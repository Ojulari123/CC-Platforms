# Pulse — Engineering Performance & Reporting

Product 1. Pulls GitHub activity into weekly reports, adds AI-written summaries,
routes them through a manager approval flow.

**Weeks 2–4 in the internship plan.** Not started yet.

Sits alongside the other product, **Forge** (`services/forge/`).

## Boundaries (from CLAUDE.md)
- Owns its own database. Never reads identity's DB directly.
- References people/teams by `user_id` / `team_id` / `org_id` from identity's tokens.
- Verifies tokens locally using identity's public key (fetched from
  `http://identity:8000/.well-known/jwks.json` in Docker, once identity publishes it).
- Owns its own view of a user (e.g. `github_handle`) keyed by `user_id`. Never
  stores name/email/avatar — those live in identity.

## Stack
FastAPI + PostgreSQL + SQLAlchemy + Alembic + Redis + Celery (for GitHub sync jobs).
Frontend: Vue 3 + Nuxt + TypeScript + Tailwind + TanStack Query + Zod.
