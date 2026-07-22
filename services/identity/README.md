# Identity service

Single source of truth for accounts, orgs, teams, memberships, and tokens.
Every product (Pulse, ML platform) trusts tokens issued here.

## What lives here vs elsewhere
- **Here:** users, orgs, teams, memberships, passwords, refresh tokens, JWT signing.
  Owns "who a person is" — name, email, avatar.
- **Not here:** anything product-specific. Pulse owns its own copy of user info it
  needs (GitHub handle, etc.), keyed by `user_id`. Products never touch identity's DB.

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
