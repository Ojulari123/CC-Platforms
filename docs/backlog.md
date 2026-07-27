# Backlog — deferred work

Living list of things we've decided to build but haven't yet. Reasons are
recorded so future-us (or a new person) doesn't have to reverse-engineer why
something's still open. **Updated per session, not per commit.**

---

## Next up

- ~~**Pulse service**~~ — **scaffolded (session 04).** `services/pulse/` with
  reports, approvals and comments, its own `pulse` database, its own Alembic
  (`0001`), its own CI jobs (tests + Postgres migration/drift check), and auth via
  `packages/core` against identity's JWKS. Draft → submit → approve/reject/
  request-changes flow, append-only approval history, flat comments, and the
  Decision-6 permission model (team lead approves; `manager` role reads
  department-wide; admin covers an absent lead). ERD: [docs/erd.md](erd.md).
  **Still to come on Pulse:** GitHub sync (Week 3), AI summaries + PDF + email
  (Week 4), name-resolution via identity's API (Week 5).
- **Token now carries `leads`** — identity adds the team ids a user is the named
  lead of (`Team.manager_user_id`) to the access token, and `crescent_core`
  parses it (`claims.leads`, `claims.leads_team(id)`). This is what lets Pulse
  route approvals statelessly. Backward-compatible: absent `leads` → empty.
- ~~**Password reset (forgot password)**~~ — **shipped (session 04).**
  `POST /auth/forgot-password` (always 204, no account enumeration; 503 only on
  global email misconfig) + `POST /auth/reset-password` (single-use hashed
  token, `PASSWORD_RESET_EXPIRE_MINUTES` expiry, bumps `token_version` and
  revokes all refresh tokens). Table `password_reset_tokens` (migration 0007).

---

## Email-dependent flows (Brevo working as of session 03)

`app/services/email.py` has one `send(...)` function behind the Brevo
transactional API, so swapping provider later is a one-file change. Invite mail
is confirmed sending for real.

- ~~Admin-invite flow~~ — **shipped session 03.** `POST /departments/{id}/invites`
  + `POST /invites/accept`, `invites` table (migration 0002), 5/min rate limit
  on accept, public `GET /invites/preview`.
- **Email verification for self-registered users** — invited users get
  `email_verified=True` free (they opened a link sent to that address). Only the
  single bootstrap user is unverified, so this is now nearly moot.
- **The invite link has nowhere to land.** The email points at
  `{FRONTEND_URL}/invites/accept?token=…` = `localhost:3000`, and the Nuxt
  frontend is Week 5. The link is correct; its destination doesn't exist yet.
  Until then, accept by posting the token to the API directly. Optionally: a
  ~40-line throwaway HTML page served by identity so the loop is demoable at a
  Friday demo — **not built, say the word.**

---

## Open questions that are really design decisions

- **`role: "manager"` grants nothing on its own — resolved for Pulse (session 04).**
  Decision recorded in the decisions doc (Decision 6): in Pulse, the department
  `manager` role carries **department-wide read** of every team's reports, but
  **no approval power**. Approval stays with the report's named team lead
  (`Team.manager_user_id`). Inside identity the role is still eligibility-only;
  the read permission lives in Pulse, evaluated from the token claims.
- **Deputies / cover for absent leads — deferred, with a fallback (session 04).**
  No dedicated deputy for now. When a team lead is away, a **department admin**
  is the approval fallback. Revisit real deputies only if leads turn out to be
  away often (before the Week 4 approval flow if so).
- **`tv` (token_version) invalidation for downstream products** —
  **decision point when building Pulse/Forge, not a bug to fix now.**

  Identity checks `tv` in its own `get_current_user`, so `/me`,
  `/auth/change-password` etc. see an immediate kill on logout-everywhere or
  password change. Pulse and Forge verify tokens via `packages/core`, which is
  **stateless** and cannot check `tv` against identity's DB. Concrete
  consequence: after a password change or a revoke-all, a stolen access token
  keeps working on Pulse/Forge for **up to 15 minutes** (its remaining expiry).

  Almost certainly fine for internal tools — 15 min is a common blast radius —
  but it's a supervisor call once those products hold real data. If the answer
  is "GitHub activity and prompt experiments", 15 min is fine.

  If immediate cross-service revocation is ever needed:
  (a) identity exposes `/introspect` for products to call on hot paths
      (simple, ~5ms per request);
  (b) push revocations to Redis, products check a bloom filter
      (fast, more moving parts);
  (c) shorten access tokens to 5 min (no code, more refresh traffic).

  **Do nothing until Pulse/Forge exist and there's a concrete requirement.**

---

## Smaller, not urgent

- **Rate-limit storage is per-process.** `slowapi` keeps counters in memory, so
  limits reset on restart and wouldn't hold across replicas. Move to Redis
  storage when Redis arrives for Celery (Week 3).
- **Local Postgres reuses the Neon password.** `CC_POSTGRES_PASSWORD` in the
  root `.env` is the same string as the Neon connection password. Nothing leaks
  today (both are git-ignored) but they should be different secrets.
- **`GET /departments` is visible to every signed-in user.** Deliberate — an
  internal org chart isn't secret, and acting on a department still needs
  membership. Revisit if that ever feels wrong.

---

## Done in session 04 (review follow-ups)

- ~~**JWT issuer default was stale**~~ — `config.py` defaulted `JWT_ISSUER` to
  `crescent-identity` while everything else uses `cyphercrescent-identity`.
  Running without the env var set would have made every product reject valid
  tokens. Default now matches the canonical value.
- ~~**`accept_invite` could 500**~~ — a double-submit / race of the same invite
  token tripped `uq_membership_user_dept` as an unhandled `IntegrityError`. Now a
  clean 409, guarded both by a pre-check and a rollback-on-IntegrityError.
- ~~**Shared pagination helper**~~ — `crescent_core.pagination` (`Page[T]`,
  `PageParams`, `page_params`), ready for the Pulse reports/comments lists.
  Identity's members list gained filtering (`role`, `team_id`, `q`) on top of the
  pagination it already had.

## Done in previous sessions (kept for reference)

- ~~`GET /me`~~ — session 03. Now returns **every** membership, not one
  arbitrary "active" one (see decisions doc, Decision 1).
- ~~`PATCH /me`~~ — session 03. Own name/avatar only; role and department are an
  admin's call.
- ~~Password change~~ — session 03. `POST /auth/change-password` verifies
  current, validates new, bumps `tv`, revokes refresh tokens, issues a fresh
  pair so the caller stays logged in on that device.
- ~~`POST /auth/logout-all`~~ — session 03. `revoke_all_for_user` had existed
  since session 02 with no route, so "log out everywhere" was unreachable.
- ~~Identity's own `get_current_user`~~ — session 03, `app/security/dependencies.py`.
- ~~Rate limiting on auth endpoints~~ — session 03. `slowapi`, per-IP: 5/min
  register, 10/min login, 30/min refresh, 5/min change-password, 5/min invite
  accept, 20/min invite preview. Toggle: `RATE_LIMIT_ENABLED`.
- ~~Department switching~~ — **no longer needed.** Removed by the session-03
  restructure: every endpoint names its department and tokens carry all
  memberships, so there is no "active department" to switch.
- ~~Registration is still the founder flow~~ — closed in session 03.
  Registration is bootstrap-only; everyone else arrives by invite.
