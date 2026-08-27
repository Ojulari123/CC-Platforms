# Backlog: deferred work

Living list of things we've decided to build but haven't yet. Reasons are
recorded so future-us (or a new person) doesn't have to reverse-engineer why
something's still open. **Updated per session, not per commit.**

---

## Next up

- **Forge: image classification is not built.** Week 6 named four modalities; Forge
  shipped two of them, tabular (classification, regression, forecast) and the LLM
  playground. Image classification was left out on cost: it needs torch or
  tensorflow, which is roughly 2 GB added to a service image whose entire ML stack
  is currently scikit-learn, pandas and numpy at about 90 MB, and the Week 6 bar was
  tabular plus one other modality. The step vocabulary
  (`services/forge/app/services/steps.py`) is a flat kind + JSON params table, so
  adding `load_images`, `resize`, `augment` and a `train_model` algorithm for a small
  CNN is additive: no migration, and the code generator picks up a new block per new
  kind. Decide first whether the images live in Postgres like the CSVs do, which will
  not scale, or in object storage, which Forge has none of yet.

- ~~**Department admins are never emailed when a repo has no lead or deputy.**~~
  **DELIVERED.** `email._approver_emails` is now `reports._can_approve` read back out:
  lead and deputy, else every active admin of the report's department, else the platform
  admins. Identity grew `GET /internal/departments/{dept_id}/admins` and
  `GET /internal/platform-admins` on a new `admins:read` scope, added to `PULSE_SCOPES`
  and granted by the boot re-seed (`seed_service_client` rewrites scopes every start), so
  no migration. Nobody is mailed about their own report. Original entry:
  `notify_report_ready`
  (`services/pulse/app/services/email.py:92`) emails only the repo's named lead and
  deputy. A repo with a department but neither named takes the `else` branch, logs
  "no approvers to notify" (`email.py:99`) and mails **nobody**, even though
  `_can_approve` (`app/services/reports.py:49`) and the list scope (`reports.py:172`)
  both put that report in every dept admin's review queue. It can sit unreviewed
  indefinitely with no one prompted. Closing it means Pulse asking identity who
  administers a department. Identity does have
  `GET /departments/{dept_id}/members?role=admin`
  (`app/routes/departments.py:43`), but it's gated by `require_dept_role()`, which needs a
  **user** token with membership in that department that a service can't present,
  and Pulse's service client holds only
  `users:read:email users:read:profile tokens:verify`
  (`identity/app/services/service_clients.py:13`). So it needs a new scope, a new
  scope-gated endpoint alongside the three in `app/routes/internal.py`, the Pulse-side
  client call, and the notification branch that uses it.
- **Forge, Week 6: visual ML workflows.** Build on the Week-5 dataset backend
  + frontend foundation. No-code workflow builder (pick a dataset → configure a
  classification/regression/time-series/LLM step → run). Not started.
- **Pre-deploy hardening.** Before Forge/Pulse go anywhere real:
  - lock `SIGNUP_ALLOWED_DOMAINS` to the org (it's empty = allow-all today);
  - add **email verification** for self-signed-up users (signup sets
    `email_verified=False` and nothing lifts it yet, since only invited users get
    verified free);
  - set up a real **GitHub OAuth App** so Pulse's live sync works outside the dev
    allowlist;
  - move tokens out of `localStorage` into **httpOnly cookies**, a **blocker,
    not a nice-to-have**. Both frontends (Pulse and Forge) keep the access
    + refresh pair in `localStorage`, where any injected script on the page can
    read it. All token handling already lives in one shared module
    (`packages/ui/composables/useTokenStorage.ts`, which both frontends
    `extends`), so the swap is a one-file change. Deliberately deferred because the correct cookie config depends on
    deployment topology: same-origin behind one domain → `SameSite=Lax` and it
    just works; a separate hostname per service → `SameSite=None; Secure`, HTTPS
    everywhere, CORS with credentials, and some corporate browser configs block
    it. Topology undecided as of 2026-08-08.
- ~~**Identity publishes a single signing key with no overlap window, pre-deploy.**~~
  **RESOLVED.** Rotation is now phased, not a cutover. `keys.py` publishes the active
  key plus every `.pem` in `JWT_RETIRED_PUBLIC_KEYS_DIR` at `/.well-known/jwks.json`
  (`get_public_jwks`), so tokens signed by either key verify during the overlap; retired
  keys verify but never sign. `get_verification_key_pem(kid)` lets identity accept its own
  pre-rotation tokens. `validate_retired_public_keys()` runs at startup (`app/main.py:20`)
  and **refuses the boot** on an unusable retired `.pem` rather than 500ing JWKS later.
  Runbook: `docs/runbook-identity-key-rotation.md`; helper `scripts/rotate-identity-keys.sh`.
- **Live Forge browser walkthrough.** Boot identity + forge + the Nuxt frontend
  and drive login → dataset upload → preview → delete end to end in a browser (the
  backend + UI are built; a full click-through hasn't been recorded).
- **Repo visibility should follow current GitHub access, not commit history.**
  **PARTLY CLOSED — the unbounded grant is gone, the GitHub check is not built.**
  `repo_ids_worked_in_q` now takes a `since`, and `_can_see_repo` /
  `visible_repo_scope` / `may_write_on_repo` / `_has_activity` / `visible_repo_ids` all
  pass `activity.visibility_activity_cutoff()` (`REPO_VISIBILITY_ACTIVITY_DAYS`, default
  90), so authorship stops granting read *or write* once it is stale instead of never. The chatbot follows the same rule: `repo_index._queue`
  refuses a tracked private repo the requester can't see, and
  `chat._searchable_indexes` drops its stored chunks from retrieval even when the index
  was built while they could. What is still open is the accurate answer: asking GitHub who
  currently has access. Sync still never pulls the collaborator list, storing it needs a
  table, and `GITHUB_OAUTH_SCOPES` couldn't read a private one anyway (below). Until
  then two holes stay open — someone who keeps their department but is dropped from a
  GitHub repo keeps the department grant, and the activity grant lives out its window.
  - **`GITHUB_OAUTH_SCOPES` defaults to `read:user`**, which grants no repository
    content access, so private-repo sync can't work as configured and would return
    empty results rather than an error (public repos work today, which is why this
    hasn't surfaced). ~~`services/pulse/.env.example` doesn't mention needing `repo`.~~
    The example file now documents adding `repo`; the default is still `read:user`.
    Ships with the collaborator sync above; both need the wider scope.

- **Sync only follows a repo's default branch.** `GitHubClient.list_commits`
  (`services/pulse/app/services/github_client.py:116`) passes no `sha`, and GitHub's
  `/repos/{repo}/commits` defaults to the default branch. Work that lives on a feature
  branch and is squash-merged appears; work on a long-lived branch that never merges
  never shows up in anyone's activity or report.
- ~~**The sync cursor filters by commit date, not push date.**~~ **DELIVERED.** The
  cursor still goes to GitHub's `since`, which filters on the commit's own timestamp, but
  `_commit_window` (`services/pulse/app/services/sync.py:260`) now subtracts an overlap
  before asking, so a commit dated behind the cursor and pushed after it is re-requested
  rather than lost. Re-asking is cheap because rows upsert by `(repo, sha)`. A commit
  older than the overlap window is still missed, so a push-event source remains the only
  complete answer.
- **A repo with no department and no lead/deputy has no approver.** Sync creates
  repositories with `dept_id`/`lead_user_id`/`deputy_user_id` left null
  (`sync.py:_upsert_repository`), and `_can_approve` (`app/services/reports.py:49`)
  only admits the lead, the deputy, a dept admin of the repo's department, or a platform
  admin, so until an admin files the repo, only a platform admin can approve. **Now closed
  on the "somebody can act" side:** those platform admins are emailed on submit
  (`email._approver_emails` → `resolve_platform_admin_emails`), and the author's warning
  (`email._notify_author_of_unfiled_repo`) says so rather than sending them to find one.
  Submission is still allowed rather than refused, because refusing strands finished work
  behind an admin task the author can't perform. Filing the repo is still a manual step
  nothing schedules or chases; `GET /github/repositories/unfiled` is the only prompt.
- ~~**Week 5: real approver email (service-to-service auth)**~~:
  **DELIVERED.** Route B is real, not stubbed: on submit, Pulse resolves the repo's
  approvers (lead + deputy) `user_id → email` by authenticating as the **`pulse`
  service** via OAuth2 client-credentials against identity's `POST /oauth/token`
  (short-lived scoped service token, cached in-process, re-minted on a 401), then
  hitting `POST /internal/users/emails` and sending via Brevo. Best-effort and fired
  after the submit commit, so a notification failure can never block/roll back a
  submission. Identity side: `service_clients` table (migration `0008`), the `pulse`
  client seeded on startup from `PULSE_CLIENT_SECRET` with scope `users:read:email`,
  and scope-gated `/internal/users/emails`. Shared secret must match on both sides
  (`PULSE_CLIENT_SECRET` in identity == `PULSE_SERVICE_CLIENT_SECRET` in Pulse).
- ~~**Self-signup + admin placement**~~: **DELIVERED.** `POST /auth/signup` opens
  an open, domain-gated (`SIGNUP_ALLOWED_DOMAINS`, empty=allow-all) door that creates
  an **unplaced non-admin** account; `POST /auth/register` stays bootstrap-only and now
  closes once a platform admin exists. `POST /departments/{dept_id}/members` lets a
  dept/platform admin place an existing user (e.g. a fresh signup) into a department.
- ~~**App-wide user directory**~~: **DELIVERED.** `GET /platform/users`
  (platform admin only; filters `q`, `is_active`, pagination): every account across
  every department, distinct from a department-scoped roster.
- ~~**Forge, Week 5: skeleton → dataset backend + frontend foundation**~~:
  **DELIVERED.** Forge boots on port **8003**, owns its own `forge` DB, verifies
  identity JWTs locally via JWKS. Datasets API: `POST /datasets` (multipart CSV
  upload, capped at `MAX_UPLOAD_MB`, streamed so an oversized body never fully
  buffers), `GET /datasets` (own + shared samples, paginated), `GET /datasets/{id}`,
  `GET /datasets/{id}/preview`, `DELETE /datasets/{id}` (owner-only; samples
  un-deletable). CSV content stored in the DB; 2 sample datasets seed idempotently on
  startup (partial unique index `uq_sample_name`). Migrations `0001`–`0002`. Nuxt 3 +
  TS + Tailwind + TanStack Query frontend foundation: login, token handling, route
  guard, protected datasets page.

- ~~**Week 4: AI generation, PDF, email trigger, usage ledger**~~:
  **DELIVERED (session 06).** `POST /reports/generate` drafts a report's three
  summaries (`summary_manager`/`summary_exec`/`next_week_goals`) from the engineer's
  real synced GitHub activity for the week, with typed failure modes (empty week →
  422 and no LLM call; existing non-editable report → 409; LLM error after one retry
  → 502). `GET /reports/{id}/pdf` exports via reportlab (same read permission as
  viewing). Token usage rolls up into a new `llm_usage` ledger read by
  `GET /admin/llm-usage` (platform admin only at the time; now scoped by who pays,
  see the entry below), deliberately **not** per-report, so
  viewers never see model/tokens. Migration `0004` (`reports.generated_at` +
  `llm_usage` table). Email-on-submit fires but is **stubbed** (logs which approver
  user_ids would be notified). Provider locked to **OpenAI** (`gpt-4o-mini` default).
  Verified: real OpenAI smoke test (three distinct summaries, ~680 tokens); 143 pulse
  tests green; migration round-trip + no drift on real Postgres.
  - ~~**Week 5: real email send.**~~ **DELIVERED** (see the Week-5 approver-email
    entry above); `notify_report_ready` now resolves emails via identity's
    service-to-service auth and sends through Brevo.
  - ~~**Week 5: frontend report link.**~~ **DELIVERED.** The notification's
    `{FRONTEND_URL}/reports/{id}` link (`services/pulse/app/services/email.py`) now
    lands on `services/pulse/frontend/pages/reports/[id].vue`. Identity's invite link
    is still the one with nowhere to go (see the email-flows section below).
- **Repo-centric restructure (session 05): reporting moves off teams onto
  repos. CONFIRMED, ready to build; do this before finishing slice 4.** A report
  is tied to the **repo** an engineer worked in, not their team; each repo has a
  **lead + deputy** and **both** approve; one report per (engineer, repo, week);
  membership derived from activity; repos belong to a department (dept admin sees
  the dept's repos); dept-or-platform admin assigns lead/deputy; a repo with no
  lead/deputy doesn't block reports. **Pulse owns** repo→lead/deputy/dept/members
  (identity stays lean); identity's team model is left **parked, not deleted**
  (a "how to delete teams" runbook is in the decision doc). Full detail:
  `docs/decisions/2026-07-30-repo-centric-reporting.md`. Questions resolved:
  `docs/questions.md`. Supersedes Decision 6.
  - ~~**Schema work**~~: **BUILT (session 05, migration `0003`).** Pulse
    `repositories` += `dept_id`/`lead_user_id`/`deputy_user_id`; `reports` +=
    `repo_id`, dropped `team_id`, uniqueness → `(author_user_id, repo_id,
    week_start)`. Repo-admin endpoints (`/github/repositories/...` assign dept/
    lead/deputy) + reworked report create/approve/read. 80 pulse tests green,
    no drift.
  - ~~**Slice 4: GitHub activity pull**~~: **BUILT (session 05).** A
    `GitHubClient` (pagination + rate-limit wait/retry) and a rewritten
    `run_full_sync` that, per allowlisted repo, upserts commits/PRs/reviews/issues
    incrementally (since `last_synced_at`), attributes them to identity users by
    matching GitHub login, and writes a `sync_runs` row each. `POST /github/sync`
    triggers it on demand (admin-only); the daily beat still fires it. 85 pulse
    tests green.
  - ~~**Slice 5: engineer activity view**~~: **BUILT (session 05).**
    `GET /activity/me` and `GET /activity/{user_id}` (own → always; others →
    admins + repo leads/deputies), with `since` / `repo_id` filters: counts +
    recent commits/PRs/reviews/issues. 95 pulse tests green.
  - **Week 3 "done when": MET.** Live GitHub data syncs (verified: 27 real
    commits from `Ojulari123/CypherCrescent`), on a daily schedule (beat), and
    surfaces per engineer via `/activity`.
  - ~~**End-of-Week-3 review fixes**~~: **done (session 05).** Stale comments +
    Pulse README rewritten to the repo-centric model with all Week-3 endpoints;
    secondary rate-limit handling + incremental PR sync + multi-account token
    fallback in the sync engine; `create_report` now enforces membership-from-
    activity; per-IP rate limiting on `/github/*` (slowapi); `POST /github/sync`
    enqueues to Celery by default (`?wait=true` for inline); CI import-check now
    boots the Celery side. 102 pulse tests green.
  - **Still open (not blocking Week 4):** drop the unused `leads` token claim;
    optional repo→dept auto-map on sync; GitHub webhooks (deferred).
- ~~**`docs/erd.md` refresh**~~: **done (session 05).** Now reflects identity
  `0001`–`0007` (incl. `password_reset_tokens`) and Pulse `0001`–`0003`: both the
  GitHub sync domain and the repo-centric reporting domain, with teams marked
  parked.
- ~~**Pulse service**~~: **scaffolded (session 04).** `services/pulse/` with
  reports, approvals and comments, its own `pulse` database, its own Alembic
  (`0001`), its own CI jobs (tests + Postgres migration/drift check), and auth via
  `packages/core` against identity's JWKS. Draft → submit → approve/reject/
  request-changes flow, append-only approval history, flat comments, and the
  Decision-6 permission model (team lead approves; `manager` role reads
  department-wide; admin covers an absent lead). ERD: [docs/erd.md](erd.md).
  ~~**Still to come on Pulse:** GitHub sync (Week 3), AI summaries + PDF + email
  (Week 4), name-resolution via identity's API (Week 5).~~ All three **DELIVERED**;
  name resolution is `app/services/people.py` (`attach_names`, one batched
  `/internal/users/profiles` call per response) plus `app/services/pdf.py`.
- **Token now carries `leads`**: identity adds the team ids a user is the named
  lead of (`Team.manager_user_id`) to the access token, and `crescent_core`
  parses it (`claims.leads`, `claims.leads_team(id)`). This is what lets Pulse
  route approvals statelessly. Backward-compatible: absent `leads` → empty.
- ~~**Password reset (forgot password)**~~: **shipped (session 04).**
  `POST /auth/forgot-password` (always 204, no account enumeration; 503 only on
  global email misconfig) + `POST /auth/reset-password` (single-use hashed
  token, `PASSWORD_RESET_EXPIRE_MINUTES` expiry, bumps `token_version` and
  revokes all refresh tokens). Table `password_reset_tokens` (migration 0007).
- **GitHub webhooks: deferred (Week 3 decision).** Week 3 pulls GitHub activity
  on a **scheduled daily sync** (Pulse asks GitHub on a timer). Webhooks (GitHub
  *pushing* us push/PR events the instant they happen, for near-real-time data)
  are deferred: they need a public dev URL (smee.io / ngrok) and the daily sync
  already meets the "syncs on a schedule" bar. Add later if near-real-time
  matters: a signature-verified `POST /github/webhook` receiver.

---

## Email-dependent flows (Brevo working as of session 03)

`app/services/email.py` has one `send(...)` function behind the Brevo
transactional API, so swapping provider later is a one-file change. Invite mail
is confirmed sending for real.

- ~~Admin-invite flow~~: **shipped session 03.** `POST /departments/{id}/invites`
  + `POST /invites/accept`, `invites` table (migration 0002), 5/min rate limit
  on accept, public `GET /invites/preview`.
- **Email verification for self-registered users**: invited users get
  `email_verified=True` free (they opened a link sent to that address). ~~Only the
  single bootstrap user is unverified, so this is now nearly moot.~~ No longer true
  now that `POST /auth/signup` exists: it sets `email_verified=False`
  (`app/services/auth.py:125`) and nothing lifts it. Also load-bearing elsewhere:
  `platform_service.delete_user` refuses a hard delete once a user is verified or has
  an `onboarded_at`, so "never onboarded" is partly defined by this flag. Listed under
  pre-deploy hardening above.
- ~~**The invite link has nowhere to land.**~~: **RESOLVED.** Both destinations now
  exist as shared pages in `packages/ui/pages`: `invites/accept.vue`,
  `forgot-password.vue` and `reset-password.vue`. Pulse's and Forge's Nuxt configs both
  `extends: ["../../../packages/ui"]`, so each frontend serves them.
- **Identity has exactly one `FRONTEND_URL`.** `services/identity/app/config.py:25`
  feeds both the invite link and the reset link (`app/services/email.py:51,72`), so every
  emailed link points at whichever product that variable names, so an invitee meant for
  Pulse lands in Forge, or vice versa. Gets worse with a third product. Wants a per-invite
  target product, or a small identity-hosted landing page that routes onward.
- **Test accounts on `@cyphercrescent.com` hard-bounce and get blocklisted at Brevo.**
  The real domain is `.org`. Brevo returns success for a send to a blocklisted address,
  so later mail to that address is silently suppressed with no error anywhere in our logs,
  a debugging trap. The repo's own examples still say `.com`
  (`services/identity/.env.example:65`, `services/identity/README.md:19`,
  `app/main.py:33`). Use real `.org` addresses when testing, and clear the Brevo
  blocklist if a test address stops receiving.

---

## Open questions that are really design decisions

- **`role: "manager"` grants nothing on its own, resolved for Pulse (session 04).**
  Decision recorded in the decisions doc (Decision 6): in Pulse, the department
  `manager` role carries **department-wide read** of every team's reports, but
  **no approval power**. Approval stays with the report's named team lead
  (`Team.manager_user_id`). Inside identity the role is still eligibility-only;
  the read permission lives in Pulse, evaluated from the token claims.
- **Deputies / cover for absent leads: deferred, with a fallback (session 04).**
  No dedicated deputy for now. When a team lead is away, a **department admin**
  is the approval fallback. Revisit real deputies only if leads turn out to be
  away often (before the Week 4 approval flow if so).
- ~~**`tv` (token_version) invalidation for downstream products**~~:
  **RESOLVED, option (a) softened.** `crescent_core.RevocationChecker`
  (`packages/core/crescent_core/revocation.py`) asks identity's
  `POST /internal/users/token-versions` and caches the answer per user for
  `TOKEN_VERSION_TTL_SECONDS` (default 60), so it is not a call per request. Both
  products wire it into the single `current_user` dependency every authenticated route
  uses (`services/pulse/app/auth.py`, `services/forge/app/auth.py`), so it can't be
  opted out of. A `STALE` or `UNKNOWN` verdict → 401; `UNAVAILABLE` is **accepted on
  purpose** (`crescent_core/deps.py:31-40`) with rate-limited warning logs, so an
  identity blip is not a platform-wide outage. Window drops from ~15 min to ~1 min.
  The original analysis, kept because it explains the trade-off:

  Identity checks `tv` in its own `get_current_user`, so `/me`,
  `/auth/change-password` etc. see an immediate kill on logout-everywhere or
  password change. Pulse and Forge verify tokens via `packages/core`, which is
  **stateless** and cannot check `tv` against identity's DB. Concrete
  consequence: after a password change or a revoke-all, a stolen access token
  keeps working on Pulse/Forge for **up to 15 minutes** (its remaining expiry).

  Almost certainly fine for internal tools (15 min is a common blast radius),
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

- **Rate limiting: per-process storage** (the keying half is done). *Storage:*
  `slowapi` keeps counters in memory, so limits reset on restart and wouldn't hold
  across replicas. Forge now uses Redis storage with an in-memory fallback
  (`services/forge/app/rate_limit.py`); **identity and Pulse still don't**, since both
  build `Limiter(...)` with no `storage_uri`, so this half stays open for them.
  *Key:* ~~all three limiters use `get_remote_address`~~: **DELIVERED.** Each
  service's `rate_limit.py` now has `user_or_address_key`, which reads the
  `Authorization` header, **verifies the access token in full** (not just decodes it,
  or anyone could forge a key) and counts per `user:<id>`; anything absent, expired
  or unverifiable falls back to the address, never a shared key. Every authenticated
  limited route uses it: identity's `/auth/change-password`, Pulse's
  `/github/connect` · `/github/sync` · `POST /reports` · `POST /reports/generate`,
  and all of Forge's (its limiter's default `key_func`). Still address-keyed on
  purpose, namely routes with no caller to attribute a request to: identity's
  register/signup/login/refresh/forgot-password/reset-password, invite preview +
  accept and `/oauth/token`, and Pulse's GitHub OAuth callback (a browser redirect
  carrying no token). Forwarded-for headers are **not** trusted by default in any of the
  three (`TRUST_PROXY_HEADERS: bool = False` in each `config.py`), so a client can't spoof
  its way into someone else's bucket; turn it on only behind a proxy you control.
- **Rate-limit tests run on a frozen clock.** The `_deterministic_limiter` autouse
  fixture in each service's `tests/test_rate_limit.py` patches the clock inside the
  limiter's in-memory storage, which is what makes those tests immune to machine load
  It also means a limit window never expires on its own. A future test that wants
  to watch one lapse has to advance the `_FrozenClock`; waiting will never work. Noted
  in Forge's fixture; the same line still needs applying to identity's and Pulse's.
- ~~**`GITHUB_ORG` is declared in Pulse's config and referenced nowhere.**~~
  **RESOLVED.** The declaration is gone from `services/pulse/app/config.py`; the
  only mentions left in the repo are this line and the session-05 log. Repo
  discovery is still the `GITHUB_REPOS` allowlist only; org-wide discovery doesn't
  exist, and nothing claims it does.
- ~~**Pulse's test suite reads the real `GITHUB_REPOS` from `.env`.**~~
  **RESOLVED.** `services/pulse/tests/conftest.py` now pins **every** setting
  `app/config.py` declares (assigned, not `setdefault`), `GITHUB_REPOS=""` included, and
  additionally blocks outbound HTTP by replacing `httpx.HTTPTransport.handle_request` /
  `AsyncHTTPTransport.handle_async_request`, recording attempts in `BLOCKED_REQUESTS` so
  the error-swallowing notify path can still be asserted on.
- **New Pulse visibility queries are unverified against Postgres.** The
  repo-visibility filter is an `IN (SELECT … UNION …)`; every test runs on SQLite
  in-memory, and CI's `pulse-migrations` job touches Postgres but never exercises
  these queries.
- **`services/pulse/celerybeat-schedule`, `-shm` and `-wal` are tracked binary
  runtime files.** They produce binary noise in every diff. ~~Gitignore them~~:
  `.gitignore:13` now has `celerybeat-schedule*`, but ignoring does nothing to a file
  already tracked: `git ls-files services/pulse` still lists all three. Still needs
  `git rm --cached services/pulse/celerybeat-schedule*` in a commit of its own.
- **Pulse duplicates the shared service-token client: deliberate deferral.**
  `services/pulse/app/services/identity_client.py` carries its own
  client-credentials/cache/retry machinery (`_fetch_service_token`, `_get_service_token`,
  `_post`) alongside `crescent_core.ServiceTokenClient`, which `app/auth.py` already
  instantiates for the revocation check, so a Pulse process mints and holds **two**
  service tokens. Not consolidated because the module's profile/leaver behaviour
  (`ProfileAnswer`, chunk-tolerant lookups, `resolve_profiles_safe`) is covered by ~37
  tests that would all need rewriting. Worth doing when that path is next touched.
- **Three new columns have no backfill and fill in only as the sync re-lists a row.**
  `pull_requests.closed_at` (migration `0016_pull_request_closed_at.py`) and
  `issues.assignee_user_id` / `assignee_github_login` / `milestone_title` /
  `milestone_due_on` (migration `0017_issue_assignee_milestone.py`) are populated in the
  sync (`services/pulse/app/services/sync.py:218,243-251`) but GitHub only re-lists an
  item it considers updated. A pull request closed long ago, or an issue nobody touches
  again, keeps a null forever. Closing it means one full re-list per repository, with
  `since` dropped, which is a rate-limit cost nobody has costed yet.
- **`commits.committed_at` rows written before the committer-date fix cannot be told
  apart.** The sync has stored the committer date since `0515da9`; anything synced before
  that holds the author date, and nothing in the database distinguishes the two. Only a
  re-sync corrects them, and the same full re-list applies.
- **Only the first assignee of an issue is stored.** GitHub sends `assignees` as a list;
  `_sync_issues` keeps `assignee`, the first of them
  (`services/pulse/app/services/sync.py:243`). An issue shared between three people reads
  as one person's queued work in next week's goals. Deliberate for now: a report describes
  one person's plan, and three assignees are not three intentions.
- **Next week's goals read journal entries from the report's own week only.**
  `_stated_intent` scopes them to the same window as the activity
  (`services/pulse/app/services/generation.py:71`), chosen so a report reads the same way
  whenever it is regenerated. Somebody who writes their plan on the Monday after has it
  missed. A trailing window would catch it and would make an old report's goals change
  under it; neither is obviously right.
- **An assigned open issue appears in every week's goals until it closes.** Not
  date-bounded, on purpose, because queued work stays queued
  (`services/pulse/app/services/generation.py:86`). The effect is the same issue repeated
  across consecutive reports with nothing marking it as already mentioned.
- ~~**A week with journal entries but no GitHub activity still refuses to generate.**~~
  **CLOSED.** Generation now proceeds on journal entries alone
  (`generation._journal_items`), and the report says so: `JOURNAL_ONLY_NOTE` is prepended
  to `summary_manager` by Pulse rather than left to the model, and the payload carries
  `no_github_activity` so the prompt stops describing commits that are not there. A week
  with nothing at all is still refused, and an assigned open issue on its own does not
  count — those are not week-scoped, so one assigned in March would let every silent week
  since generate a report about nothing anybody said.
- ~~**The token usage ledger showed one figure to one person.**~~ **CLOSED.**
  `GET /admin/llm-usage` was platform-admin only, which was backwards on both sides: the
  one person spending nobody's money but the platform's saw every figure, and the people
  funding calls with their own or their department's key saw none of theirs. It now
  follows `llm_budget.may_see_figures` like the budget messages do — platform key gets
  403, own key sees own spend, an admin of a department sees what that department's key
  paid for plus their own, platform admin sees everything, and `scope` in the response
  says which. Needed `llm_usage.dept_id` (migration `0018`), stamped from the paying key,
  because Pulse must not read identity's database and so cannot ask which department a
  `user_id` belongs to. Rows written before it carry null and count towards their own
  user and the platform total only.
- **Dated activity fixtures in `test_adhoc_reports.py` will age out.** Visibility and
  write access are a rolling window off the clock
  (`REPO_VISIBILITY_ACTIVITY_DAYS`, default 90). Every other suite's activity fixtures
  were made relative; `test_adhoc_reports.py` still seeds July 2026 activity and sends
  `range_start` / `range_end` as fixed strings in the request body, so making it relative
  means rewriting the ranges and the assertions on them together. It passes today and
  starts 403ing once that July activity falls outside the window.
- **Playwright is not in the repo or in CI.** The browser check of the chat page
  (`services/pulse/frontend/pages/chat.vue:308-330`) was run from a throwaway install
  outside the tree, so nothing reproduces it. The Vitest component tests cover the same
  logic; what is missing is the real-browser regression.
- **`.dockerignore` is ineffective for Pulse and Forge.** Both build with
  `context: .` (repo root), where no `/.dockerignore` exists, so every build ships
  the full ~537MB context. Identity builds from its own directory and is fine.
- **No application service has a Docker healthcheck.** Only `postgres` and `redis`
  have one, so `depends_on: service_started` means "the process launched", not
  "it's ready to serve".
- ~~**No Python linter, formatter or typechecker anywhere in CI.**~~ **MOSTLY CLOSED.**
  `ruff.toml` at the repo root and a `ruff` CI job lint `services/*` and `packages/core`.
  The ruleset is deliberately narrow — ruff's default (`E4`, `E7`, `E9`, `F`) plus
  bugbear (`B`) — chosen to catch defects rather than argue about layout. `B008` is
  waived for FastAPI's `Depends`/`Query` (its dependency system is a function call in a
  default argument by design) and `E401` for the repo's one-line imports. `mypy` gates
  `packages/core` only, via its `pyproject.toml`, because that package already passes.
  What is left:
  - **The formatter is not a gate.** `ruff format --check` wants to rewrite **218 of 240
    files, 43,879 diff lines**, almost all of it the repo's one blank line between defs
    and its single-line function signatures. Widening `line-length` does not help (216
    files at 200 or 300). Adopting it is a decision about house style, not a fix, and a
    diff that size would bury every other change in flight.
  - **`B904` (`raise ... from`) is waived**, 52 sites, all of them a service converting a
    domain error into an `HTTPException`. Mechanical, and nothing a caller sees changes.
  - **mypy on the services is not gated**: 121 errors in identity, 193 in pulse, 9 in
    forge under `--ignore-missing-imports`. Most are the SQLAlchemy 1.x `Column` API
    typing as `Column` where a scalar is expected, so closing it is a modelling decision
    (2.0 `Mapped[...]` annotations), not an afternoon of annotations. Forge's 9 are small
    enough to be worth doing on their own.
- **Local Postgres reuses the Neon password.** `CC_POSTGRES_PASSWORD` in the
  root `.env` is the same string as the Neon connection password. Nothing leaks
  today (both are git-ignored) but they should be different secrets.
- **`GET /departments` is visible to every signed-in user.** Deliberate: an
  internal org chart isn't secret, and acting on a department still needs
  membership. Revisit if that ever feels wrong.

---

## Done in session 04 (review follow-ups)

- ~~**JWT issuer default was stale**~~: `config.py` defaulted `JWT_ISSUER` to
  `crescent-identity` while everything else uses `cyphercrescent-identity`.
  Running without the env var set would have made every product reject valid
  tokens. Default now matches the canonical value.
- ~~**`accept_invite` could 500**~~: a double-submit / race of the same invite
  token tripped `uq_membership_user_dept` as an unhandled `IntegrityError`. Now a
  clean 409, guarded both by a pre-check and a rollback-on-IntegrityError.
- ~~**Shared pagination helper**~~: `crescent_core.pagination` (`Page[T]`,
  `PageParams`, `page_params`), ready for the Pulse reports/comments lists.
  Identity's members list gained filtering (`role`, `team_id`, `q`) on top of the
  pagination it already had.

## Done in previous sessions (kept for reference)

- ~~`GET /me`~~: session 03. Now returns **every** membership, not one
  arbitrary "active" one (see decisions doc, Decision 1).
- ~~`PATCH /me`~~: session 03. Own name/avatar only; role and department are an
  admin's call.
- ~~Password change~~: session 03. `POST /auth/change-password` verifies
  current, validates new, bumps `tv`, revokes refresh tokens, issues a fresh
  pair so the caller stays logged in on that device.
- ~~`POST /auth/logout-all`~~: session 03. `revoke_all_for_user` had existed
  since session 02 with no route, so "log out everywhere" was unreachable.
- ~~Identity's own `get_current_user`~~: session 03, `app/security/dependencies.py`.
- ~~Rate limiting on auth endpoints~~: session 03. `slowapi`, per-IP: 5/min
  register, 10/min login, 30/min refresh, 5/min change-password, 5/min invite
  accept, 20/min invite preview. Toggle: `RATE_LIMIT_ENABLED`.
- ~~Department switching~~: **no longer needed.** Removed by the session-03
  restructure: every endpoint names its department and tokens carry all
  memberships, so there is no "active department" to switch.
- ~~Registration is still the founder flow~~: closed in session 03.
  Registration is bootstrap-only; everyone else arrives by invite.
