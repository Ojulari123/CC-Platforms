# Forge — No-Code AI / ML Learning Platform

Product 2. Guided environment for classification, regression, time-series, and
LLM workflows without writing code first.

**Weeks 5–7 in the internship plan.** Not started — begins after Pulse is
demo-ready.

## Boundaries (from CLAUDE.md)
Same rules as Pulse:
- Own database (`forge`). Never touches identity's or Pulse's DB.
- References people/teams by IDs from identity's tokens.
- Verifies tokens locally against identity's public key (via `/.well-known/jwks.json`).

## Stack
Same as Pulse. Frontend stays on Vue 3 + Nuxt to keep component reuse cheap.
