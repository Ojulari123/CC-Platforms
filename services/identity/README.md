# Identity service

Single source of truth for accounts, departments, teams, memberships, and tokens.
Every product (Pulse, ML platform) trusts tokens issued here.

## What lives here vs elsewhere
- **Here:** users, departments, teams, memberships, passwords, refresh tokens, JWT signing.
  Owns "who a person is": name, email, avatar.
- **Not here:** anything product-specific. Pulse owns its own copy of user info it
  needs (GitHub handle, etc.), keyed by `user_id`. Products never touch identity's DB.

## Getting in (two doors)
- **`POST /auth/register`**: **bootstrap only.** Creates the first user as a
  platform admin. It **closes the moment a platform admin exists** (any later call
  → 403 "Registration is closed"), so it can only ever mint the founder.
- **`POST /auth/signup`**: **open self-signup.** Creates a plain, **non-admin
  account with no department** (empty `memberships` on `/me` until placed, which is expected,
  not a bug). Gated by `SIGNUP_ALLOWED_DOMAINS`: empty = any email domain allowed;
  set to a comma-separated list (e.g. `cyphercrescent.com`) to lock signup to the org
  (off-domain email → 403).
- **`POST /departments/{dept_id}/members`**: **admin placement.** Puts an existing
  user (e.g. a fresh self-signup) into a department with a role/team. Dept admin or
  platform admin only. The counterpart to invites for people who already have an account.

## Platform directory & service-to-service auth
- **`GET /platform/users`**: workspace-wide user directory, **platform admin only**
  (filters `q`, `is_active`, `limit`, `offset`). Distinct from a department roster,
  which is scoped to one department.
- **`POST /platform/users/{id}/deactivate`**: the normal path for someone leaving.
  The account and their name survive so old reports still say who wrote them; they
  can't log in and every session dies immediately. Reversible via `/reactivate`.
- **`DELETE /platform/users/{id}`**: **permanent**, platform admin only, and only
  for an account that has never been part of the workspace (a typo'd signup, a
  leftover test login). Identity can't see whether someone authored anything in
  Pulse and won't read another service's database, so it refuses unless *every*
  signal it can see says the account is untouched: no department membership, heads
  no department and leads no team, not a platform admin, not you, and **never
  onboarded**, with `users.onboarded_at` still null. That column is stamped the first
  time the account is placed in a department and never cleared, so it still refuses
  an ex-employee whose membership row was deleted when they left. It replaced a
  `token_version > 0` check, which meant a typo'd signup that merely changed its own
  password became permanently undeletable; changing a password or signing out
  everywhere no longer blocks deletion. `email_verified` and "ever accepted an
  invite" are still checked as backstops (both are subsets of `onboarded_at` today).
  Any of those → **400** naming the reason and pointing at deactivation. On success:
  **204**, and their refresh tokens, password reset tokens and memberships go with
  them; a pending invite they *sent* survives with no named inviter
  (`invites.invited_by` is `ON DELETE SET NULL`).
- **`POST /oauth/token`**: OAuth2 **client-credentials** grant (only that grant),
  a service authenticates as itself (`client_id` + `client_secret`) and gets a
  short-lived, scoped **service token**. Backed by the `service_clients` table; the
  `pulse` client is seeded on startup from `PULSE_CLIENT_SECRET` (no-op if unset) with
  scopes `users:read:email users:read:profile tokens:verify`.
- **`POST /internal/users/emails`**: resolve `user_id → email` for another service
  (Pulse, for approver notifications). **Service-token + scope gated**
  (`users:read:email`); unknown ids are silently omitted.
- **`POST /internal/users/profiles`**: resolve `user_id → first_name, last_name,
  avatar_url, is_active`, so a product can render a person instead of a bare id.
  **Service-token + scope gated** (`users:read:profile`, deliberately a *different,
  lower-privilege* scope than `users:read:email`, so a service that only draws names
  cannot pull the company's email list). Carries **no email**. The answer is **total**:
  ids that don't resolve are still omitted from `users` (unchanged for existing callers)
  and are additionally listed in `unknown_user_ids`, so a caller can tell "no such user"
  from "identity didn't answer". Omission alone was ambiguous, which is why Pulse could
  never safely clean up after a hard-deleted account. Both lists are sorted by id, but
  key by `user_id`; they are not positionally aligned with the request.
  **Deactivated users still resolve** (an old report must still show its author's name),
  are flagged `is_active: false`, and are never reported unknown. Batch capped at
  **200 ids** per call; over that is a 422.
- **`POST /internal/users/token-versions`**: resolve `user_id → token_version`, the
  number a service compares against the `tv` claim in a presented access token. Without
  it a downstream verifying locally against JWKS keeps honouring a token for up to 15
  minutes after "log out everywhere", because identity is never asked. **Service-token +
  scope gated** on its own scope `tokens:verify`: it is a verification primitive, not a
  people-directory read, and every token-verifying service needs it while none should
  have to hold `users:read:email`/`users:read:profile` to get it. Carries **no PII**:
  `{"users": [{"user_id": 1, "token_version": 3}], "unknown_user_ids": []}`. Total over
  the requested ids, same shape as `/internal/users/profiles`: an id in `unknown_user_ids`
  has no version to compare against, so the caller must **reject** its tokens rather than
  read the silence as "still valid". Deactivation bumps `token_version` too, so the number
  alone already condemns an offboarded person's tokens. Batch capped at **200 ids**; over
  that is a 422.

Migrations run `0001`–`0010` (`0010_user_onboarded_at` adds `users.onboarded_at`, the
explicit "this account was really onboarded" stamp the delete guard reads).

## Run standalone (without Docker)
```bash
cd services/identity
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# generate signing keys (RS256) — required
mkdir -p keys
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out keys/private.pem
openssl rsa -pubout -in keys/private.pem -out keys/public.pem

cp .env.example .env
# edit DATABASE_URL if needed

uvicorn app.main:app --reload --port 8001
```

## Run via docker-compose (recommended)
From repo root:
```bash
cp .env.example .env
cp services/identity/.env.example services/identity/.env
docker compose up --build identity
```
Health check: `curl http://localhost:8001/health`

## Structure
```
app/
├── main.py          FastAPI app + CORS
├── config.py        Pydantic Settings (env-driven)
├── db.py            SQLAlchemy engine + get_db dependency
├── routes/          HTTP endpoints (thin)
├── services/        business logic
├── models/          SQLAlchemy ORM models
├── schemas/         Pydantic request/response schemas
└── security/        password hash, JWT sign/verify, refresh rotation, JWKS
alembic/             migrations
```

## Design notes

The long version of decisions the code only has room to state in a line or two.
Code comments point here rather than repeating this.

### Signing keys and rotation
Keys are read **once per process, at startup**, and never refreshed at runtime.
`app/security/keys.py` caches every reader and only tests clear it. Editing
`keys/` does nothing until identity restarts. Startup also parses every `*.pem` in
`JWT_RETIRED_PUBLIC_KEYS_DIR` and **refuses to boot** on a bad one, naming the file:
a loud failed deploy beats either silently dropping a key (everyone holding a token
signed by it is logged out with no signal) or 500ing `/.well-known/jwks.json` later
(that endpoint is how every service verifies tokens). Retired keys are published for
verification only; nothing signs with them. Full operator procedure, the phase
waits, and pruning: **`docs/runbook-identity-key-rotation.md`**.

### Rate-limit keys (`app/rate_limit.py`)
Unauthenticated routes are keyed per client address, authenticated ones per user, because
one person burning their quota must not lock out everyone behind the same office
NAT or mobile carrier.

`X-Forwarded-For` is a caller-supplied header, so trusting it unconditionally hands
out a fresh bucket per made-up value. It is only read when `TRUST_PROXY_HEADERS` is
on, and then hops are counted **from the right**: each hop appends the address it
saw, so the entry `TRUSTED_PROXY_COUNT` from the right is the last one a proxy we
run wrote. Everything left of that came from the caller and can say anything.

The per-user key **fully verifies** the token rather than reading `sub` from an
unverified claim. Otherwise anyone could forge a header to mint a fresh bucket, or
aim one at another user. The cost is a second public-key verify on those routes
(the auth dependency verifies again). Anything absent, malformed or unverifiable
falls back to the address, never to a shared or empty key.

### What revokes what
`token_version` (the `tv` claim) is **per user**, so bumping it signs the person out
of every device on their next request.

- **Logout one device** (`revoke_refresh_token`) deliberately does *not* bump it.
  That device's access token stays alive until it expires (≤15 min); anything more
  would sign the person out everywhere just because they closed one browser.
- **Refresh-token reuse** (a revoked token presented again) *does* bump it, on top of
  revoking the whole token family. Revoking the family only stops new pairs being
  minted, and the access token already in the thief's hands would keep reading data
  until it expired. Reuse is a theft signal, and under-revoking on one is the worse
  failure than the person losing their other sessions.
- Password change/reset, deactivation, and platform-admin grant/revoke all bump it
  too, the last two because the old token's claims are now wrong.

### Why `users.onboarded_at` exists (the delete guard)
`DELETE /platform/users/{id}` needs durable, identity-side evidence that an account
was really part of the workspace, and `remove_member` hard-deletes the membership
row, so a live-membership count cannot tell "never joined" from "was in Engineering
for two years". `onboarded_at` is stamped the first time an account is placed in a
department and never cleared, so it says exactly that.

It replaced a `token_version > 0` check, which stood in for the same thing but fired
on any password change: a typo'd signup that merely reset its own password became
permanently undeletable.

`email_verified` and "ever accepted an invite" are subsets of it today (every path
that sets either also creates a membership) and are kept as backstops rather than
removed, because a missed `onboarded_at` write would be an irreversible delete. If a
standalone "verify your email" flow is ever added for plain signups, **drop the
`email_verified` branch**: it would then re-create exactly the false positive
`onboarded_at` was introduced to remove.

Migration `0010`'s backfill is deliberately wider than "everyone with a membership":
it stamps every account the old rule would have refused (any membership, or
`token_version > 0`, or `email_verified`, or an accepted invite for their address),
so nobody undeletable before the migration is deletable after it.
