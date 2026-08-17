# Week 6 plan — Visual ML workflows (Forge)

Written 2026-08-17. Scope authority is the internship PDF at the repo root. Where
`docs/backlog.md` and the PDF disagree, **the PDF wins** and this document says where.

Everything in section 2 was verified by running it, not by reading a claim.

---

## 1. What the PDF actually says Week 6 is

Verified against `8-Week Software Engineering Internship Plan — CypherCrescent.pdf`,
page 3 (week detail) and page 4 (deliverables table).

**Week 6 — Visual ML workflows.** Guided workflows for four cases: tabular
prediction from CSV, basic image classification, a simple time-series forecast, and
an LLM playground (prompt testing, captioning, Q&A). Preprocessing and feature
choices must be **visible in the UI** — the PDF is explicit that the point is
learning, not hiding every step behind a Run button. Side-by-side comparison of two
runs is called out as an extra, not a requirement.

**Done when:** at least one full path (data in → train/run → result) works for
tabular **and one other modality**.

**Deliverables table, week 6:** visual workflows for tabular plus at least one
other task type.

Two things follow from reading it closely:

- **The prose and the "done when" set different bars.** The prose names four
  modalities; the completion condition requires two. The completion condition is the
  contract. This plan targets two and names what moves.
- **Week 7 constrains Week 6.** Week 7 is "From canvas to code": generate readable
  Python from a **completed workflow**. So whatever Week 6 stores has to describe a
  workflow declaratively enough that Week 7 can render it as code. Store only fitted
  models and metrics and Week 7 begins with a schema rewrite.

---

## 2. Where we actually are

### 2.1 Test suites — all green, all run today

| Suite | Command run | Result |
|---|---|---|
| `packages/core` | `env -u PYTHONPATH ../../.venv/bin/python -m pytest -q` | **101 passed** |
| `services/identity` | same | **516 passed**, 98% cov, 317s |
| `services/pulse` | same | **395 passed**, 98% cov |
| `services/forge` | same | **75 passed**, 96% cov |
| `tests/contract` | same, from repo root | **9 passed** |
| `packages/ui` | `npx vitest run` | **154 passed** (15 files) |
| `services/identity/frontend` | `npx vitest run` | **160 passed** (10 files) |
| `services/pulse/frontend` | `npx vitest run` | **73 passed** (8 files) |
| `services/forge/frontend` | `npx vitest run` | **60 passed** (5 files) |

All four `npm run typecheck` runs exit clean (`packages/ui` via `vue-tsc`, the three
apps via `nuxt typecheck`). Note that `npx nuxi typecheck` fails in `packages/ui` —
it is a Nuxt *layer*, not an app. Use the package script, which is what CI does.

Identity's suite takes over five minutes. That is argon2 doing its job, not a
problem, but it means "run the tests" is not a thing you do casually mid-edit.

### 2.2 What CI actually runs

`.github/workflows/ci.yml` has **12 jobs**:

| Job | What it does |
|---|---|
| `identity` | install, module-level import check, pytest, `--cov-fail-under=95` |
| `core` | install with dev extras, pytest |
| `migrations` | identity migrations from scratch on real Postgres 16, autogenerate drift check, downgrade to base and re-apply |
| `contract` | identity's token minter against `packages/core`'s verifier — the only job that runs both sides together |
| `pulse` | install, import check (web **and** celery), pytest, `--cov-fail-under=90` |
| `pulse-migrations` | same Postgres/drift/downgrade treatment |
| `packages-ui` | `vue-tsc` strict, vitest |
| `pulse-frontend` | typecheck, tests, Nuxt build |
| `identity-frontend` | typecheck, tests, Nuxt build |
| `forge-frontend` | typecheck, tests, Nuxt build |
| `forge` | install, import check, pytest, `--cov-fail-under=85` |
| `forge-migrations` | same Postgres/drift/downgrade treatment |

The three frontend app jobs are the recent addition. `docs/sessions/2026-08-09-session-08.md`
recorded "Pulse's frontend is not in CI" as an open gap; that gap is **closed** —
`pulse-frontend` exists now, alongside `identity-frontend`.

**CI gaps that are still real:**

- **No Python linter, formatter or typechecker anywhere.** No ruff, flake8, mypy,
  eslint or prettier config exists in the repo. The only static analysis is
  `vue-tsc` on the frontends. A misused pandas API that only fires on a real
  dataframe would pass the import check and the SQLite tests.
- **Forge's coverage floor is 85**, and the job's own comment says "Raise this as
  features land." A new `training.py` with thin tests can land while CI stays green.
- **No end-to-end job.** Nothing boots a frontend against a live API. Every
  frontend test is a component test against mocks.
- **The new Forge queries would be SQLite-only.** `forge-migrations` touches
  Postgres but never runs an application query against it. The backlog already
  flags exactly this for Pulse's visibility filter; Forge is about to inherit it.

### 2.3 Forge is datasets and nothing else

Verified by reading every file in `services/forge/`.

| Piece | State |
|---|---|
| `app/models/__init__.py` | **one table**: `Dataset` (`content` is a `Text` column holding raw CSV) |
| `app/routes/` | `datasets.py`, `health.py`. That is all. |
| Endpoints | `POST /datasets`, `GET /datasets`, `GET /datasets/summary`, `GET /datasets/{id}`, `GET /datasets/{id}/preview`, `DELETE /datasets/{id}` |
| Migrations | `0001_datasets`, `0002_sample_name_unique` |
| ML dependencies | **none.** `requirements.txt` has no pandas, numpy, scikit-learn, torch or openai |
| LLM path | **none.** No `LLM_API_KEY` in `app/config.py`, no llm module |
| Background jobs | **none.** `docker-compose.yml:145` says so in as many words; `render.yaml` defines no Forge worker |
| Binary/blob storage | **none.** Datasets are UTF-8 CSV text or they are rejected (`_parse_csv`) |
| Samples | two, both tabular: Iris (6 rows) and Monthly Sales (6 rows) |

The frontend is further along than the backend, and is honest about it.
`pages/canvas.vue` carries a comment saying it is a static sketch that exists "to
settle the vocabulary and the shape of the builder before it is built".
`constants/canvasModules.ts` defines twelve modules in four groups.
`constants/learningPaths.ts` specifies four paths step by step. `RoadmapPanel.vue`
renders a build ledger with four `live: true` rows and three `live: false` rows
tagged "week 6", and states in body copy: "No ML libraries are installed yet, so
nothing here trains a model."

That honesty is an asset. It also means **every one of those surfaces is a dated
promise**, and the plan has to either keep it or rewrite it.

### 2.4 Identity — what recently landed

Commit `e85b93d` ("per-device sign-out, email change, and department transfers")
added real capability:

- `GET /me/sessions`, `DELETE /me/sessions/current`, `DELETE /me/sessions/{session_id}`
  in `app/routes/me.py` — per-device sign-out is reachable, not just modelled.
- `POST /auth/change-email` and `POST /auth/confirm-email-change`, backed by
  `email_change_tokens` (migration `0011`).
- Token-version bumps on the paths that need them. `confirm_email_change`
  (`app/services/auth.py:437-451`) revokes every unrevoked refresh token, increments
  `token_version` and calls `revocations.publish_user_revoked`.
- Identity is now at migration `0012`.

### 2.5 Documented gaps — verified, with two corrections

I checked each one in the code rather than restating it.

| Gap | Verdict |
|---|---|
| Nothing lifts the "unverified email" flag | **Partly wrong now.** `app/services/auth.py:443` sets `email_verified = True` in `confirm_email_change`. So there *is* one lifting path — but it requires changing your email address to a different one. A `/auth/signup` user who is happy with their address still has no way out of the flag. There is no resend-verification endpoint. The gap is real; the description isn't. |
| No audit log | **Confirmed.** `grep -rni audit` across `services/{identity,pulse,forge}/app` and `packages/core` returns **zero** matches. `docs/meridian-frontend-spec.md` §8.4 says the landing hero copy has been removed, but the spec's Sessions screen still renders a `SECURITY_EVENTS` rail and the sign-in trust list still claims an audit trail. |
| `sync_runs` has no trigger column | **Confirmed.** The model (`services/pulse/app/models/__init__.py`) has `repo_id, status, detail, started_at, finished_at`. Nothing records manual vs scheduled, so the UI's "inferred" label is the only honest thing it could say. |
| `refresh_tokens` stores no user-agent or IP | **Confirmed.** Columns are `token_hash, user_id, family_id, expires_at, is_revoked, replaced_by, created_at`. Sessions can now be *revoked* individually but still cannot be *named*. |
| Historical `sync_runs` rows carry pre-sanitisation detail | **Cannot verify from the repo.** The sanitisation is in the current code path; what is already stored is a data question needing a query against a database with real history. |
| `render.yaml` never applied to Render | **Confirmed as documented.** `DEPLOY.md`'s first section says so itself and lists what *has* been verified — all of it local. |
| Three frontend components uncommitted | **No longer true.** `git status --porcelain` on `IdentityShell.vue`, `InviteDialog.vue` and `RowMenu.vue` is empty. They landed in `ea81674` ("last batch of fixes"), which is HEAD and postdates the brief for this document. The tree is shared; re-check before you touch anything. |

---

## 3. Where the PDF and the repo disagree

| # | The PDF says | The repo says | Reconciliation (PDF wins on scope) |
|---|---|---|---|
| 1 | Week 5 is the no-code platform's **shell and onboarding** — Nuxt frontend, CSV upload with preview, sample datasets, canvas sketched early | `docs/backlog.md` labels four **backend** items "Week 5": the approver-email service-to-service auth, self-signup + admin placement, the app-wide user directory, and the frontend report link | The backlog is mislabelling. Those are Pulse and identity backend items that happened *during* week 5, not week 5's deliverable. The backlog's own "Forge, Week 5" entry is the one that matches the PDF, and it is marked delivered. Nothing to fix in code; the labels are the problem. |
| 2 | Week 6 prose names **four** modalities | Zero exist | The PDF's own "done when" requires **two**. Build two. §5 names what moves and where. |
| 3 | Week 5 says sketch the canvas early so Week 6 has something to hang workflows on | `pages/canvas.vue` is explicitly a static drawing: no drag, no connections, no Run | Week 6 starts from a written vocabulary, not a working canvas. That is a real cost the plan absorbs in item A4. |
| 4 | Stack lists the OpenAI API for "learning assistants" in the no-code product | Forge has no `openai` dependency and no `LLM_API_KEY`. Pulse has both, plus `app/services/llm.py` and an `llm_usage` ledger. Nothing is shared via `packages/core` | The LLM playground is not a small addition to Forge. It is a provider decision, a config key, a usage ledger and a spend owner. Stretch at best. |
| 5 | Week 6 includes basic **image classification** | Forge's only storage is a CSV text column; uploads that aren't UTF-8 CSV are refused. No object store in `docker-compose.yml` or `render.yaml` | Image classification needs a whole new storage story plus a model runtime. It is not a week-6-sized item on this codebase. Moves out. |
| 6 | Week 6 says **train** | Forge has no Celery app, no worker container and no worker service in `render.yaml`. Pulse has all three | Needs a decision (§6, item 2): in-process with hard caps, or stand up a Forge worker. |
| 7 | Weekly rhythm: daily check-in, pairing, PR review before merge, Friday demo to leads | One developer, several concurrent agents on a shared tree | Already substituted: `docs/sessions/` and `docs/backlog.md` are the standing record. Not a scope disagreement. |
| 8 | Week 8 is Compose, CI, logging, security checks, docs | Already largely done: 12 CI jobs, `docker-compose.yml`, `render.yaml`, `DEPLOY.md`, three service READMEs | Week 8 has slack in it. That is where displaced Week-6 scope should land, not into an already-full Week 7. |

---

## 4. The fork: does Forge continue?

A sibling session is writing `docs/product-strategy-research.md` (615 lines as of
this writing) on whether Forge is worth building at all. **This document does not
pre-empt that answer.** It gives you the two Week 6s so the answer converts straight
into work.

The thing worth internalising: **the branch point is cheap today and expensive on
Wednesday.** Branch A's second item commits pandas and scikit-learn to
`services/forge/requirements.txt` and lands migration `0003`. From that moment the
work argues for itself, the Forge image roughly triples, and "should we build Forge"
becomes "we already did most of it". Take decision 1 before writing any code.

What is genuinely shared between the branches is small and honest:

- **The decision itself** (§6 item 1).
- **The Forge UI's dated promises.** `pages/canvas.vue`, `pages/learning/index.vue`,
  `pages/learning/[slug].vue` and `components/RoadmapPanel.vue` all carry a
  "Week 6 · not built" tag and a `LEDGER` with `live: false` rows. Under A those get
  deleted one at a time as features land. Under B they get rewritten to say
  something that stays true. Either way they get touched this week — the shape
  depends on the branch, so it is not work you can start early.

Everything else diverges immediately.

---

## 5. The plan

### Branch A — Forge continues as planned

Sequenced by dependency. Nothing below starts before the item above it is done.

#### Must ship

**A0 · Decide the runtime and the workflow shape** — **S**, blocks A1–A5

Two decisions written down before any code:

1. **Where does training run?** On the 6-row samples, in-process is instant. On a
   5 MB CSV, a scikit-learn fit can outlast a web request's patience and will hold a
   uvicorn worker while it does. *Recommendation:* run in-process behind hard row and
   column caps plus a timeout for Week 6, and record the worker as a known
   limitation. A worker is a Celery app Forge doesn't have, a second compose
   container and a second Render service — a day of infrastructure that buys the
   Week-6 demo nothing.
2. **What does a stored workflow look like?** Week 7 generates Python from a
   completed workflow, so the record must be a **declarative step list** (dataset,
   target, features, preprocessing choices, model kind, parameters) — not the fitted
   estimator's internals. Get this wrong and Week 7 opens with a migration.

*Files:* a new `docs/decisions/2026-08-1X-forge-workflows.md`.
*Verified by:* the decision doc existing, and the A2 migration draft matching it.
*Done when:* both questions have a written answer with the reasoning, in the same
format as the two existing decision docs.

**A1 · ML dependencies and the tabular training core** — **M**, blocks A3–A5

*What:* add `pandas` and `scikit-learn` to `services/forge/requirements.txt` (and so
`requirements-dev.txt`, which includes it). New `app/services/training.py` taking a
`Dataset` row, a target column and a feature list, returning fitted-and-scored
results. Classification (accuracy, confusion matrix, feature importance) and
regression (MAE, R²) — the two paths `constants/learningPaths.ts` already specifies
step by step. New `app/services/preprocess.py` for the choices the PDF wants
*visible*: null filling, text encoding, the train/test split.

*Why now:* nothing else in Week 6 can happen. `RoadmapPanel.vue` says out loud that
no ML libraries are installed.

*Verified by:* pytest against the two bundled samples, with a fixed `random_state`
so they're deterministic — a classification fit on Iris `species` must beat
majority-class accuracy; a regression fit on Monthly Sales `revenue` must return a
finite MAE. Plus `docker compose build forge` succeeding and its image size
measured, not assumed.

*Done when:* forge's pytest is green, the coverage floor still passes, and the
Docker build works.

**A2 · Workflow and run schema, migration `0003`** — **M**, blocks A3

*What:* `workflows` (`owner_user_id`, `dataset_id`, `path_slug`, `name`, `steps`
JSON per A0.2, timestamps) and `workflow_runs` (`workflow_id`, `status`,
`started_at`, `finished_at`, `metrics` JSON, `error`). Ownership mirrors `Dataset`:
`owner_user_id` referencing identity by id only, never a copy of the user — CLAUDE.md
rule 3.

*Files:* `app/models/__init__.py`, `alembic/versions/0003_workflows.py`,
`app/schemas/workflows.py`.

*Verified by:* CI's `forge-migrations` job, run locally against the compose Postgres
first — apply from scratch, autogenerate must produce an empty migration, downgrade
to base and re-apply. SQLite green is not evidence here.

*Done when:* that job passes on real Postgres with no drift.

**A3 · The workflow API** — **M**, blocks A4

*Endpoints:* `POST /workflows`, `GET /workflows`, `GET /workflows/{id}`,
`DELETE /workflows/{id}`, `POST /workflows/{id}/run`, `GET /workflows/{id}/runs`,
`GET /workflows/{id}/runs/{run_id}`.

Plus one the UI cannot work without: **`GET /datasets/{id}/columns`** returning per
column a name, an inferred type, a null count and a distinct count. This is what
makes "preprocessing and feature choices visible in the UI" possible, which is the
PDF's stated emphasis — not a nicety.

Permissions copy `datasets`: own-or-sample readable, owner-only delete. Rate limits
through the existing `app/rate_limit.py` limiter.

*Verified by:* pytest — a run against Iris returns metrics; a target column with one
distinct value returns a typed 422 rather than a scikit-learn traceback; a non-owner
gets 403; a dataset past the caps gets a typed refusal. The typed-failure discipline
is already the house style in `app/services/datasets.py::_parse_csv`; match it.

*Done when:* all eight routes answer and every failure mode is typed, not a 500.

**A4 · The frontend: one path end to end** — **L**, blocks A5

*What:* turn `pages/canvas.vue`'s sketch and `pages/learning/[slug].vue`'s "not
runnable" rows into a working form — dataset → target → features (showing the A3
column types and null counts) → Run → result. TanStack Query with the existing key
convention (`["workflows"]`, `["workflow", id, "runs"]`, matching
`["datasets", "list"]` in `pages/index.vue`). Remove the `WEEK6_TAG` from whatever
now works and only from that. Update `RoadmapPanel`'s `LEDGER` rows from
`live: false` to `live: true` as they become true — those rows are load-bearing
honesty, not decoration.

*Verified by:* vitest component tests for form validation and the result render,
**plus a real browser round trip** — compose up identity, forge and the Nuxt app,
log in, pick Iris, train, read the accuracy back, screenshot into the session log.
The backlog already owes this: "Live Forge browser walkthrough" has been open since
the login → upload → preview → delete flow shipped. Do it once and pay both debts.

*Done when:* a first-time user gets from dataset to result without reading code, and
`npm run typecheck` and `npm test` are clean in `services/forge/frontend`.

**A5 · The second modality: time-series forecast** — **M**

*What:* forecast on the Monthly Sales sample — n periods ahead with a point estimate
per period.

*Why this one and not image classification or the LLM playground:* it needs no new
storage, no new content type and no dependency beyond what A1 already installs;
`learningPaths.ts` already specifies its steps; and `canvasModules.ts` already has a
`Forecast` module under Model. Image classification needs binary storage Forge does
not have. The LLM playground needs a provider, a key, a ledger and a spend owner.

*Verified by:* a forecast run on Monthly Sales returning the requested number of
future periods with finite estimates; a component test on the chart's empty and
error states.

*Done when:* two modalities complete data in → run → result. **That is exactly the
PDF's "done when", so this item is the week's finish line.**

#### Should — if A0–A5 land with time left

- **Raise forge's `--cov-fail-under` above 85** in `.github/workflows/ci.yml`. The
  job's own comment asks for this once features land, and a brand-new `training.py`
  is that moment. Do it in the same commit as the module or it won't happen.
- **Surface the column statistics as a "what we noticed about your data" panel.**
  Cheap once A3 exists, and it's the most direct answer to the PDF's insistence that
  preprocessing be visible.
- **Run the new workflow-list query against Postgres.** The backlog already carries
  "New Pulse visibility queries are unverified against Postgres" as an open item.
  Don't let Forge inherit the same debt on day one.

#### Stretch — named, deliberately not planned into the week

- **LLM playground.** Needs a provider decision, a key in `app/config.py`, a usage
  ledger and a named spend owner. Pulse's `app/services/llm.py` plus its `llm_usage`
  ledger is the pattern, but copying it a second time is the signal to extract it
  into `packages/core` instead — which is a refactor, not a Week-6 feature.
- **Image classification.** Binary storage, a content-type story, a model runtime.
  Not a week's work here.
- **Side-by-side run comparison.** The PDF itself calls this an extra, not a
  requirement.

#### Is the PDF's Week 6 bigger than one developer's week? Yes — plainly.

The prose asks for four modalities, on a canvas that does not exist, in a service
with no ML dependency, no worker and no LLM path. A0–A5 is a tight full week for one
person and it satisfies the PDF's own completion condition.

**What moves, and where:**

| Displaced | Goes to | Why there |
|---|---|---|
| Image classification | Week 8, or a recorded limitation | Week 8 has slack — Compose, CI and deploy docs are already built (§3 item 8). Week 7 does not. |
| LLM playground | Week 7 or Week 8 | It sits naturally next to "show the learner what happened under the hood", but Week 7 is already a full week. Depends on §6 item 4. |
| A working drag-and-drop canvas | Week 7 | Week 7 is the canvas-to-code week; a real canvas belongs to the week that has to read one. |
| Side-by-side comparison | Cut unless free | The PDF says extra. Believe it. |

### Branch B — Forge gets repositioned

Under B, **do not start A1.** Committing pandas, scikit-learn and migration `0003`
is the point past which the decision has effectively been made.

Every item below is work the repo has already written down as open. None of it is
invented for this document.

#### Must ship

**B1 · Stop the Forge UI promising Week 6** — **S**

*What:* `pages/canvas.vue`, `pages/learning/index.vue`, `pages/learning/[slug].vue`
and `components/RoadmapPanel.vue` each carry a "Week 6 · not built" tag; the
`RoadmapPanel` ledger marks three rows "week 6". If Forge is repositioned, those
become a promise nobody is keeping — the exact failure mode the whole panel was
built to avoid.

*Verified by:* the existing 60 `forge-frontend` tests, plus an added assertion that
no "Week 6" string remains in `services/forge/frontend/`.
*Done when:* the UI's claims match the actual roadmap.

**B2 · Build the audit log, or cut every claim** — **M**

*Why now:* `docs/meridian-frontend-spec.md` §8.4 lists three places the word "audit"
appears in copy and a `SECURITY_EVENTS` rail with no table and no endpoint behind it.
I verified there is no audit code anywhere in the repo. The spec's own verdict is
that shipping the copy without the feature is what gets noticed in a security
review, and it is right.

*Files:* `services/identity/app/models/__init__.py`, a new
`alembic/versions/0013_audit_log.py`, `app/services/audit.py`, write calls at the
events the copy already names (login, failed login, logout-all, password change,
email change, role change, department transfer, invite accept), and
`GET /platform/audit` gated to platform admin alongside the existing
`app/routes/platform.py` routes.

*Verified by:* pytest — a login writes exactly one row; a failed login writes a row
and issues no token; a non-admin gets 403 on the read endpoint. Plus the
`migrations` job's Postgres round trip.
*Done when:* every event the copy claims has a row, or the copy is gone. Not half of
either.

**B3 · Move tokens out of `localStorage` into httpOnly cookies** — **M**

*Why now, specifically:* the backlog calls this "a blocker, not a nice-to-have", and
says the swap is a one-file change in
`packages/ui/composables/useTokenStorage.ts` (all three frontends `extends` the
layer). It was deferred for one reason only — the cookie config depends on
deployment topology, undecided as of 2026-08-08. **`DEPLOY.md` now settles the
topology:** three Nuxt apps on Vercel, three FastAPI services on Render, separate
hostnames. That means `SameSite=None; Secure`, HTTPS throughout, CORS with
credentials. The blocker on the blocker is gone.

*Verified by:* a real round trip on the compose stack — sign in, confirm via
devtools that no token is in `localStorage`, reload and stay signed in, sign out and
confirm the cookie is cleared. Plus all four frontend suites and typechecks.
*Done when:* `useTokenStorage.ts` no longer touches `localStorage` and CI's four
frontend jobs are green.

#### Should

**B4 · Apply `render.yaml` to Render, for the first time** — **M**

*Why now:* `DEPLOY.md`'s opening line says the blueprint has never been applied and
should be treated as a starting point rather than a tested artefact. Until it is
applied, every deployment claim in that document is inference.

*Verified by:* the blueprint creating the services; `alembic upgrade head` running
as the pre-deploy command on all three; `/health` answering on all three; a login
working end to end against the deployed identity.
*Done when:* `DEPLOY.md`'s "what has been verified" section can name Render instead
of only localhost.

**B5 · Close the department-admin notification gap** — **M**

*Why now:* it is the backlog's own top "next up" item, dated for 2026-08-11 and
still open. `notify_report_ready` (`services/pulse/app/services/email.py:92`) mails
only a repo's named lead and deputy. A repo with a department but neither named takes
the `else` branch, logs "no approvers to notify" and mails **nobody** — while
`_can_approve` and the list scope both put that report in every dept admin's review
queue. It can sit unreviewed indefinitely with nobody prompted.

*What it takes:* a new identity scope, a scope-gated endpoint beside the three in
`app/routes/internal.py` (the existing `GET /departments/{dept_id}/members?role=admin`
needs a *user* token a service can't present), the Pulse-side client call, and the
notification branch.
*Verified by:* pytest on both sides plus the `contract` suite.
*Done when:* a repo with a department and no lead or deputy produces mail to that
department's admins.

#### Stretch under B

- Lock `SIGNUP_ALLOWED_DOMAINS` to the org — it is empty, meaning allow-all.
- A resend-verification endpoint, so §2.5's flag has an exit that isn't "change your
  email address".
- The `sync_runs` trigger column, so the UI can stop saying "inferred".

---

## 6. Decisions needed before work starts

| # | Decision | Who | Blocks | Cost of guessing |
|---|---|---|---|---|
| 1 | **Does Forge continue as planned, or get repositioned?** | user + supervisor, informed by `docs/product-strategy-research.md` | everything | Branch A's second item is the point of no easy return. Cheap today, expensive Wednesday. |
| 2 | If A: in-process training, or stand up a Forge Celery worker? | user | A1, A3 | Retrofitting a worker after the API exists changes every run endpoint from synchronous to polled — a contract change through the API, the schema and the UI. |
| 3 | If A: which second modality? (recommend time-series) | user | A5 | Image classification silently drags in binary storage, a content-type story and a model runtime. |
| 4 | If A: is an LLM playground in scope, and **who owns the API spend**? | supervisor | stretch scope | Pulse already spends against `LLM_API_KEY`. A second spender with no named budget owner is not a conversation to have retroactively. |
| 5 | Audit log: build it, or cut every claim that references it? | supervisor | B2 | The spec's own words: shipping the copy without the feature is what gets noticed in a security review. |
| 6 | Cookie topology: all three apps behind one domain, or separate Vercel hostnames? | user | B3 | `SameSite=Lax` vs `SameSite=None; Secure`. `DEPLOY.md` implies separate hostnames; confirm before writing it, because some corporate browser configs block the cross-site form. |

---

## 7. Risks and how they bite

| Risk | How it bites | Early warning | What to do |
|---|---|---|---|
| pandas + scikit-learn roughly triple Forge's image | A Render deploy nobody has ever done fails on build time or disk, on the plan you can't test locally | `docker compose build forge` wall time and `docker images` size, measured before committing | Measure in A1, not after. Pin scikit-learn without optional extras. |
| In-process training holds a uvicorn worker | One 5 MB fit blocks other Forge requests. The rate limiter won't save you — it counts requests, not seconds | Any fit over a second or two on the largest CSV you can upload | Hard row and column caps enforced inside `training.py`, plus a timeout. Both decided in A0. |
| Week 6's schema doesn't survive Week 7 | "Canvas to code" needs a declarative step list. If `workflow_runs` only stores metrics, Week 7 opens with a migration and a rewrite | You notice while writing A2's model and shrug | This is the one risk that costs a rewrite rather than a fix. Settle it in A0.2, in writing. |
| Several agents share this tree | Two of §2.5's "known gaps" were already stale by the time this document was written; the three frontend components landed in HEAD mid-brief | State you were told doesn't match `git status` | Re-check `git status` on the **specific paths** you're about to touch, never repo-wide, before every edit. |
| Building Branch A while the strategy answer is open | Two days into A1/A2, sunk cost starts making the argument for you | You're installing scikit-learn and nobody has answered decision 1 | Take decision 1 first. It is the cheapest thing on this page. |
| Forge's coverage floor sits at 85 | A new `training.py` with thin tests lands and CI stays green, so nothing tells you | Coverage report barely moves after a large new module | Raise the floor in the same commit as the module. |
| No Python linter or typechecker in CI | A pandas API misuse that only fires on a real dataframe passes the import check and every SQLite test | Nothing warns you. That's the point. | Out of scope for Week 6; worth naming as the largest standing CI gap. |
| `render.yaml` has never been applied | Any claim this week about how Forge's new dependencies behave in production is inference stacked on inference | `DEPLOY.md` already says every Render claim comes from documentation | Under A, don't make deployment claims. Under B, B4 fixes it. |

---

## 8. What could not be determined from the sources

- **The sibling session's conclusion** in `docs/product-strategy-research.md`.
  Deliberately not read, so §4 stays a genuine fork.
- **Whether historical `sync_runs` rows still carry pre-sanitisation detail
  strings.** The sanitisation is in the current code path; what is already stored
  needs a query against a database with real sync history. Nothing in the repo can
  answer it.
- **Whether Render's starter plan tolerates a pandas + scikit-learn Forge image.**
  `DEPLOY.md` is explicit that everything about Render's behaviour comes from their
  documentation rather than a deploy that worked.
- **Actual Docker image sizes.** Not measured; the tripling estimate in §7 is from
  the dependency set, not from a build.
