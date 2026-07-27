# Pulse — Engineering Performance & Reporting

Product 1. Weekly engineering reports: an engineer drafts one, submits it, and
their team lead approves / rejects / asks for changes, with a full history and
comments. GitHub sync (Week 3) and AI-drafted summaries (Week 4) build on top.

**Week 2 status: reporting backend built.** Reports, approvals and comments,
with their own database, Alembic migrations, and tests. Auth is delegated to
identity — Pulse verifies tokens locally, never calls identity's DB.

Sits alongside the other product, **Forge** (`services/forge/`).

## Boundaries (CLAUDE.md rules 2–4)
- Owns its own database (`pulse`). Never reads identity's DB.
- References people/teams by `user_id` / `team_id` / `dept_id` from the token.
  Stores no names/emails/avatars — those live in identity.
- Verifies tokens locally with identity's public keys (JWKS), via the shared
  `packages/core`. The signing key never leaves identity.

## Who can do what (from the token, per decisions doc Decision 6)
- **Write / edit / submit** a report: its author, and only while it's a draft or
  sent back for changes.
- **Read** reports: the author; anyone with the `manager` or `admin` role in the
  report's department (department-wide, read-only); a platform admin.
- **Approve / reject / request changes**: the report's **team lead**
  (`Team.manager_user_id`, carried in the token's `leads`), with a department
  **admin** as the cover for an absent lead, or a platform admin. The `manager`
  role alone can read every report but cannot approve — only the named lead does.

## Endpoints

| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/` · `/health` | — | Service ping · DB reachable check |
| POST | `/reports` | member | Open a weekly draft (`dept_id`, optional `week_start`) |
| GET | `/reports?dept_id=` | member | List (paginated; filters `team_id`,`author_user_id`,`status`) |
| GET | `/reports/{id}` | reader | One report |
| PATCH | `/reports/{id}` | author | Edit a draft / changes-requested report |
| DELETE | `/reports/{id}` | author, draft only | Delete an unsent draft; once submitted, nobody can delete it |
| POST | `/reports/{id}/submit` | author | Send to the team lead for review |
| POST | `/reports/{id}/approve` | team lead / admin | Approve a submitted report |
| POST | `/reports/{id}/reject` | team lead / admin | Reject (optional `note`) |
| POST | `/reports/{id}/request-changes` | team lead / admin | Send back to the author |
| GET | `/reports/{id}/approvals` | reader | Append-only decision history (paginated) |
| POST / GET | `/reports/{id}/comments` | reader | Add / list flat comments (paginated) |
| PATCH / DELETE | `/reports/{id}/comments/{cid}` | comment author | Edit / delete your own comment |

Interactive docs at `/docs`. Paste the raw identity access token (starts `eyJ`)
in Swagger's **Authorize** box.

## Run it

```bash
# From the repo root, with the sandbox Postgres up (docker compose up postgres):
cp services/pulse/.env.example services/pulse/.env   # edit if needed
docker compose up pulse                              # http://localhost:8002

# Or standalone (needs a running identity for token verification):
pip install -e packages/core
pip install -r services/pulse/requirements.txt
cd services/pulse && alembic upgrade head && uvicorn app.main:app --reload
```

## Tests

```bash
pip install -e packages/core
pip install -r services/pulse/requirements-dev.txt
cd services/pulse && pytest
```

SQLite in-memory; the auth dependency is overridden so tests inject token claims
directly (token *verification* is covered by `packages/core` + the contract
tests). No DB server or identity instance needed.

## Not built yet (later weeks)
- GitHub OAuth + sync jobs (Celery/Redis) that populate report activity — **Week 3**.
- AI-drafted summaries, PDF export, email-on-ready — **Week 4**.
- Name resolution (showing who `author_user_id` is) via identity's API — pairs
  with the Nuxt frontend in **Week 5**.

## Stack
FastAPI + PostgreSQL + SQLAlchemy + Alembic. Redis + Celery arrive with GitHub
sync (Week 3). Frontend: Vue 3 + Nuxt + TypeScript + Tailwind (Week 5).
