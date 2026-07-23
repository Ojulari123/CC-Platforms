# Backlog — deferred work

Living list of things we've decided to build but haven't yet. Reasons are
recorded so future-us (or a new person) doesn't have to reverse-engineer why
something's still open. **Updated per session, not per commit.**

---

## Email-dependent flows (Brevo confirmed session 03 — no longer blocked)
`app/services/email.py` now exists with one `send(...)` function (Brevo
transactional API). Provider choice still worth confirming with supervisor,
but building proceeds in parallel.

- **Email verification for self-registered users** — register still sets
  `email_verified=False`; invited users get `True` automatically (they proved
  the address by opening the link). A verify flow only matters for the
  self-signup founder path.
- **Password reset (forgot password)** — public flow: enter email → get link →
  set new password. FindYourCribb has the same shape (6-digit code or magic
  link). Next email flow to build.
- ~~Admin-invite flow~~ — **shipped session 03.** `POST /dept/invites` +
  `POST /invites/accept`, `invites` table (migration 0002), 5/min rate limit
  on accept. New users land in the inviting department with the invited role.

---

## Also open (larger, tackle later)

- **Department switching** — a user can belong to several departments (their own
  from register, plus any they're invited to). Login picks their first active
  membership arbitrarily; accepting an invite issues tokens scoped to the
  inviting department. Fine while nearly everyone is in one department, but a
  real `POST /auth/switch-dept` is needed before anyone genuinely sits in two.
- **Registration is still the founder flow** — `POST /auth/register` creates a
  *new* department every time. Now that invites exist, self-registration should
  probably be closed off (or restricted to a @cyphercrescent.com domain) so the
  only way in is an invite. **Supervisor call.**
- **`tv` (token_version) invalidation for downstream products** —
  **decision point when building Pulse/Forge, not a bug to fix now.**

  How it works today: identity checks `tv` in its own `get_current_user`, so
  `/me`, `/auth/change-password`, etc. see an immediate kill on
  logout-everywhere or password change. But Pulse and Forge verify tokens via
  `packages/core`, which is **stateless** and cannot check `tv` against
  identity's DB. Concrete consequence: after a user changes their password (or
  identity revokes all their sessions), a stolen access token on Pulse/Forge
  keeps working for **up to 15 minutes** (its remaining expiry).

  Is this OK? Almost certainly yes for internal CypherCrescent tools —
  15 min is a common industry blast-radius. **But it's a supervisor-level
  call once Pulse/Forge are handling real data.** Ask what data those products
  will touch, and if the answer is "GitHub reports, prompt experiments" then
  15 min is fine. If it becomes "financial data" or similar, we tighten.

  When/if we ever need immediate cross-service revocation, options:
  (a) identity exposes a `/introspect` endpoint products call on hot paths
      (simple, adds ~5ms per request);
  (b) push revocations to Redis and have products check a bloom filter
      (fast, more moving parts);
  (c) shorten access tokens further — 5 min instead of 15
      (no code, but more refresh traffic).

  **Do nothing until Pulse/Forge exist and there's a concrete requirement.**

---

## Done in previous sessions (kept for reference)

- ~~`GET /me`~~ — shipped session 03 (2026-07-22). Returns identity fields + active org/role.
- ~~Password change (user knows current password)~~ — shipped session 03.
  `POST /auth/change-password`: verifies current, validates new, bumps `tv`,
  revokes all refresh tokens, issues fresh pair so caller stays logged in.
- ~~Identity's own `get_current_user`~~ — shipped session 03 in
  `app/security/dependencies.py`. Decodes JWT + loads user + checks
  `is_active` + checks `tv`.
- ~~Rate limiting on auth endpoints~~ — shipped session 03. `slowapi`, per-IP:
  5/min register, 10/min login, 30/min refresh, 5/min change-password.
  In-memory store (per-process); move to Redis storage when Redis lands for
  Celery. Toggle: `RATE_LIMIT_ENABLED` (tests turn it off globally).
