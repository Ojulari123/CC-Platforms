# Deploying Meridian

A runbook. Follow it top to bottom. Every step says who does it, what to run or click,
and how to confirm it worked before you move on. If a confirmation fails, stop there:
each step is depended on by the ones after it.

Two Nuxt apps on Vercel, two FastAPI services plus one Celery worker on Render, two
Postgres databases on Neon, one Key Value instance on Render. The Render bill is $7 a
month, all of it the worker. Read "What the free tier costs you" before you rely on any
of this.

Forge is not deployed. Its own pages say it is not built yet, so it is not worth an
instance or a Vercel project. "Adding Forge back" at the end of this file is the whole
procedure for when it is.

`docs/deploy-env-matrix.md` is the reference for every variable named here: what it does,
whether it is required, and what breaks when it is wrong. Keep it open alongside this.

## What has been verified, and what has not

Verified locally, on this machine:

- All three front ends build from a clean tree with the shared Nuxt layer resolved by
  relative path, under the same Nitro preset Vercel uses. The generated
  `.vercel/output/config.json` ends in a catch-all route to the app shell, which is what
  makes a deep link such as `/reports/12` load instead of 404.
- The SSO allowlist validator rejects a bare origin and rejects plain `http`, both with a
  message naming the entry.
- The full test suite passes: Pulse 1088, identity 517, Forge 76, packages/ui 239,
  Pulse front end 227, identity front end 160, Forge front end 60.
- The merged worker command, `celery -A app.celery_app.celery worker --beat`, run against
  the built Pulse image and a local Redis. One process registered both tasks, started beat,
  queued `daily-github-sync` and consumed it. The standalone `celery beat` command queued
  the same task at the same point in startup, so the fire-on-cold-start below is inherited,
  not caused by the merge.

Read from Render's own documentation on 2026-08-26, not from a dashboard:

- Free web services sleep after 15 minutes and take about a minute to wake; 750 free
  instance-hours per workspace per month; no persistent disk, no SSH, no one-off jobs, no
  inbound private network traffic; no outbound on ports 25, 465, 587.
- The pre-deploy command is available only on paid web services, private services and
  background workers. That is why `render.yaml` no longer has one.
- Background workers have no free instance type. Web/worker `starter` is $7/month.
- Render Key Value has a free plan: 25 MB, 50 connections, no persistence, one per
  workspace.

Not verified, because it needs an account:

- Anything about Render's or Vercel's own dashboards: whether a setting is where this
  document says it is, whether the figures above have moved since.
- `render.yaml` has still never been applied. It is written from Render's schema, not
  from a deploy that worked.
- Neon has never been contacted from this repo's tooling.

## What runs where

| Piece | Where | Plan | Cost | Local equivalent |
|---|---|---|---|---|
| `identity-web` | Vercel | hobby | $0 | `identity-web` container, :3002 |
| `pulse-web` | Vercel | hobby | $0 | `pulse-web` container, :3001 |
| `crescent-identity` | Render web service | free | $0 | `identity` container, :8001 |
| `crescent-pulse` | Render web service | free | $0 | `pulse` container, :8002 |
| `crescent-pulse-worker` | Render worker | starter | $7/mo | `pulse-worker` and `pulse-beat` containers, merged |
| `crescent-keyvalue` | Render Key Value | free | $0 | `redis` container |
| two Postgres databases | Neon | free | $0 | one `postgres` container, three databases |

The local stack still runs `pulse-worker` and `pulse-beat` as two containers, and still
runs Forge. Only the deployment is trimmed.

## Before you start

Have these ready. Getting one of them mid-run is what turns an hour into an afternoon.

- Accounts: Neon, Render, Vercel, GitHub, Brevo, OpenAI. Anthropic is optional.
- A Brevo sender address that Brevo has verified. An unverified sender is accepted by the
  API and then never delivered.
- The repository pushed to GitHub, on the branch you want deployed.
- A scratch note with four blank lines on it, labelled `<identity-api>`, `<pulse-api>`,
  `<identity-web>`, `<pulse-web>`. You will fill them in as you go and paste them into
  about twenty fields. Getting them consistent is most of this job.

---

# Part 1: Neon

### Step 1. You: create two databases

In the Neon console, create two databases. One project with two databases is enough, but
two separate projects is what actually enforces CLAUDE.md rule 3: separate credentials
mean no service can reach another's rows even by mistake.

Name them `identity` and `pulse`. A third, `forge`, already exists and is migrated; it is
not used until you follow "Adding Forge back". Put them in the region you will put Render
in.
The connection strings currently sitting in `services/*/.env` are `us-east-1`, which
pairs with Render's **Virginia** region, and `render.yaml` is set to Virginia to match.

**Confirm:** both appear in the console and show a size.

### Step 2. You: collect four connection strings, not two

For each database, Neon offers a **pooled** and a **direct** connection string. The
pooled one has `-pooler` in the hostname. Copy both for each database.

This deployment uses the **direct** string everywhere:

- You run `alembic upgrade head` over the same `DATABASE_URL` from your own machine, and
  Neon's pooled endpoint is PgBouncer in transaction mode, which cannot execute `SET` at
  all.
- Pulse's migration `0008_repo_index` creates the pgvector extension and an HNSW index on
  `repo_chunks.embedding`. Building that index at zero rows costs nothing and works over
  either endpoint, but any later rebuild of `ix_repo_chunks_embedding_hnsw` wants a raised
  `maintenance_work_mem`, which the pooled endpoint cannot do.
- These services run one instance each. The pooled endpoint solves a connection-count
  problem this deployment does not have yet.

If connection counts do become a problem later, move the running services to the pooled
string and keep migrating by hand over the direct one. Do not do both from one variable.

**Confirm:** you can tell the two apart at a glance. The direct one has no `-pooler`.

### Step 3. You: run the migrations, from your laptop, over the direct string

Migrations run from your laptop, now and every time afterwards. Render's
`preDeployCommand`, which is where migrations would normally live, is available only on
paid web services, and both APIs here are on the free instance type. So there is no
automatic migration step: **after any deploy that adds a migration, come back and run
this by hand.** It is the one manual chore the free tier costs you, and forgetting it
shows up as a 500 on whichever route touches the new column.

> **Read this before running anything.** `services/identity/.env` and
> `services/pulse/.env` already contain live Neon connection strings, and Pulse's is the
> production database. Alembic reads `app.config`, which reads that `.env` file when no
> environment variable overrides it. Running `alembic upgrade head` in one of those
> directories without an explicit `DATABASE_URL` in front of it will migrate whatever
> that file points at. Always put the variable on the command line.

From the repository root, with the project virtualenv (it carries all three services'
dependencies):

```bash
cd services/identity && DATABASE_URL='<neon identity direct>' ../../.venv/bin/alembic upgrade head && cd ../..
cd services/pulse    && DATABASE_URL='<neon pulse direct>'    ../../.venv/bin/alembic upgrade head && cd ../..
```

Each service has its own alembic tree and migrates only its own database, so nothing
races and order does not matter.

**Confirm:** run `alembic current` the same way in each directory. You should see:

| Service | expected head |
|---|---|
| identity | `0012_department_name_unique` |
| pulse | `0015_indexed_repo_owner_dept_ids` |

If Pulse stops on `0008_repo_index` with a permissions error about `CREATE EXTENSION`,
you are on a Neon role that may not install extensions. Neon ships pgvector on every plan
and the provisioned owner role can install it, so this normally means you are connected
as the wrong role.

---

# Part 2: Render

### Step 4. You: generate the identity signing keypair

Identity signs tokens with RS256 and reads three **file paths**, so the keys arrive as
Render Secret Files rather than environment variables.

```bash
./scripts/generate-identity-keys.sh
```

That writes `services/identity/keys/private.pem` and `public.pem`. `*.pem` is gitignored
and has never been committed. Keep it that way.

**Confirm:** `openssl rsa -in services/identity/keys/private.pem -noout -check` prints
`RSA key ok`.

### Step 5. You: create the Blueprint

In Render, New > Blueprint, point it at the repository, and let it read `render.yaml`.
It will create three services and one Key Value instance: two free web services, one
starter worker, one free Key Value. There is no `databases:` block, because Postgres is
on Neon.

Only one free Key Value instance is allowed per Render workspace. If you already have
one, this Blueprint will not create a second; move the old one off free or delete it.

Render will prompt for every `sync: false` variable. Fill in every one from
`docs/deploy-env-matrix.md`. The URL-shaped ones are not knowable yet: put a placeholder
such as `https://placeholder.invalid` in `CORS_ORIGINS`, `FRONTEND_URL`,
`GITHUB_OAUTH_REDIRECT_URI`, `IDENTITY_JWKS_URL` and `IDENTITY_API_URL`, and come back at
Step 8 and Step 13. Everything else, set properly now:

- both `DATABASE_URL`s, the direct strings from Step 2,
- `BREVO_API_KEY`, `EMAIL_FROM`, `SIGNUP_ALLOWED_DOMAINS`,
- `LLM_API_KEY`, optionally `ANTHROPIC_API_KEY`,
- `GITHUB_TOKEN_ENC_KEY`: generate it once with
  `python -c "import secrets; print(secrets.token_urlsafe(32))"` and keep a copy
  somewhere you will not lose it. Changing this value later makes every stored GitHub
  connection unreadable and everybody has to reconnect.
- `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `GITHUB_REPOS`: placeholders for now, the
  OAuth app does not exist until Step 12.

`PULSE_CLIENT_SECRET` is not prompted for. Render generates it on identity, and Pulse
reads it back through a service reference, so no human ever handles it. There is no
`FORGE_CLIENT_SECRET` at all: identity only seeds a service client when its secret is
non-empty, so leaving it unset means no forge client row exists rather than a live
credential for a service nobody deployed.

**Confirm:** all four resources appear in the dashboard. They will not all be healthy
yet.

### Step 6. You: upload the signing keys as Secret Files

On `crescent-identity` only, Environment > Secret Files, add two:

| Filename | Contents |
|---|---|
| `jwt-private.key` | the whole of `services/identity/keys/private.pem`, `-----BEGIN` line included |
| `jwt-public.key` | the whole of `public.pem` |

The `.key` extension is not cosmetic. Render serves secret files from `/etc/secrets` flat,
a filename cannot contain a directory, and `JWT_RETIRED_PUBLIC_KEYS_DIR` is therefore
`/etc/secrets` itself. Identity globs `*.pem` in that directory and publishes everything
it finds to the JWKS document. Upload a private key named `*.pem` and you publish your
signing key.

Regenerating this pair invalidates every access and refresh token in existence and signs
everybody out of every product at once. To change keys without that,
`docs/runbook-identity-key-rotation.md` and `scripts/rotate-identity-keys.sh` publish the
new key alongside the retired one so existing tokens verify until they expire.

**Confirm:** Step 7 is the confirmation.

### Step 7. Render: identity deploys

Watch the deploy log. There is no pre-deploy step, so it goes build, then start. Step 3
already applied the schema.

The first request after this may take about a minute: a free web service that has been
idle 15 minutes is asleep, and Render shows a loading page while it wakes. A `curl` that
seems to hang for a minute and then answers is the service waking, not a fault.

**Confirm:** two things, both from your own machine.

```bash
curl -s <identity-api>/health
# {"status":"ok","db":"reachable"}

curl -s <identity-api>/.well-known/jwks.json
# {"keys":[{...,"kty":"RSA",...}]}   one key, and no "d" field anywhere in it
```

A `503 degraded` means `DATABASE_URL`. An empty `keys` array means the public key file
did not mount. A `"d"` field in the JWKS means you uploaded a private key with a `.pem`
extension: delete it, rotate the keypair, and start Step 4 again.

Write `<identity-api>` on your note.

### Step 8. Render: Pulse deploys

Same shape. Once it is up, go back and set the two identity-trust variables on
`crescent-pulse` and `crescent-pulse-worker`:

- `IDENTITY_JWKS_URL` = `<identity-api>/.well-known/jwks.json`
- `IDENTITY_API_URL` = `<identity-api>`

Both are identity's **public** URL. A free web service cannot receive private network
traffic, so a private-network name would not work here even if you wanted one.

Saving these triggers a redeploy. Let it finish.

**Confirm:**

```bash
curl -s <pulse-api>/health   # {"status":"ok","db":"reachable"}
curl -s -o /dev/null -w '%{http_code}\n' <pulse-api>/reports   # 401, not 500
```

A 401 from an authenticated route is the right answer: it proves the service is up and
rejecting an unauthenticated caller rather than failing to verify tokens at all. A 503
there means it cannot fetch the JWKS, which on free can also mean identity was asleep and
the fetch timed out. Retry once before you go looking for a fault.

Write `<pulse-api>` on your note.

### Step 9. Render: the worker

There is one worker process and it carries the scheduler inside it:

```
celery -A app.celery_app.celery worker --beat --loglevel=info
```

`--beat` is what used to be a second Render service. `app/celery_app.py` defines
`beat_schedule` in code, not in a separate beat module, so the same process reads the same
schedule the standalone scheduler read. This is only safe because there is exactly one
worker: run two with `--beat` and both schedulers queue the same task. If Pulse ever
scales past one worker, split beat back into its own service **before** adding the second.

**Confirm:** the worker log lists two registered tasks under `[tasks]`,
`app.tasks.sync_all_repos` and `app.tasks.index_repo`, then shows `beat: Starting...` from
`INFO/Beat` and ends with `celery@... ready.`, all in the one log, because it is one
process.

Expect a `Scheduler: Sending due task daily-github-sync` line within a second or two of
startup, and a sync to run there and then. Celery beat keeps its last-run marker in a
local file, Render's filesystem is ephemeral, so every deploy and every restart starts
with no marker and treats the daily job as due. This is not new: the standalone beat
service did the same thing. It costs one extra GitHub sync per deploy, and a sync is
incremental, so the cost is API calls rather than duplicated data.

A worker that loops on connection errors has the wrong `REDIS_URL`; that one is wired by
the Blueprint, so it usually means the Key Value instance is in a different region from
the services.

---

# Part 3: Vercel

### Step 10. You: create two projects

One project per front end, for identity and Pulse. Forge's front end is not deployed;
there is no Forge API for it to talk to. The Root Directory setting is the part that
decides whether this works at all.

Both apps do `extends: ["../../../packages/ui"]`. That layer lives outside each app's
directory, so a build that can only see the app directory fails at config load before it
compiles a single line.

For each project, in Settings > Build and Deployment:

| Setting | Value |
|---|---|
| Root Directory | `services/identity/frontend`, `services/pulse/frontend` |
| **Include source files outside of the Root Directory in the Build Step** | **on** |
| Framework Preset | Nuxt.js |
| Install Command | leave to `vercel.json` |
| Build Command | leave to `vercel.json` |
| Output Directory | leave to `vercel.json` |

Both halves matter. The Root Directory has to be the app, because that is the only place
Vercel reads `vercel.json` from, and each app's `vercel.json` carries the install and
build commands. The checkbox has to be on, because that is what uploads `packages/ui`.

If the checkbox is off, the install command fails immediately with a message telling you
to turn it on. That guard is in `vercel.json` on purpose: the alternative failure is an
unresolved-import error deep in a Nuxt stack trace.

Do not set a `NITRO_PRESET`. Nitro detects Vercel on its own and produces
`.vercel/output` with a fallback function that serves the app shell for any path. That
fallback is what makes deep links work. Forcing the static preset instead produces an
output with no catch-all route, and every URL except the handful Nuxt could crawl at
build time returns a 404: `/reports/<id>` and the rest all break, which is easy to miss
because the home page looks fine.

**Confirm:** nothing yet. Set the variables first, or the first build bakes in localhost.

### Step 11. You: set the environment variables, then deploy

Take the values from `docs/deploy-env-matrix.md`, section by section. Set them under the
Production environment.

Two things to be careful about:

- **`NUXT_PUBLIC_PULSE_URL` means different things in different projects.** In Pulse's
  project it is Pulse's **API** on Render. In identity's project it is Pulse's **site**
  on Vercel, and identity reads the API through `NUXT_PUBLIC_PULSE_API_URL` instead.
  Swapping them produces no error at build and no error at boot; screens just load
  forever.
- **Leave `NUXT_PUBLIC_FORGE_URL` and `NUXT_PUBLIC_FORGE_API_URL` unset on identity.**
  With no Forge deployed they would point at nothing. Identity's product picker drops a
  tile's stat line rather than showing a figure it cannot stand behind.
- **These values are baked into the JavaScript bundle at build time.** Editing one in the
  dashboard changes nothing until you redeploy. There is no restart that picks it up.
  Every URL correction later in this runbook means a redeploy of the affected project.

Then deploy each project.

**Confirm:** for each, open the deployment and check the build log ends in
`Build complete`, then open the site. You should get the app's login screen, styled, not
an unstyled page and not a 404.

If the build failed on `NUXT_PUBLIC_SSO_RETURN_ALLOWLIST`, read the error: the validator
names the offending entry and the reason. A bare origin, a wildcard, plain `http`, a
trailing query string and embedded credentials are all refused, deliberately, at build
time rather than in a browser.

Write `<identity-web>` and `<pulse-web>` on your note.

### Step 12. You: fill in CORS on both Render web services

Now that the Vercel URLs exist, go back to Render:

| Service | `CORS_ORIGINS` |
|---|---|
| `crescent-identity` | `<identity-web>,<pulse-web>` |
| `crescent-pulse` | `<pulse-web>,<identity-web>` |

Scheme and host only. No trailing slash, no path.

`<identity-web>` is on both because identity's product picker reads live report counts
straight from Pulse's API. Leaving it off Pulse does not produce an error page; the picker
quietly drops that stat line rather than showing a zero it cannot stand behind.

While you are there, set `FRONTEND_URL`:

| Service | `FRONTEND_URL` |
|---|---|
| `crescent-identity` | `<identity-web>` |
| `crescent-pulse` and `crescent-pulse-worker` | `<pulse-web>` |

Identity's is its own front end, not a product's: `/confirm-email-change` and `/account`
exist only there. Pulse's config default is port 3000, which is Forge in development, so
a wrong value here looks plausible and sends every report link to the wrong product.

Saving these redeploys the services. Let them finish.

**Confirm:** a preflight from the browser's point of view.

```bash
curl -s -o /dev/null -w '%{http_code} %{header_json}' \
  -X OPTIONS <identity-api>/auth/login \
  -H "Origin: <pulse-web>" \
  -H "Access-Control-Request-Method: POST" | head -c 400
```

You want a 200 and an `access-control-allow-origin` header echoing `<pulse-web>`. No such
header means the origin is not on the list, usually a trailing slash.

---

# Part 4: GitHub

### Step 13. You: create the OAuth app and wire the callback back

GitHub, Settings > Developer settings > OAuth Apps > New OAuth App.

| Field | Value |
|---|---|
| Homepage URL | `<pulse-web>` |
| Authorization callback URL | `<pulse-api>/github/oauth/callback` |

The callback points at the **API on Render**, not the front end on Vercel, because only
the API holds the client secret. This is the field people get wrong.

On the free instance type, GitHub's redirect back to `<pulse-api>` can be the request that
wakes a sleeping Pulse. GitHub itself does not time out on that, but the browser sits on
Render's loading page for about a minute before the callback is handled. Slow once, then
normal for the next 15 minutes.

Generate a client secret, then set on both `crescent-pulse` and `crescent-pulse-worker`:

- `GITHUB_CLIENT_ID`
- `GITHUB_CLIENT_SECRET`
- `GITHUB_OAUTH_REDIRECT_URI` = `<pulse-api>/github/oauth/callback`, character for
  character identical to what you typed into GitHub
- `GITHUB_REPOS` = the repositories to sync, comma separated as `owner/name`. This
  allowlist is the only way repositories are discovered; nothing is picked up
  automatically.

**Confirm:** Step 17 exercises this end to end.

---

# Part 5: Prove it works

Health checks prove the processes started. These prove the deployment does its job.
Do them in order.

### Step 14. Sign in

Open `<identity-web>`. Create the first account through signup, using an address on a
domain in `SIGNUP_ALLOWED_DOMAINS`.

**Confirm:** you land signed in, not back on the login screen. Then reload the page: you
should stay signed in. A reload that logs you out means the token was never stored, which
means `NUXT_PUBLIC_IDENTITY_URL` is wrong or CORS is refusing the call. Check the browser
console, not the server logs; both failures are browser-side.

### Step 15. Cross-product sign-in

Open the product picker at `<identity-web>/products`.

**Confirm, in order:**

1. The Pulse tile shows a live count. A blank count means `<identity-web>` is missing
   from Pulse's `CORS_ORIGINS` (Step 12), or `NUXT_PUBLIC_PULSE_API_URL` is wrong
   (Step 11), or Pulse is simply asleep. Reload once before you debug: a free service that
   was idle answers the second request.
2. Click through to Pulse. You should arrive **already signed in**. Landing on Pulse's own
   login page means the handoff was refused: check `NUXT_PUBLIC_SSO_AUTHORIZE_URL` and
   both ends of the return allowlist. A screen naming a refusal reason is the guard
   working correctly, so read the reason it gives.

### Step 16. Generate something with AI

In Pulse, generate a weekly report.

**Confirm:** prose comes back, not a 502 and not a placeholder. Then check
`GET /settings/credentials/budgets` or the usage surface shows tokens spent: that proves
the call reached the provider and the ledger recorded it, rather than a cached or
stubbed answer. A 502 here is `LLM_API_KEY`. A 429 naming a reset time is the daily
budget doing its job, not a fault.

If the report generated but no notification email arrived, that is Brevo: check
`EMAIL_FROM` is a sender Brevo has verified.

### Step 17. Connect GitHub and index a repository

In Pulse, connect your GitHub account.

**Confirm, in order:**

1. GitHub's consent screen names your OAuth app and asks for `read:user` and `repo`. A
   "redirect_uri mismatch" error is Step 13.
2. After approving, you land back on `<pulse-web>` with a success indicator. Landing on
   localhost is `FRONTEND_URL` on Pulse.
3. Start an index on one repository from `GITHUB_REPOS`. Watch
   `crescent-pulse-worker`'s log: it should pick up `app.tasks.index_repo` and commit
   batches. A run that never starts means the worker cannot reach Redis, or the queued job
   was lost to a Key Value restart (see the free tier section); a run that fails
   immediately on embeddings means `LLM_API_KEY` is missing on the **worker**, which is a
   separate service from the API.
4. When it finishes, ask the chat assistant a question about that repository. An answer
   with citations naming real files is the proof: it means the embeddings were written,
   the vector index is queryable, and pgvector installed correctly during Step 3.

Only after Step 17 passes is the deployment actually working.

---

# What will not work, and why

These are known and expected. None of them is a fault to debug.

### The theme will not follow you between products

The light/dark choice is kept in a cookie so it follows a person from one product to the
next. A cookie is scoped by host, and `NUXT_PUBLIC_THEME_COOKIE_DOMAIN` exists to widen
it to a shared parent domain.

That cannot be made to work here. `vercel.app` and `onrender.com` are both on the Public
Suffix List, which is precisely the list of domains browsers refuse to let a site set a
cookie on, so that one site on `vercel.app` cannot write cookies read by another. Setting
`NUXT_PUBLIC_THEME_COOKIE_DOMAIN=.vercel.app` does not partially work; the browser drops
the cookie entirely and the theme stops persisting even within one product.

Leave it unset. Each product keeps its own copy of the choice, so switching to dark in
Pulse leaves identity light. It fixes itself the day the products sit on subdomains of
one custom domain, at which point set it to that parent domain on both projects and
redeploy.

Sessions are unaffected. Tokens live in localStorage and are handed between products by
the SSO redirect, which does not depend on a shared origin.

### Preview deployments cannot sign in

Every Vercel preview gets a unique URL. That URL is on no `CORS_ORIGINS` list and on no
SSO return allowlist, so identity refuses the handoff and the API refuses the call.
Previews are useful for looking at layout and nothing else. Do not add a wildcard to
work around this: the allowlist compares exact origins, a wildcard matches nothing, and
the validator rejects one at build time for exactly that reason.

### One GitHub OAuth app means one callback

The callback is registered against `<pulse-api>`, which is stable, so this does not
affect previews of the front end. But after the OAuth exchange Pulse sends the browser to
`FRONTEND_URL`, which is production. Connecting GitHub from a preview deployment lands
you on the production site. Expected.

### Everyone connected to GitHub before this release must reconnect

`GITHUB_OAUTH_SCOPES` is `read:user,repo`. It used to be `read:user`, which grants no
access to repository contents at all. An OAuth token carries the scopes it was granted
and can never gain more, so widening the setting changes nothing for an existing
connection.

Until such a person reconnects: indexing a private repository ends in an error asking
them to reconnect, an ad-hoc report on one is refused with the same message, and a sync
fails with a run whose detail says the same. `GET /chat/repos/github-status` returns
`reconnect_required: true` for exactly these accounts and `POST /github/reconnect`
returns a fresh authorize URL. The old connection stays in place until they approve, so
opening the consent screen and closing it leaves them where they were. Public
repositories were never affected.

### What the free tier costs you

Everything except the worker is on Render's free instance type, which is a real choice
with real costs. Nothing here is a fault to debug.

**The APIs sleep.** Render spins a free web service down after 15 minutes with no inbound
traffic, and waking it takes about a minute, during which Render shows a loading page.
Consequences, in the order you will meet them:

- The first sign-in after a quiet spell waits on identity waking. Identity is the front
  door, so that minute is charged to whoever arrives first.
- Waking is per service. Signing in wakes identity; the first call into Pulse afterwards
  can pay the minute again.
- A product's screens may show a loading state for that minute rather than an error,
  because the request is genuinely still open.
- Token verification on Pulse fetches identity's JWKS. If identity is asleep when that
  fetch happens, Pulse can answer 503 on authenticated routes until the retry succeeds.
  Retry once before assuming `IDENTITY_JWKS_URL` is wrong.
- The GitHub OAuth callback lands on `<pulse-api>`, so connecting an account can be the
  request that wakes Pulse. GitHub tolerates the delay; you sit on a loading page.
- The health checks in this runbook are affected the same way. A `curl` that appears to
  hang for a minute and then answers is the service waking.

**Free instance hours are shared and finite.** Render grants 750 free instance-hours per
workspace per calendar month, and a spun-down service consumes none. Two services awake
around the clock would need 1,440, so this only fits because they sleep. Burn the 750 and
Render suspends every free web service in the workspace until the month rolls over. Watch
it on the Billing page's Monthly Included Usage.

**Migrations are manual.** `preDeployCommand` is available only on paid web services, so
`render.yaml` does not set one. Every deploy that adds a migration needs Step 3 run again
by hand. Nothing warns you; the symptom is a 500 on the route that touches the new column.

**The Key Value instance forgets.** A free Key Value instance is 25 MB, 50 connections,
and never writes to disk, and Render may restart it at any time. Two things live in it:

- Rate-limit counters. Losing them resets everyone's window. Harmless.
- Celery's queue and results. Losing them drops whatever was queued and not yet running.
  A daily sync lost this way is picked up by the next day's run; an index a person started
  from the UI is simply gone and has to be started again. The task that was already
  executing in the worker is unaffected, since it is running in the worker's memory.

Only one free Key Value instance is allowed per workspace, and upgrading it to a paid plan
later loses its contents during the upgrade.

**Other free-tier limits that happen not to bite here.** Free services have an ephemeral
filesystem (nothing is stored on disk that matters), cannot use SSH or one-off jobs
(migrations are run from a laptop instead), cannot receive private network traffic (every
cross-service URL here is public by design), and cannot make outbound connections on ports
25, 465 and 587. That last one would kill SMTP; email goes through Brevo's HTTPS API, so
it does not apply.

**What is not free.** Background workers have no free instance type on Render at all, so
`crescent-pulse-worker` is `starter` at $7/month. That is the entire Render bill.

If the Neon databases are on a free plan they also scale to zero, which adds a cold start
to the first query after an idle period. A `/health` check that answers `503 degraded`
once and then `ok` on a retry is that, not a fault.

### Forge is not deployed

Forge's own pages say it is not built yet, so it has no Render service and no Vercel
project. Identity's product picker has no Forge tile to fill. "Adding Forge back" below is
the procedure for when there is something to deploy.

### The repo index is memory-hungry on a starter worker

Indexing reads, chunks and embeds up to `INDEX_MAX_FILES` files in batches of
`INDEX_BATCH_FILES`, fetching `INDEX_FETCH_CONCURRENCY` blobs at once. On a `starter`
worker a large repository can be tight. A run that dies loses at most one batch and can
be retried. If it happens repeatedly, lower `INDEX_BATCH_FILES` and
`INDEX_FETCH_CONCURRENCY` before reaching for a bigger instance.

### A change to the front end's URLs is a rebuild, never a restart

`NUXT_PUBLIC_*` values are compiled into the JavaScript bundle. Editing one in Vercel's
dashboard has no effect until that project is redeployed. This catches people at Step 12
in particular, when the Render URLs turn out to be different from what they guessed.

---

# When something is wrong

| Symptom | Almost always |
|---|---|
| A request hangs about a minute, then works | a free web service waking from sleep. Not a fault |
| Every free web service is suddenly suspended | the workspace burned its 750 free instance-hours for the month |
| A 500 on one route right after a deploy | a migration that was never run. Step 3 is manual on the free tier |
| A queued sync or index never starts | the free Key Value instance restarted and dropped the queue. Start it again |
| `/health` returns `503 degraded` | `DATABASE_URL`, or a Neon database still waking |
| Every authenticated route on Pulse returns 503 | `IDENTITY_JWKS_URL`, or identity was asleep when the JWKS fetch went out. Retry once first |
| Every token rejected everywhere | `JWT_ISSUER` differs between identity and a product, or the keypair was regenerated |
| Login works, reload signs you out | CORS, or `NUXT_PUBLIC_IDENTITY_URL` |
| Product picker renders with counts missing | `<identity-web>` missing from Pulse's `CORS_ORIGINS`, or Pulse asleep |
| Opening a product lands on its own login page | `NUXT_PUBLIC_SSO_AUTHORIZE_URL`, or the return allowlist on either end |
| Screens load forever with no error | `NUXT_PUBLIC_PULSE_URL` set to the site instead of the API |
| Emails link to localhost | `FRONTEND_URL` on the service that sent it |
| GitHub says redirect_uri mismatch | `GITHUB_OAUTH_REDIRECT_URI` differs from the OAuth app by a character |
| Report generation 502s | `LLM_API_KEY` on the web service |
| Indexing fails immediately | `LLM_API_KEY` on the **worker**, which is configured separately |
| Vercel build fails on the shared layer | "Include source files outside of the Root Directory" is off |
| Deep links 404 but the home page works | a `NITRO_PRESET` was set to a static preset |

---

# Adding Forge back

Forge was left out of the deployment, not deleted. Its code, its migrations and its Neon
database are all still here, and its database is already at head
(`0002_sample_name_unique`), so nothing has to be rebuilt. Do this when Forge is worth an
instance.

It costs $7/month if you put it on `starter`, or $0 on `free` with the same sleep,
instance-hour and manual-migration terms as the other two web services.

**1. Render: add the service block.** In `render.yaml`, alongside the other services:

```yaml
  - type: web
    name: crescent-forge
    runtime: docker
    region: virginia
    plan: free
    dockerContext: .
    dockerfilePath: services/forge/Dockerfile
    healthCheckPath: /health
    autoDeployTrigger: commit
    buildFilter:
      paths:
        - services/forge/**
        - packages/core/**
      ignoredPaths:
        - services/forge/frontend/**
    envVars:
      - key: DATABASE_URL
        sync: false
      - key: REDIS_URL
        fromService:
          type: keyvalue
          name: crescent-keyvalue
          property: connectionString
      - key: IDENTITY_JWKS_URL
        sync: false
      - key: IDENTITY_API_URL
        sync: false
      - key: JWT_ISSUER
        value: cyphercrescent-identity
      - key: FORGE_SERVICE_CLIENT_ID
        value: forge
      - key: FORGE_SERVICE_CLIENT_SECRET
        fromService:
          type: web
          name: crescent-identity
          envVarKey: FORGE_CLIENT_SECRET
      - key: CORS_ORIGINS
        sync: false
      - key: TRUST_PROXY_HEADERS
        value: "true"
      - key: TRUSTED_PROXY_COUNT
        value: "1"
      - key: RATE_LIMIT_ENABLED
        value: "true"
      - key: MAX_UPLOAD_MB
        value: "5"
      - key: PORT
        value: "8000"
```

Add `plan: starter` and `preDeployCommand: alembic upgrade head` instead if you want
Forge's migrations to run themselves.

**2. Render: put the two Forge client variables back on identity.** They are absent on
purpose today. Under `crescent-identity`'s `envVars`:

```yaml
      - key: FORGE_CLIENT_ID
        value: forge
      - key: FORGE_CLIENT_SECRET
        generateValue: true
```

Identity seeds service clients at **startup**, so restart `crescent-identity` after this
or `POST /oauth/token` keeps returning 401 for Forge with nothing in the logs explaining
why. The block above must be added before Forge's `fromService` reference to
`FORGE_CLIENT_SECRET` can resolve.

**3. Neon.** Nothing to do. The `forge` database exists and is migrated. Confirm with
`cd services/forge && DATABASE_URL='<neon forge direct>' ../../.venv/bin/alembic current`,
which should print `0002_sample_name_unique`.

**4. Vercel: create the Forge front-end project.** Root Directory
`services/forge/frontend`, "Include source files outside of the Root Directory" on, same
as Step 10. Set `NUXT_PUBLIC_IDENTITY_URL`, `NUXT_PUBLIC_FORGE_URL` (= `<forge-api>`),
`NUXT_PUBLIC_IDENTITY_WEB_URL`, `NUXT_PUBLIC_SSO_AUTHORIZE_URL` and
`NUXT_PUBLIC_SSO_RETURN_ALLOWLIST` (= `<forge-web>/auth/callback`).

**5. Fix the four cross-references, or Forge deploys and cannot be signed into.** This is
the part that is easy to half-do:

| Where | Change |
|---|---|
| `crescent-identity` `CORS_ORIGINS` | add `<forge-web>` |
| `crescent-forge` `CORS_ORIGINS` | `<forge-web>,<identity-web>` |
| identity's `NUXT_PUBLIC_SSO_RETURN_ALLOWLIST` | add `<forge-web>/auth/callback` |
| identity's `NUXT_PUBLIC_FORGE_URL` / `NUXT_PUBLIC_FORGE_API_URL` | `<forge-web>` / `<forge-api>` |

The two Vercel variables are baked in at build time, so identity's project needs a
redeploy, not a restart.

**6. Confirm**, in this order: `curl -s <forge-api>/health` returns
`{"status":"ok","db":"reachable"}`; `curl -s -o /dev/null -w '%{http_code}\n'
<forge-api>/datasets` returns 401, not 500; identity's product picker shows a Forge tile
with a live dataset count; clicking it lands you in Forge already signed in.

Then update `docs/deploy-env-matrix.md`, which currently documents two Render services and
two Vercel projects.
