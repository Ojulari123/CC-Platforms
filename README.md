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
| POST | `/auth/register` | — | Create user + new department (self-signup founder) |
| POST | `/auth/login` | — | Email + password → token pair |
| POST | `/auth/refresh` | — | Rotate refresh token, get new pair |
| POST | `/auth/logout` | — | Revoke a refresh token |
| POST | `/auth/change-password` | Bearer | Change password, kill all other sessions |
| GET | `/me` | Bearer | Current user + active department/role |
| GET | `/dept` | Bearer | The caller's department |
| POST | `/dept/teams` | admin | Create a team |
| GET | `/dept/teams` | Bearer | Teams in the caller's department |
| GET | `/dept/members` | Bearer | Members (paginated: `limit`, `offset`) |
| PATCH | `/dept/members/{user_id}` | admin | Change a member's role / team |
| POST | `/dept/invites` | admin | Email someone a one-time invite link |
| POST | `/invites/accept` | — | Redeem an invite (token from the email) |

**No endpoint takes a `dept_id`** — it comes from your token, so you can only
ever act on your own department.

Interactive versions at `/docs`. In Swagger's **Authorize** box paste the raw
token only (starts `eyJ`) — it adds the `Bearer ` prefix itself, and pasting it
twice gives `401 Invalid token`.

## Where's my data?

Under Docker Compose, `DATABASE_URL` is **overridden** to the local sandbox
Postgres container — `environment:` beats `env_file:`, so the Neon URL in
`services/identity/.env` is ignored while running in Docker. That's deliberate:
dev testing never touches Neon. To see what you just wrote:

```bash
docker compose exec postgres psql -U admin -d identity -c "select id, email from users;"
```
