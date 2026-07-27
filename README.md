# CypherCrescent Platforms

Internal monorepo. Two products sharing one login system:

- **identity** (`services/identity`) — accounts, departments, teams, JWT tokens. Everyone trusts tokens issued here.
- **pulse** (`services/pulse`) — engineering performance reporting (GitHub sync + AI-drafted weekly reports + manager approval).
- **forge** (`services/forge`) — no-code AI/ML learning platform.

Shared code: `packages/core` (Python — starts with the JWT verifier that Pulse/Forge use to accept identity's tokens) and `packages/ui` (Vue/Nuxt shared components — not populated yet).

---

## First-time setup

```bash
# 1. RSA keypair identity uses to sign JWTs (RS256)
./scripts/generate-identity-keys.sh

# 2. Root env — feeds docker-compose (Postgres creds for the local sandbox DB)
cp .env.example .env

# 3. Identity env — the app's own settings (DATABASE_URL, JWT paths, CORS, etc.)
cp services/identity/.env.example services/identity/.env
```

Then edit `services/identity/.env` and set `DATABASE_URL` to your Neon connection string (or leave the localhost default if you're using the sandbox Postgres). The `+psycopg` prefix is required — SQLAlchemy needs it to pick up psycopg 3.

## Running the code

### Everything via Docker (closest to prod, one command)
```bash
docker compose up --build
```
- Identity API: <http://localhost:8001>
- Swagger UI: <http://localhost:8001/docs>
- Local Postgres: `localhost:5432` (sandbox — identity itself points at Neon by default)

Stop with `Ctrl+C`. Wipe the local DB volume with `docker compose down -v`.

### Identity only, no Docker (fastest inner loop)
Needs Python 3.14 and a reachable Postgres via `DATABASE_URL`.
```bash
cd services/identity
python3.14 -m venv .venv && source .venv/bin/activate    # first time only
pip install -r requirements-dev.txt                       # first time only

alembic upgrade head
uvicorn app.main:app --reload --port 8001
```

### Just the tests (no DB, no server — SQLite in-memory + ephemeral RSA keys)
```bash
cd services/identity  &&  .venv/bin/pytest    # identity suite
cd packages/core      &&  .venv/bin/pytest    # shared verifier suite
```

## Where things live

```
CC-Platforms/
├── services/identity/     FastAPI app — accounts, departments, teams, JWT
├── services/pulse/        GitHub reporting
├── services/forge/        no-code ML learning
├── packages/core/         Shared Python Components
├── packages/ui/           Shared Vue/Nuxt Components
├── scripts/               generate-identity-keys.sh, init-databases.sh
├── docker-compose.yml     Local dev stack
├── docs/sessions/         Per-conversation change logs
├── docs/backlog.md        Deferred work + why
└── CLAUDE.md              Architecture rules (READ THIS)
```

## Endpoints (identity, current)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/` | — | Service ping |
| GET | `/health` | — | DB reachable check |
| GET | `/.well-known/jwks.json` | — | Public key for products to verify tokens |
| POST | `/auth/register` | — | Bootstrap only: first user → platform admin + first department; 403 after |
| POST | `/auth/login` | — | Email + password → token pair |
| POST | `/auth/refresh` | — | Rotate refresh token, get new pair |
| POST | `/auth/logout` | — | Revoke a refresh token |
| POST | `/auth/logout-all` | Bearer | Revoke every session (bumps token_version) |
| POST | `/auth/change-password` | Bearer | Change password, kill all other sessions |
| POST | `/auth/forgot-password` | — | Email a reset link (always 204; no account enumeration) |
| POST | `/auth/reset-password` | — | Redeem a reset token, set a new password, kill all sessions |
| GET / PATCH | `/me` | Bearer | Current user + **every** department/role; PATCH edits own name/avatar |
| GET | `/departments` | Bearer | List departments (org chart) |
| POST / DELETE | `/departments` · `/departments/{id}` | platform admin | Create / delete a department |
| GET / PATCH | `/departments/{id}` | member / admin | View / rename a department |
| PUT / DELETE | `/departments/{id}/head[/{user_id}]` | platform admin | Set / clear the department head |
| GET | `/departments/{id}/members` | member | Roster (paginated: `limit`,`offset`; filters: `role`,`team_id`,`q`) |
| PATCH / DELETE | `/departments/{id}/members/{user_id}` | admin | Change role/team · remove (with handover) |
| POST / GET / DELETE | `/departments/{id}/invites[/{invite_id}]` | admin | Create / list / revoke invites |
| POST / GET | `/departments/{id}/teams` | admin / member | Create / list teams |
| GET / PATCH / DELETE | `/departments/{id}/teams/{tid}` | member / admin | View / rename / delete a team |
| PUT / DELETE | `/departments/{id}/teams/{tid}/manager[/{user_id}]` | admin | Set / clear the team lead |
| GET | `/departments/{id}/teams/{tid}/members` | member | Team roster |
| PUT / DELETE | `/departments/{id}/teams/{tid}/members/{user_id}` | admin / team lead | Add / remove from team |
| GET | `/teams` | Bearer | Flat "all teams I can see" across departments |
| POST | `/platform/users/{id}/deactivate` · `/reactivate` | platform admin | Offboard / restore an account |
| GET / PUT / DELETE | `/platform/admins[/{id}]` | platform admin | List / grant / revoke platform admin |
| GET | `/invites/preview` | — | Public invite preview (who invited you, which dept) |
| POST | `/invites/accept` | — | Redeem an invite (token from the email) |

**Department actions name the `dept_id` in the path** (e.g. `PATCH
/departments/12`), and permission is checked against *that* department — so
someone who is admin in Engineering and an engineer in Data can only administer
Engineering. The token carries every membership; there is no "active department".

Interactive versions at `/docs`. In Swagger's **Authorize** box paste the raw
token only (starts `eyJ`) — it adds the `Bearer ` prefix itself, and pasting it
twice gives `401 Invalid token`.

## Two databases — which is which

| | Docker Postgres | Neon |
|---|---|---|
| Where | your laptop, via `docker compose up` | hosted, on the internet |
| Job | **everyday development** — wipe and rebuild freely | the copy that survives: deploys, demos, anything not on your laptop |
| Used when | always, right now | from Week 8 (deployment), or whenever something off your machine needs the data |
| Safe to destroy | yes, that's the point | no |

Under Docker Compose, `DATABASE_URL` is **overridden** to the local sandbox
Postgres — in Compose, `environment:` beats `env_file:`, so the Neon URL in
`services/identity/.env` is ignored while running in Docker. Deliberate: dev is
where you run half-finished migrations and create junk users, and none of that
should land in the database you later demo from.

**To run against Neon instead**, comment out the `DATABASE_URL:` line under
`identity:` in `docker-compose.yml` and `docker compose up -d --build identity`.
The `.env` (Neon) URL then applies.

## Seeing your data

Browser: **http://localhost:8080** (Adminer, starts with the stack).

| field | value |
|---|---|
| System | PostgreSQL |
| Server | `postgres` |
| Username / Password | `CC_POSTGRES_USER` / `CC_POSTGRES_PASSWORD` from your root `.env` |
| Database | `identity` |

Or from the terminal:

```bash
docker compose exec postgres psql -U admin -d identity -c "select id, email from users;"
```
