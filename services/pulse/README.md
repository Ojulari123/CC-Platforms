# Pulse — Engineering Performance & Reporting

Product 1. Weekly engineering reports built around **repositories**: an engineer
drafts a report for a repo they worked in, submits it, and the repo's **lead or
deputy** approves / rejects / asks for changes — with a full history and comments.
On top sits a **GitHub sync** that pulls each engineer's real activity (commits,
PRs, reviews, issues) so reports start from real data. Week 4 adds an **AI draft**
step (summaries written by an LLM from that activity), **PDF export**, and an
**email notification** when a report is submitted for review.

**Status:** Week 2 (reporting backend), Week 3 (GitHub sync + activity view), and
Week 4 (AI-drafted summaries, PDF export, email-on-submit) built and tested. Auth
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
| POST | `/reports` | contributor to the repo | Open a weekly draft (`repo_id`, optional `week_start`) |
| POST | `/reports/generate` | contributor to the repo | AI-draft a weekly report from your synced GitHub activity (`repo_id`, optional `week_start`) — creates or regenerates a draft |
| GET | `/reports` | scoped | List (paginated; filters `repo_id`, `dept_id`, `author_user_id`, `status`) |
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
  - **LLM error after one retry → 502**.
- **`GET /reports/{id}/pdf`** returns `application/pdf` (rendered with reportlab),
  gated behind the same read permission as viewing the report. Drafts export too,
  with their status shown on the page.
- **`GET /admin/llm-usage`** (platform admin only) reports total tokens and
  generation count. By design, report viewers do **not** see the model or a
  per-report token count — usage rolls up only to this admin view.
- **Email on submit:** submitting a report fires an approver notification, but it is
  **currently STUBBED** — it logs which approver `user_id`s would be emailed rather
  than sending. Real delivery is Week 5 (needs identity's `user_id → email` lookup
  plus service-to-service auth). The send path is best-effort: a notification problem
  can never block or roll back a submission.

**GitHub — connect & sync**

| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/github/connect` | self | Get the GitHub OAuth authorize URL |
| GET | `/github/oauth/callback` | (browser) | OAuth callback — stores the token encrypted |
| GET / DELETE | `/github/account` | self | View / disconnect your linked GitHub account |
| POST | `/github/sync` | admin | Run a sync now (`?wait=true` inline; default enqueues to Celery) |

**GitHub — repo administration**

| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/github/repositories` · `/{id}` | member | List / view tracked repos (paginated) |
| PUT | `/github/repositories/{id}/department/{dept_id}` | dept/platform admin | File the repo under a department |
| PUT / DELETE | `/github/repositories/{id}/lead/{user_id}` | dept/platform admin | Set / clear the repo's lead |
| PUT / DELETE | `/github/repositories/{id}/deputy/{user_id}` | dept/platform admin | Set / clear the repo's deputy |

**Activity view**

| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/activity/me` | self | Your synced activity (counts + recent commits/PRs/reviews/issues) |
| GET | `/activity/{user_id}` | self / admin / repo lead | Someone's activity (filters: `since`, `repo_id`) |

Interactive docs at `/docs`. Paste the raw identity access token (starts `eyJ`)
in Swagger's **Authorize** box.

## Background jobs (GitHub sync)
Celery + Redis run the sync. A daily **beat** schedule fires
`app.tasks.sync_all_repos` (hour set by `SYNC_HOUR_UTC`); a worker consumes it and
pulls each allowlisted repo (`GITHUB_REPOS` / `GITHUB_ORG`) **incrementally** —
only what changed since the repo's `last_synced_at` — with GitHub pagination and
rate-limit handling. `POST /github/sync?wait=true` runs one pass inline for demos.

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
| `BREVO_API_KEY` | `""` | Brevo key for the (Week-5) real email send. |
| `EMAIL_FROM` | `""` | Sender address for notifications. |
| `FRONTEND_URL` | `http://localhost:3000` | Base for the report link in notification emails. |

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
- **Real email send** — the approver notification on submit is stubbed (logs intent);
  turning it on needs identity's `user_id → email` lookup + service-to-service auth — **Week 5**.
- Name resolution (showing who `author_user_id` is) via identity's API, with the
  Nuxt frontend — **Week 5**.
- GitHub webhooks (near-real-time) — deferred; the daily sync covers Week 3.

## Stack
FastAPI + PostgreSQL + SQLAlchemy + Alembic + Celery + Redis. Frontend: Vue 3 +
Nuxt + TypeScript + Tailwind (Week 5).
