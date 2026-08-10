# Pulse — Engineering Performance & Reporting

Product 1. Weekly engineering reports built around **repositories**: an engineer
drafts a report for a repo they worked in, submits it, and the repo's **lead or
deputy** approves / rejects / asks for changes — with a full history and comments.
On top sits a **GitHub sync** that pulls each engineer's real activity (commits,
PRs, reviews, issues) so reports start from real data. Week 4 adds an **AI draft**
step (summaries written by an LLM from that activity), **PDF export**, and an
**email notification** when a report is submitted for review.

**Status:** Week 2 (reporting backend), Week 3 (GitHub sync + activity view),
Week 4 (AI-drafted summaries, PDF export, email-on-submit) and Week 5 (the Nuxt
frontend in `frontend/`) built and tested. Auth
is delegated to identity — Pulse verifies tokens locally, never calls identity's DB.

Sits alongside the other product, **Forge** (`services/forge/`).

## Boundaries (CLAUDE.md rules 2–4)
- Owns its own database (`pulse`). Never reads identity's DB.
- References people/repos/departments by id (`user_id` / `dept_id`, and its own
  `repo_id`). Stores no names/emails/avatars — those live in identity.
- Verifies tokens locally with identity's public keys (JWKS), via the shared
  `packages/core`. The signing key never leaves identity.

## The model (repo-centric — decisions doc 2026-07-30)
- A report is **about a repo**: one report per **(engineer, repo, week)**. Working
  in two repos in a week means two reports.
- Each repo belongs to a **department** and has a **lead + deputy**; **both
  approve** its reports (co-approvers). Department/platform admins may also approve.
- **Who reads:** author → own · repo lead/deputy → their repo · department admin →
  the department · platform admin → everything.
- **Who reports on a repo:** someone with synced activity in it (or the repo's
  lead/deputy, or an admin). Membership is derived from GitHub activity, not a
  hand-kept roster.

## Endpoints

**Reports**

| Method | Path | Who | Purpose |
|---|---|---|---|
| POST | `/reports` | contributor to the repo | Open a weekly draft (`repo_id`, optional `week_start`) — rate-limited to **30/minute** per caller |
| POST | `/reports/generate` | contributor to the repo | AI-draft a weekly report from your synced GitHub activity (`repo_id`, optional `week_start`) — creates or regenerates a draft; rate-limited to **10/hour** per caller |
| GET | `/reports` | scoped | List (paginated; filters `repo_id`, `dept_id`, `author_user_id`, `status`) |
| GET | `/reports/review-queue` | repo lead/deputy, dept/platform admin | The approver's inbox: reports awaiting *your* decision across every repo you approve for (`?status=`, defaults to `submitted`; paginated) |
| GET | `/reports/{id}` | reader | One report |
| GET | `/reports/{id}/pdf` | reader | Download the report as a PDF (`application/pdf`) |
| PATCH | `/reports/{id}` | author | Edit a draft / changes-requested report |
| DELETE | `/reports/{id}` | author, draft only | Delete an unsent draft; once submitted, nobody can |
| POST | `/reports/{id}/submit` | author | Send to the repo's lead/deputy |
| POST | `/reports/{id}/approve` · `/reject` · `/request-changes` | repo lead/deputy or admin | Decide a submitted report (optional `note`) |
| GET | `/reports/{id}/approvals` | reader | Append-only decision history (paginated) |
| POST / GET | `/reports/{id}/comments` | reader | Add / list flat comments (paginated) |
| PATCH / DELETE | `/reports/{id}/comments/{cid}` | comment author | Edit / delete your own comment |

**Admin**

| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/admin/llm-usage` | platform admin | LLM consumption so far: `{total_tokens, generation_count}` (optional `?since=YYYY-MM-DD`) — so the admin knows when to top up the account |

### Report generation, PDF & email (Week 4)

- **`POST /reports/generate`** (`{repo_id, week_start?}`, contributor to the repo)
  creates a **draft** whose three summaries — `summary_manager`, `summary_exec`,
  `next_week_goals` — are AI-written from the engineer's real synced GitHub activity
  for that week (`week_start` defaults to this week's Monday). You then edit with
  `PATCH /reports/{id}`, submit, and it's approved/rejected as usual. Regenerating
  overwrites an existing **editable** draft. Failure modes:
  - **empty week → 422** (the LLM is never called, no report created);
  - **existing non-editable report** (already submitted/approved/rejected) **→ 409**;
  - **LLM error after one retry → 502**;
  - **over 10 generations an hour → 429** (each one costs tokens, so this is a real
    throttle; `POST /reports` is separately capped at 30/minute as a loose guard
    against a runaway client).
  A generated draft records `prompt_version` — the version of the prompt that wrote
  it, from `app/services/prompts.py`. It's on `ReportResponse` next to `generated_at`
  for the same reason that field is: together they say whether a report was AI-written,
  when, and with which prompt, which is what makes "the summaries got worse after we
  changed the prompt" answerable. Hand-written reports (and anything generated before
  the column existed) read `null`. Editing a draft by hand leaves it as it is, exactly
  like `generated_at`.
- **`GET /reports/{id}/pdf`** returns `application/pdf` (rendered with reportlab),
  gated behind the same read permission as viewing the report. Drafts export too,
  with their status shown on the page. Report text is escaped before it reaches
  reportlab: `Paragraph` parses a small XML-like markup, so an unescaped summary
  mentioning `R&D` or `<100ms` rendered wrong and a stray `</b>` raised and 500'd the
  export. The `<br/>` that turns newlines in the goals list into line breaks is the
  template's own markup and is still applied after escaping.
- **`GET /admin/llm-usage`** (platform admin only) reports total tokens and
  generation count. By design, report viewers do **not** see the model or a
  per-report token count — usage rolls up only to this admin view.
- **Email on submit (real as of Week 5):** submitting a report notifies the repo's
  approvers (lead + deputy) by email. Pulse resolves their `user_id → email` by
  calling identity's `POST /internal/users/emails`, authenticating as the **`pulse`
  service** via OAuth2 client-credentials against identity's `POST /oauth/token`
  (short-lived scoped service token, cached in-process and re-minted on a 401), then
  sends via **Brevo**. The whole path is **best-effort and fires after the submit
  commit**: identity down, resolution failing, email misconfigured, or Brevo erroring
  are all logged and swallowed — a notification problem can never block or roll back a
  submission.

**GitHub — connect & sync**

| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/github/connect` | self | Get the GitHub OAuth authorize URL |
| GET | `/github/oauth/callback` | (browser) | OAuth callback — stores the token encrypted, then redirects to the frontend with a result code |
| GET / DELETE | `/github/account` | self | View / disconnect your linked GitHub account |
| POST | `/github/sync` | platform admin | Run a sync now (`?wait=true` inline; default enqueues to Celery). Platform-admin only: a sync hits every allowlisted repo across all departments and spends the shared GitHub quota, so it isn't a per-department call |
| GET | `/github/sync-runs` | scoped | Sync history for repos you can see, newest first (paginated; `?repo_id=`) — why your data is stale |

**Where the callback lands.** The OAuth callback renders no page of its own. GitHub
has to redirect to Pulse (Pulse holds the client secret), but the person is in a
browser and has nowhere to go from an API response, so every outcome ends in a **303
to `{FRONTEND_URL}/?github=<code>`** with one of six codes: `connected`, `denied` (turned
it down on GitHub's consent screen), `expired` (the signed `state` is stale or
invalid — start again from `/github/connect`), `already_linked` (that GitHub account
belongs to another user), `not_configured` (no `GITHUB_CLIENT_ID`/`SECRET` on the
server) and `failed` for everything else, including GitHub being unreachable during
the token exchange. Codes rather than messages: the wording belongs to the UI, and
error text has no business sitting in browser history. The redirect target is built
from `FRONTEND_URL` plus that fixed set — **no value from the request reaches it**, so
whoever calls the callback can't aim the browser somewhere else.

**GitHub — repo administration**

| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/github/repositories` · `/{id}` | scoped | List / view repos **you can see** (paginated) — see "Who sees a repo" below. A repo outside your scope reads as **404**, not 403 |
| PUT | `/github/repositories/{id}/department/{dept_id}` | dept/platform admin | File the repo under a department |
| PUT | `/github/repositories/{id}/lead/{user_id}` · `deputy/{user_id}` | dept/platform admin | Set the repo's lead / deputy |
| DELETE | `/github/repositories/{id}/lead` · `deputy` | dept/platform admin | Clear the repo's lead / deputy (no `user_id` in the path) |
| PUT / DELETE | `/github/repositories/{id}/tracked` | dept/platform admin | Resume / stop syncing this repo. Not a visibility rule — history and reports stay readable |

**Who sees a repo:** a platform admin (all of them), its lead or deputy, anyone in
the department it's filed under, or anyone who has **worked in it** — authored a
commit, PR or issue there, or reviewed a PR there. That last rule is what makes a
freshly synced repo visible before an admin has filed it under a department.
Visibility is not permission: working in a repo never lets you set its department,
lead or deputy.

**Activity view**

| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/activity/me` | self | Your synced activity (counts + recent commits/PRs/reviews/issues) |
| GET | `/activity/{user_id}` | scoped | Someone's activity (filters: `since`, `repo_id`) |

Scoping on `/activity/{user_id}`: you see all of your own; a platform admin sees
anyone's; a repo lead/deputy or a department admin sees only what that person did in
the repos they oversee. Anyone with a token may ask — a caller who oversees none of
that person's repos gets a **200 with zeroed counts**, not a 403. Pulse can't read
identity's user→department data, so it derives a manager's reach from which
department each *repo* is filed under; a 403 there would fire just as loudly for a
new joiner with no synced activity as for a real permissions problem. The empty
response says nothing about whether the person, the repo, or the activity exists. A
`repo_id` outside your scope is treated the same way: intersected with the scope, so
it returns an empty response rather than confirming the repo exists.

### Rate limits — and whose allowance it is

| Route | Limit | Counted per |
|---|---|---|
| `POST /reports/generate` | 10/hour | verified user |
| `POST /reports` | 30/minute | verified user |
| `GET /github/connect` | 10/minute | verified user |
| `POST /github/sync` | 5/minute | verified user |
| `GET /github/oauth/callback` | 20/minute | client address |

"Per caller" means **per user id read out of a fully verified access token**, not per
client address. Address-keying an authenticated route is worse than no limit behind a
proxy or an office NAT: everyone lands in one bucket, so the first busy engineer locks
out the whole floor while an attacker on a different address is barely touched — and
on `/reports/generate` the bucket is real OpenAI spend.

The key is derived *before* route dependencies run, so it comes from the
`Authorization` header directly. The token is **verified in full** (signature against
identity's published JWKS, issuer, expiry, token type) rather than just decoded: a key
taken from an unverified `sub` would let anyone claim a fresh bucket per made-up value,
or aim one at a colleague and drain their generation allowance. That means the
signature is checked twice on these routes — once for the key, once by the auth
dependency — which is a public-key verify against the cached JWKS, not a call to
identity. Anything absent, malformed, expired, wrongly issued, or signed by the wrong
key falls back to the **client address**, never to a shared constant.

The OAuth callback is the one address-keyed route, because GitHub redirects a browser
there with no token at all; its trust comes from the signed `state`.

Same design as identity's (`services/identity/app/rate_limit.py`) — one pattern across
the platform.

### Names on responses

Pulse stores people as ids only (Rule 3 — it never keeps its own copy of a user), so
a raw response used to say `author_user_id: 6` and nothing else. Responses now carry
a **name object alongside** each id, resolved from identity:

| Response | id field (unchanged) | added |
|---|---|---|
| Report | `author_user_id` | `author` |
| Approval | `actor_user_id` | `actor` |
| Comment | `author_user_id` | `author` |
| Repository | `lead_user_id`, `deputy_user_id` | `lead`, `deputy` |
| Activity (`GET /activity/me`, `GET /activity/{user_id}`) | `user_id` | `user` |

```json
{
  "id": 12, "author_user_id": 6,
  "author": {"user_id": 6, "first_name": "Ada", "last_name": "Lovelace",
             "avatar_url": null, "is_active": true}
}
```

**Additive, not a replacement.** The id fields keep their names, types and meaning —
permission logic and links are built on them, and a name can be absent. Use the id
for anything that has to be right; use the object for what's on screen.

The name object is `null` when identity doesn't recognise the id (a departed user
whose record is gone) **or** when identity can't be asked at all. Resolution is
best-effort: identity being down, slow, or not yet granting Pulse the
`users:read:profile` scope means names are missing, never a failed request. Names
come from `POST /internal/users/profiles` (service token, `users:read:profile`
scope) — one batched call per response no matter how many people are in it, cached
in-process for 5 minutes. No email is exposed; that sits behind a higher-privilege
scope Pulse only uses for notifications.

The activity response describes exactly one person: the recent commits, PRs, reviews
and issues on it carry repo and PR ids, not user ids, so there is nothing else to name.

**PDF export.** `GET /reports/{id}/pdf` prints the author as
`Ada Lovelace (#6)` — name for the reader, id kept because an exported file gets
forwarded to people who can't tell two Ada Lovelaces apart. If identity can't be
reached or doesn't know the id, it falls back to `Engineer #6`, the line the PDF
printed before names existed. A failed lookup costs readability, never the export.

Interactive docs at `/docs`. Paste the raw identity access token (starts `eyJ`)
in Swagger's **Authorize** box.

## Background jobs (GitHub sync)
Celery + Redis run the sync. A daily **beat** schedule fires
`app.tasks.sync_all_repos` (hour set by `SYNC_HOUR_UTC`); a worker consumes it and
pulls each allowlisted repo (`GITHUB_REPOS`, a comma-separated list of `owner/name`)
**incrementally** — only what changed since the repo's `last_synced_at` — with GitHub
pagination and rate-limit handling. `POST /github/sync?wait=true` runs one pass inline
for demos.

Each repo's pass is recorded as a `SyncRun` with a status of **`running` ·
`success` · `error` · `rate_limited` · `skipped`**. `rate_limited` is its own status on
purpose: GitHub's quota being spent is not a failure of ours, so "we were throttled" (with
when it can resume, in `detail`) never reads as "the sync is broken" — the next
scheduled pass picks the repo up again.

**Reading the history.** `GET /github/sync-runs` returns those rows newest-first and
paged, scoped like the repository list — you see sync history for repos you can see.
`?repo_id=` narrows it to one repo. This is deliberately not admin-only: an engineer
whose week looks empty should be able to see that the last pass was rate-limited
without asking anyone. Each item carries `status`, `detail`, `started_at`,
`finished_at` and the repo's `full_name`. The repo-less rows (`no repos configured`,
`no connected GitHub account`) are platform-config problems and only a platform admin
sees them.

**When someone leaves.** Deactivating a user happens in identity, and identity has no
way to tell Pulse about it — a product being pushed at by identity is exactly the
coupling rule 2 forbids. So Pulse checks for itself, over the channel it already uses:
the `POST /internal/users/profiles` call that resolves names also returns `is_active`,
and names the ids it has no user for in `unknown_user_ids`. Every sync pass starts by
asking about the users who have a stored GitHub credential and **deleting the
credential of anyone identity reports as inactive *or* as unknown**, before any token
is decrypted — so no pass ever calls GitHub with a departed employee's token.
Deactivated and hard-deleted both count as departed, for the same reason: the
credential belongs to someone who is gone. A deleted user has no profile row left to
carry `is_active: false`, so without the second case their stored GitHub token would
outlive the account entirely.
A revocation is recorded as a repo-less `SyncRun` row (platform-admin visible, like
the other platform-level rows) naming the user ids; nothing is written when nobody
left.

**Only the credential goes.** Their commits, PRs, reviews and issues stay, still
attributed to them: reports covering past weeks have to keep adding up, and
attribution is history, not a live permission. Once their account row is gone their
GitHub login no longer maps to a user id, so a later pass that re-lists an old item
(GitHub returns a PR again when it's commented on) **keeps** the attribution already
on the row rather than blanking it.

**An identity outage deletes nothing.** The cleanup works off a `ProfileAnswer`
(`resolve_profiles_answer`) whose two fields are both **things identity actually
said**: `profiles` are the ids it returned a row for, `unknown` are the ids it listed
in `unknown_user_ids`. Neither is computed by subtracting the answer from the request,
so an id identity never got to — a batch that timed out, 403'd or 500'd — appears in
*neither* field and is left alone. Deletion needs a positive statement: an explicit
`is_active: false`, or an explicit "no such user". A pass that gets nothing back at all
(identity down, slow, unauthenticated, scope not granted, no service secret configured)
bails out and logs that it was skipped. Absence is never a verdict, because reading it
as one would wipe every stored GitHub credential on the platform the first time
identity restarted.

**That leans on identity sending `unknown_user_ids`.** It's the only way Pulse can
tell "deleted" from "not answered", and an identity build that omits the field doesn't
fail loudly — `unknown` just comes back empty and cleanup quietly narrows to
deactivated users only, leaving a hard-deleted user's credential in place. Worth
knowing about, since the symptom is less cleanup rather than an error.

**Turning a repo off.** `DELETE /github/repositories/{id}/tracked` clears
`is_tracked` and `PUT` sets it back; both take a platform admin or an admin of the
repo's department, the same rule as naming a lead. An untracked repo is skipped
before any GitHub call, so it costs no API quota, and the skip is recorded as a
`skipped` `SyncRun` — "nothing happened" and "nothing was meant to happen" have to be
tellable apart. Untracking is **not** a visibility rule: the repo, its history and its
reports stay readable, and it stays in `GET /github/repositories` so it can be turned
back on. Pass `?tracked_only=true` to filter it out of that list.

Under docker-compose these run as the `pulse-worker` and `pulse-beat` services
(same image as `pulse`, different command) against the `redis` service.

## Run it

```bash
# From the repo root, with the sandbox Postgres + Redis up:
cp services/pulse/.env.example services/pulse/.env   # fill in GITHUB_* + a Fernet key
docker compose up pulse pulse-worker pulse-beat       # http://localhost:8002

# Or standalone (needs a running identity for token verification):
pip install -e packages/core
pip install -r services/pulse/requirements.txt
cd services/pulse && alembic upgrade head && uvicorn app.main:app --reload
```

Connecting GitHub needs an **OAuth App** (Client ID/Secret in `.env`) and a
`GITHUB_TOKEN_ENC_KEY` (a Fernet key). See `.env.example`.

### Config — LLM & email (Week 4)

| Var | Default | Purpose |
|---|---|---|
| `LLM_API_KEY` (or `OPENAI_API_KEY`) | `""` | OpenAI key for report generation. Either name works (alias). |
| `LLM_MODEL` | `gpt-4o-mini` | Model used for generation. |
| `LLM_TIMEOUT_SECONDS` | `30.0` | Per-call provider timeout. |
| `LLM_MAX_OUTPUT_TOKENS` | `1000` | Output cap per generation. |
| `BREVO_API_KEY` | `""` | Brevo key for the real email send on submit. |
| `EMAIL_FROM` | `""` | Sender address for notifications. |
| `FRONTEND_URL` | `http://localhost:3000` | Base for the report link in notification emails. |
| `IDENTITY_API_URL` | `http://identity:8000` | Identity's internal URL — used for the `/oauth/token` + `/internal/users/emails` + `/internal/users/profiles` service calls. |
| `PULSE_SERVICE_CLIENT_ID` | `pulse` | Client id Pulse authenticates as (client-credentials). |
| `PULSE_SERVICE_CLIENT_SECRET` | `""` | Shared secret for that client. Empty = email and name resolution refuse to call (log-and-skip; responses just carry no names). |

The `PULSE_SERVICE_CLIENT_SECRET` here **must match** the `pulse` client seeded in
identity via its `PULSE_CLIENT_SECRET` — same shared secret on both sides, or the
`/oauth/token` call is rejected and the notification is skipped.

### Config — rate limiting

| Var | Default | Purpose |
|---|---|---|
| `RATE_LIMIT_ENABLED` | `true` | Master switch. The test suite turns it off. |
| `TRUST_PROXY_HEADERS` | `false` | Whether to read the client address out of `X-Forwarded-For`. |
| `TRUSTED_PROXY_COUNT` | `1` | How many proxies of yours sit in front of Pulse. |

`X-Forwarded-For` is **just a request header — anyone can send one.** Trusting it while
Pulse is reachable directly lets a caller send a different value on every request and
bypass every address-based limit, which is strictly worse than not reading the header at
all. Only set `TRUST_PROXY_HEADERS=true` when Pulse really does sit behind a reverse
proxy or load balancer **you** run. Each hop appends the address it saw, so the entry
`TRUSTED_PROXY_COUNT` from the **right** is the last one a trusted proxy wrote and
everything to its left came from the caller — count your hops rather than guessing, or
you go back to reading a caller-controlled value.

**The key must live in `services/pulse/.env`.** Pulse reads *its own* `.env` from
this directory (`services/pulse/`); a key set only in the repo-root `.env` is **not**
picked up by the running service. Set it as `LLM_API_KEY` **or** `OPENAI_API_KEY`.
Generation needs a real key; the test suite mocks the provider, so tests need none.

## Tests

```bash
pip install -e packages/core
pip install -r services/pulse/requirements-dev.txt
cd services/pulse && pytest
```

SQLite in-memory; the auth dependency is overridden so tests inject token claims
directly, and GitHub is faked (no network). No DB server or identity instance
needed.

## Not built yet (later weeks)
- GitHub webhooks (near-real-time) — deferred; the daily sync covers Week 3.

## Stack
FastAPI + PostgreSQL + SQLAlchemy + Alembic + Celery + Redis. Frontend: Vue 3 +
Nuxt + TypeScript + Tailwind, in `frontend/`.
