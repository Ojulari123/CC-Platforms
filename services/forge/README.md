# Forge: No-Code AI / ML Learning Platform

Product 2. Guided environment for classification, regression, time-series, and
LLM workflows without writing code first.

**Weeks 5–7 in the internship plan.** Weeks 5 to 7 are up: the service boots on
port **8003**, owns its own `forge` database, verifies identity's JWTs locally,
serves a **datasets** API (upload / list / view / preview / delete), builds
**workflows** out of ordered steps, runs them on a **Celery worker**, keeps the
**run history**, and exports **readable Python** from the same step rows the
canvas shows.

Two modalities are built: **tabular** (classification, regression, time-series
forecast) and the **LLM playground**. Image classification is not built and is
recorded in `docs/backlog.md` with the reason.

Sits alongside the other product, **Pulse** (`services/pulse/`).

## Boundaries (from CLAUDE.md)
Same rules as Pulse:
- Owns its own database (`forge`). Never touches identity's or Pulse's DB.
- References people by identity `user_id` only (from the token), so a dataset's
  owner is a plain integer, not a copy of the user.
- Verifies tokens locally against identity's public keys via JWKS
  (`IDENTITY_JWKS_URL`, default `/.well-known/jwks.json`). The signing key never
  leaves identity.

## Endpoints

**Datasets**: every route needs a signed-in identity user.

| Method | Path | Who | Purpose |
|---|---|---|---|
| POST | `/datasets` | any signed-in user | Upload a CSV as a new dataset you own (multipart: `file`, optional `name`) |
| GET | `/datasets` | any signed-in user | List your own datasets **plus** the shared samples (paginated, newest first) |
| GET | `/datasets/summary` | any signed-in user | Dashboard counts in one call: `owned_count` (yours, samples excluded), `sample_count`, and the `recent` newest visible datasets (`?recent=`, default 5, 0–20) |
| GET | `/datasets/{id}` | owner or sample | One dataset's metadata |
| GET | `/datasets/{id}/preview` | owner or sample | First `rows` data rows (`?rows=`, default `DATASET_PREVIEW_ROWS`, 1–500) + column headers |
| DELETE | `/datasets/{id}` | owner only | Delete your dataset (204). Samples are owner-less, so nobody can delete them |

**Workflows**: every route needs a signed-in identity user, and every route is
scoped to what that user owns.

| Method | Path | Purpose |
|---|---|---|
| POST | `/workflows` | Create a workflow: `name`, `kind`, `dataset_id`, and the ordered `steps` |
| GET | `/workflows` | Your workflows, paginated, newest first |
| GET | `/workflows/steps` | The step vocabulary the canvas draws its palette from |
| GET | `/workflows/{id}` | One workflow with every step row |
| PUT | `/workflows/{id}/steps` | Replace the whole step list |
| DELETE | `/workflows/{id}` | Delete the workflow, its steps and its runs (204) |
| POST | `/workflows/{id}/runs` | Queue a run (202). Training happens on the worker, never in the request |
| GET | `/workflows/{id}/runs` | Run history, so nothing is lost when a tab closes |
| GET | `/workflows/{id}/runs/{run_id}` | One run: status, metrics, result, error, timing |
| GET | `/workflows/{id}/code` | The generated Python (`?fmt=script` or `?fmt=notebook`) |
| GET | `/workflows/{id}/code/raw` | The same script as a file download |

Workflow kinds: `tabular_classification`, `tabular_regression`,
`timeseries_forecast`, `llm_playground`.

Step kinds: `load_csv`, `handle_missing`, `encode_categorical`, `scale_features`,
`select_features`, `select_target`, `lag_features`, `train_test_split`,
`train_model`, `evaluate`, `prompt`. One row per step, `params` as JSON text.
The steps are stored in the order the learner built them and sorted into
pipeline order by `app/services/steps.py:ordered_steps`, which both the runner
and the code generator use, so what runs and what is exported cannot disagree.

Metrics: classification reports accuracy, macro precision, macro recall, macro
F1 and a confusion matrix. Regression reports R², MAE and RMSE. A forecast adds
MAPE.

A workflow that isn't yours is a **404**, not a 403. A step or parameter the
server will not accept is a **400** carrying a sentence naming the fix. A run
that fails stores a message a learner can act on, never a traceback.

**LLM playground**: `llm_playground` workflows send a system prompt, a question
and optional grounding text to OpenAI through `app/services/ai_provider.py` — a
small copy of the shape Pulse uses, not an import, because services do not
depend on each other's code. Every call is metered into Forge's own `llm_usage`
table and checked against `LLM_DAILY_TOKEN_CAP` **before** the call, so the cap
prevents overspending rather than reporting it. Over the cap is a **429**.

Access rules (in `app/services/datasets.py`): a caller sees their own datasets
plus every `is_sample` dataset and nothing else. A dataset that isn't yours and
isn't a sample is a **403**, a missing id is a **404**. Delete is **owner-only**;
since samples have no owner, a delete against one is a 403.

Upload validation rejects (400) anything that isn't UTF-8 text, is empty, or has
no header row (a header with zero data rows is allowed), and rejects (413) a body
over `MAX_UPLOAD_MB`: the body is read in 1 MB chunks and bailed the moment it
crosses the limit, so an oversized upload never fully buffers into memory.

## Rate limits
Per minute, per route: **10** upload, **60** list / summary / get, **30** preview,
**30** delete. Upload is tightest (buffers up to `MAX_UPLOAD_MB` and inserts every
row); delete sits below the reads because it writes, above upload because it only
drops a row.

Counters are keyed **per user**, not per address, because everyone behind one office NAT
or reverse proxy would otherwise share a bucket, so one heavy user could lock out
the rest. The bearer token is fully verified before its `user_id` becomes the key;
keying on an unverified claim would let anyone forge a header to mint fresh buckets
or drain someone else's. A missing or unverifiable token falls back to the client
address. Same implementation as identity (`app/rate_limit.py` in both).

The client address comes from the socket unless `TRUST_PROXY_HEADERS=true`, since
`X-Forwarded-For` is caller-supplied, so see the warning in `.env.example` before
turning it on.

`GET /health` returns `{"status": "ok", "db": "reachable"}`.
Interactive docs at `/docs`. Paste the raw identity access token (starts `eyJ`)
in Swagger's **Authorize** box.

## Storage & samples
The raw CSV **content lives in the database** (`datasets.content`, small learning
datasets), so there is no storage volume to manage. `columns` (JSON header list)
and `row_count` are cached from a parse at upload time, so listing never re-reads
the CSV. Two bundled **sample datasets** seed once on startup (idempotent, guarded
by the `uq_sample_name` partial unique index so two workers booting at once can't
double-seed), which keeps a new user's list from ever being empty.

## Config

| Var | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | — (required) | Forge's own `forge` Postgres |
| `IDENTITY_JWKS_URL` | `http://identity:8000/.well-known/jwks.json` | Where to fetch identity's public keys |
| `JWT_ISSUER` | `cyphercrescent-identity` | Expected token issuer |
| `JWKS_TTL_SECONDS` | `3600` | How long to cache the fetched JWKS |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed frontend origins |
| `RATE_LIMIT_ENABLED` | `true` | Set `false` to turn rate limiting off (tests do) |
| `REDIS_URL` | `redis://redis:6379/0` | Shared rate-limit counters; falls back to in-memory if unreachable |
| `TRUST_PROXY_HEADERS` | `false` | Read `X-Forwarded-For` for the client address. **Only** true behind a proxy you run; the header is caller-supplied |
| `TRUSTED_PROXY_COUNT` | `1` | How many of your proxies sit in front; the address is taken that far from the right of `X-Forwarded-For` |
| `DATASET_PREVIEW_ROWS` | `10` | Default rows returned by preview |
| `MAX_UPLOAD_MB` | `5` | Reject dataset uploads larger than this (413) |

## Run it

**Backend**, via docker-compose (recommended; builds from the repo root so the
image can pull in `packages/core`):

```bash
# From the repo root, with the sandbox Postgres up:
cp services/forge/.env.example services/forge/.env
docker compose up --build forge          # http://localhost:8003
```

Or standalone (needs a running identity for token verification):

```bash
pip install -e packages/core
pip install -r services/forge/requirements.txt
cd services/forge && alembic upgrade head && uvicorn app.main:app --reload --port 8003
```

**Frontend**: Nuxt 3 dev server on port 3000:

```bash
cd services/forge/frontend && npm install && npm run dev   # http://localhost:3000
```

See [`frontend/README.md`](frontend/README.md) for the frontend (login, token
handling, route guard, datasets page).

## Tests

```bash
pip install -e packages/core
pip install -r services/forge/requirements-dev.txt
cd services/forge && pytest
```

SQLite-based; the auth dependency is overridden so tests inject token claims
directly. No DB server or identity instance needed. The code-generation tests
write a generated script to a temporary directory and **run it in a subprocess**
against a real CSV, so an export that stops working fails the suite.

## Stack
FastAPI + PostgreSQL + SQLAlchemy + Alembic. Training runs on Celery over Redis
(`forge-worker` in `docker-compose.yml`), the same pattern Pulse uses. Models are
scikit-learn; frames are pandas. Frontend: Nuxt 3 + TypeScript +
Tailwind + TanStack Query, to keep component reuse with Pulse cheap.
