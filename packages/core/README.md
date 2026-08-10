# @crescent/core (Python)

Shared backend helpers. **Never imports from any `services/*`** — it's the shared
foundation, not a dumping ground.

## What's in it right now
The **access-token verifier**. Pulse and Forge use this to check a caller's JWT
without ever touching identity's database or copying its signing key — they
fetch identity's public key(s) once, cache them, and verify locally.

Plus a small **pagination** helper (`Page`, `PageParams`, `page_params`) so every
service's list endpoints share one `limit`/`offset` shape, an optional
**revocation check** (`RevocationChecker`, `Verdict`) that cuts a killed session
short, and the **service client** (`ServiceTokenClient`, `IdentityUnavailable`)
it calls identity through.

## Install (from another service in this monorepo)
Editable install so changes in `packages/core/` land immediately, no rebuild:

```bash
pip install -e ../../packages/core
```

Or add to a service's `requirements.txt`:

```
-e ../../packages/core
```

## Usage in a product (Pulse / Forge)

```python
from fastapi import FastAPI, Depends
from crescent_core import JWKSClient, current_user_dep, require_dept_role, TokenClaims

app = FastAPI()

# Once, at startup — a single shared client for the app's lifetime.
jwks = JWKSClient(jwks_url="http://identity:8000/.well-known/jwks.json")
current_user = current_user_dep(jwks_client=jwks, issuer="cyphercrescent-identity")
dept_manager = require_dept_role(current_user, "manager", "admin")

@app.get("/me")
def me(user: TokenClaims = Depends(current_user)):
    return {"user_id": user.user_id, "memberships": user.memberships}

@app.post("/departments/{dept_id}/reports/{report_id}/approve")
def approve(dept_id: int, report_id: int, user: TokenClaims = Depends(dept_manager)):
    # 401 if unauthenticated; 403 if the caller isn't a member of THIS dept_id, or
    # their role in it isn't manager/admin. Platform admins pass every check.
    ...
```

`require_dept_role` reads `dept_id` **from the path**, so the check is always
against the department actually being acted on — a manager in Engineering gets no
manager rights in Data. Pass no roles to require membership only.

## What the verifier guarantees
- Signature valid against identity's **public** key (RS256).
- Not expired.
- Issuer matches what you configured.
- `token_type == "access"` (refresh tokens can't sneak through).

Returns a `TokenClaims` object with `user_id`, `email`, `memberships`,
`is_platform_admin`, `token_version`, `leads`, and the raw payload as `.raw`.

There is **no single `dept_id`/`role`** — a person can be an admin in one
department and an engineer in another, so `memberships` is a tuple of
`DeptMembership(dept_id, team_id, role)`. Read it through the helpers:
`role_in(dept_id)`, `is_member_of(dept_id)`, `team_in(dept_id)`, `dept_ids`, and
`leads_team(team_id)` (whether the caller is a team's named lead — this is what
lets Pulse route approvals statelessly).

## Cutting a revoked session short (optional)
A token verifies locally, so a session identity killed keeps working for the rest
of its ~15 minutes. `RevocationChecker` closes that to about a minute by asking
identity for the user's current `token_version`:

```python
from crescent_core import RevocationChecker, ServiceTokenClient, current_user_dep

identity = ServiceTokenClient(base_url="http://identity:8000", client_id="pulse", client_secret=SECRET)
current_user = current_user_dep(jwks, issuer="cyphercrescent-identity",
                                revocation_checker=RevocationChecker(identity))
```

One `POST /internal/users/token-versions` per user per TTL (60s by default),
however many requests arrive. A `tv` below identity's is `STALE` and 401s; an id
identity explicitly says it doesn't have is `UNKNOWN` and also 401s. **Everything
else is `UNAVAILABLE`, never `UNKNOWN`** — a failed lookup is the absence of an
answer, and reading it as one would log the whole platform out the moment identity
blinked. So `UNAVAILABLE` is accepted, logged (throttled to one line per 30s) and
backed off for 10s before the next attempt.

`ServiceTokenClient` is how a product authenticates as *itself*: OAuth2
client-credentials against identity's `/oauth/token`, the token cached in-process
until just before it expires and re-minted once on a 401. `lookup(path, user_ids)`
(≤200 ids) raises `IdentityUnavailable` on every failure path, so a caller can
never mistake a broken call for an answer.

## What it does NOT do
- Doesn't hit identity's database.
- Doesn't talk to identity at all after JWKS is cached (TTL: 1 hour by default),
  unless you wire the revocation checker above.
  An unknown `kid` triggers an early refresh so rotations land without a restart,
  but at most once every 30s (`min_refresh_interval_seconds`) — otherwise anyone
  waving a token with a made-up `kid` could make us fetch once per request, and
  auth runs before the rate limiter. Worst case a rotated key takes that interval
  to become usable.
- Doesn't know or care what roles exist. That's the product's job.
