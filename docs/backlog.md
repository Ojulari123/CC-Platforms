# Backlog — deferred work

Living list of things we've decided to build but haven't yet. Reasons are
recorded so future-us (or a new person) doesn't have to reverse-engineer why
something's still open. **Updated per session, not per commit.**

---

## Blocked on: supervisor confirms email provider
Every item here sends email at some point. Nothing here can be built end-to-end
until the supervisor picks a provider (Brevo is our tentative default — see the
supervisor questions in `docs/sessions/2026-07-21-session-01.md`).

- **Email verification** — new users get a "click to verify" link. Until this
  ships, `email_verified` on the user always stays `false`.
- **Password reset (forgot password)** — public flow: enter email → get link →
  set new password. FindYourCribb has the same shape (6-digit code or magic
  link).
- **Admin-invite flow** — the second/third user joins an existing org via a
  link an admin sends them. Adds `POST /orgs/{id}/invites`,
  `POST /invites/{token}/accept`, backing invite table. This is what turns
  identity from a self-signup founder tool into a real internal-user system.

**When email is confirmed:** build a thin `app/services/email.py` (or reuse the
FindYourCribb `Utils/email.py` pattern) with one `send(...)` function, then
wire the three flows above onto it.

---

## Also open (larger, tackle later)

- **`GET /orgs/{id}/members`** and other org-admin endpoints once multi-user
  orgs exist (i.e. after admin-invite lands).
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
