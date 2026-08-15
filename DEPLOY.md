# Deploying Meridian

Three Nuxt apps on Vercel, three FastAPI services plus two Celery processes on
Render, with managed Postgres and Redis.

## Read this first

`render.yaml` has never been applied to Render. It is written from Render's
Blueprint schema, not from a deploy that worked, so treat it as a starting point
that will need adjusting on first contact rather than a tested artefact.

What *has* been verified, locally:

- The whole stack tears down and rebuilds with `docker compose up --build` and
  all six ports answer.
- Every URL that used to be hardcoded to localhost is now an environment
  variable with the localhost value as its default, so local development is
  unchanged and a deployment overrides it.
- The SSO return allowlist validator refuses a bare origin at build time and
  accepts a proper callback URL. Observed, not inferred.

Everything about Render's own behaviour — plan limits, how many databases an
instance gives you, whether the Blueprint schema has drifted — comes from their
documentation and should be checked against what you actually see.

## What runs where

| Piece | Where | Local equivalent |
|---|---|---|
| `identity-web` | Vercel | `identity-web` container, :3002 |
| `pulse-web` | Vercel | `pulse-web` container, :3001 |
| `forge-web` | Vercel | `forge-web` container, :3000 |
| `crescent-identity` | Render web service | `identity` container, :8001 |
| `crescent-pulse` | Render web service | `pulse` container, :8002 |
| `crescent-forge` | Render web service | `forge` container, :8003 |
| `crescent-pulse-worker` | Render worker | `pulse-worker` container |
| `crescent-pulse-beat` | Render worker | `pulse-beat` container |
| `crescent-keyvalue` | Render Key Value | `redis` container |
| three Postgres instances | Render | one `postgres` container, three databases |

## Vercel

Each app has a `vercel.json`, but the important setting is not in it.

All three apps do `extends: ["../../../packages/ui"]`. That layer lives outside
each app's directory, so a build rooted at the app directory cannot see it and
fails. In each Vercel project set:

- **Root Directory**: the repository root, *not* `services/<name>/frontend`.
  Untick "Include source files outside of the Root Directory" only if Vercel
  offers it — you need those files.
- **Build Command**: `npm --prefix packages/ui ci && npm --prefix services/<name>/frontend ci && npm --prefix services/<name>/frontend run build`
- **Output Directory**: `services/<name>/frontend/.output`
- **Framework Preset**: Nuxt

This is the same trap the Docker images hit: the build context has to be the
repo root, or the shared layer is invisible.

`vercel.json` sets an `ignoreCommand` so a project only rebuilds when its own
app or `packages/ui` changed. A change to one product does not redeploy the
other two.

### Vercel environment variables

Set these per project. Every one has a localhost default in `nuxt.config.ts`,
so a missing value silently points production at localhost and the app appears
to work until something tries to reach an API.

| Variable | Set on | What breaks if wrong |
|---|---|---|
| `NUXT_PUBLIC_IDENTITY_URL` | all three | Sign-in, `/me`, everything auth |
| `NUXT_PUBLIC_IDENTITY_WEB_URL` | all three | "All products" and account links go nowhere |
| `NUXT_PUBLIC_SSO_AUTHORIZE_URL` | all three | Cross-product sign-in fails; each product asks for its own login |
| `NUXT_PUBLIC_SSO_RETURN_ALLOWLIST` | all three | See the allowlist section. Getting this wrong is the worst case in this document |
| `NUXT_PUBLIC_PULSE_URL` | identity, pulse | Pulse API calls fail; picker figures blank |
| `NUXT_PUBLIC_FORGE_URL` | identity, forge | Forge API calls fail |
| `NUXT_PUBLIC_PULSE_API_URL` | identity | Picker cannot read Pulse's figures |
| `NUXT_PUBLIC_FORGE_API_URL` | identity | Picker cannot read Forge's figures |

Do **not** set `NUXT_PUBLIC_AUTH_STORAGE_PREFIX`. It namespaces each product's
tokens in the browser, and changing it signs out every existing session.

## The SSO return allowlist

This is the open-redirect guard, and it is the single value where a mistake
hands a live access token to whoever asked for one.

The handoff works by identity redirecting back to a product with a short-lived
access token in the URL fragment. The allowlist is the list of addresses a token
may be delivered to. Anything on it is somewhere a token can land.

`checkedAllowlist` in each `nuxt.config.ts` validates the value at build time
and fails the build rather than shipping a bad list. It rejects:

| Rejected | Why |
|---|---|
| A wildcard (`*`) | Matches nothing, because origins are compared exactly. Someone writing one believed it widened the list, so sign-in is broken and looks configured |
| A bare origin (`https://pulse.example.com`) | Allows **every path on that host** to receive a token |
| Plain `http://` (except localhost) | The token travels in the URL fragment; plain http puts it on the wire |
| Embedded credentials (`https://a@b.com/x`) | Reads as one host, resolves to another |
| A query or fragment | Only origin and path are matched, so anything after them is a false promise |

A correct value names the full callback path on each product, comma separated:

```
https://pulse.meridian.example.com/auth/callback,https://forge.meridian.example.com/auth/callback
```

Identity holds the list of all three because identity is the end that hands
tokens out. Each product needs only its own callback, since a product only ever
asks for a handoff to itself. A wider list there buys nothing and widens the
surface.

The validator only runs when the variable is set, so local development keeps its
localhost default untouched.

## Render

`render.yaml` defines five services, three Postgres instances and one Key Value
instance. Create a Blueprint from it and Render will provision them together.

Values marked below as **dashboard** are secrets. They are declared with
`sync: false` so they are never in the repository, and Render will ask for each
one when the Blueprint is created.

Two secrets are handled for you: `PULSE_CLIENT_SECRET` and `FORGE_CLIENT_SECRET`
are generated on identity, and the products read them through service references
rather than you copying them by hand.

### crescent-identity

| Variable | Source | What breaks if wrong |
|---|---|---|
| `DATABASE_URL` | wired | Service will not start |
| `REDIS_URL` | wired | Rate limiting and revocation publishing degrade; service still runs |
| `JWT_PRIVATE_KEY_PATH` | `/etc/secrets/jwt-private.key` | No tokens can be signed |
| `JWT_PUBLIC_KEY_PATH` | `/etc/secrets/jwt-public.key` | JWKS empty; every product rejects every token |
| `JWT_RETIRED_PUBLIC_KEYS_DIR` | `/etc/secrets` | Old tokens rejected during a key rotation |
| `JWT_ISSUER` | `cyphercrescent-identity` | Products verify `iss`; a mismatch rejects every token. Pinned in all four services |
| `CORS_ORIGINS` | dashboard | Browsers block the frontends |
| `FRONTEND_URL` | dashboard | Invite and password-reset emails link to the wrong place |
| `SIGNUP_ALLOWED_DOMAINS` | dashboard | Either nobody can sign up, or anybody can |
| `BREVO_API_KEY`, `EMAIL_FROM` | dashboard | No email sends. Invites and resets stop working |
| `TRUST_PROXY_HEADERS`, `TRUSTED_PROXY_COUNT` | set | Wrong values read a spoofable end of `X-Forwarded-For` and rate limits key on the wrong address |

### crescent-pulse

| Variable | Source | What breaks if wrong |
|---|---|---|
| `DATABASE_URL`, `REDIS_URL` | wired | Will not start / Celery and revocation degrade |
| `IDENTITY_JWKS_URL` | dashboard | Cannot verify any token. Every authenticated route 503s |
| `IDENTITY_API_URL` | dashboard | Cannot resolve names or check revocation |
| `PULSE_SERVICE_CLIENT_ID` / `_SECRET` | set / wired | Service-to-service calls to identity fail |
| `CORS_ORIGINS`, `FRONTEND_URL` | dashboard | Browser blocked; OAuth returns land wrong |
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `GITHUB_OAUTH_REDIRECT_URI` | dashboard | GitHub connect fails |
| `GITHUB_TOKEN_ENC_KEY` | dashboard | Stored GitHub tokens cannot be read. **Changing it makes existing ones unreadable** |
| `GITHUB_REPOS` | dashboard | Sync has nothing to do |
| `LLM_API_KEY` | dashboard | Report drafting returns 502 |
| `BREVO_API_KEY`, `EMAIL_FROM` | dashboard | Report-ready notifications stop |

`crescent-pulse-worker` takes the same set minus the web-only entries.
`crescent-pulse-beat` needs only `DATABASE_URL`, `REDIS_URL` and `SYNC_HOUR_UTC`.

### crescent-forge

Same shape: `DATABASE_URL`, `REDIS_URL`, `IDENTITY_JWKS_URL`, `IDENTITY_API_URL`,
`JWT_ISSUER`, `FORGE_SERVICE_CLIENT_ID` / `_SECRET`, `CORS_ORIGINS`, and the two
proxy settings.

## Signing keys

Identity signs tokens with RS256. `config.py` reads three **file paths**, so the
keys arrive as Render Secret Files rather than environment variables:

- `jwt-private.key` mounted at `/etc/secrets/jwt-private.key`
- `jwt-public.key` mounted at `/etc/secrets/jwt-public.key`

Generate a pair with `scripts/generate-identity-keys.sh`, then paste each PEM
into a Secret File in the identity service's dashboard. `*.pem` is gitignored and
has never been committed, which is correct — do not change that.

**Regenerating these invalidates every access and refresh token in existence.**
Everyone is signed out of every product, immediately. To change keys without that
happening, follow `docs/runbook-identity-key-rotation.md`, which publishes the new
key alongside the retired one so tokens signed with the old key still verify until
they expire. `scripts/rotate-identity-keys.sh` implements it.

## Databases

`scripts/init-databases.sh` creates three databases locally: `identity`, `pulse`,
`forge`. `CLAUDE.md` requires each service to own its own, and no service may read
another's.

`render.yaml` follows that literally with **three separate Postgres instances**
(`crescent-identity-db`, `crescent-pulse-db`, `crescent-forge-db`). The rule stays
intact and each service can be moved or restored independently. It costs three
instances instead of one.

The cheaper alternative is one instance with three logical databases. Whether
Render's managed Postgres lets you create additional databases on an instance is
something to check against their current documentation — I have not verified it,
and if it does not, the choice is made for you.

Pulse's worker and beat share Pulse's database. That is one service's data
accessed by that service's own processes, which does not cross the rule.

## Migrations

Each web service runs `alembic upgrade head` as a `preDeployCommand`, so the
schema is current before new code serves traffic. Locally this happens in the
container command instead.

Each service migrates only its own database, so nothing races. If you move to a
shared instance, that stops being automatically true.

## Free tier

Render's free services sleep when idle and take time to wake.

Identity is the front door for all three products. If it sleeps, nobody can sign
in to anything, and every product's token verification fails until it is back.
`render.yaml` uses `starter` plans for that reason. Dropping to free is fine for a
demo you are driving yourself and bad for anything people rely on.

## First deploy, in order

1. **Provision Render from the Blueprint.** Fill in every dashboard secret. Add
   the two Secret Files for the signing keys.
2. **Check each API is up**: `/health` on all three should return
   `{"status":"ok","db":"reachable"}`. A failure here is almost always
   `DATABASE_URL` or a missing migration.
3. **Deploy the three Vercel projects.** Set the root directory and build command
   per the Vercel section, then the environment variables.
4. **Set `CORS_ORIGINS`** on all three Render services to the Vercel domains, and
   redeploy them. Note that Render reads `env_file` at container create, so a
   restart is not enough — recreate the service.
5. **Sign in** at the identity app. If this fails, check `IDENTITY_JWKS_URL` and
   that the public key file mounted.
6. **Open the product picker.** The Pulse and Forge figures come from
   cross-origin calls to those APIs. Blank figures with CORS errors in the console
   mean step 4 is wrong or has not been redeployed.
7. **Open Pulse from the picker.** Landing on Pulse's own login page instead of
   signed in means the SSO allowlist or `NUXT_PUBLIC_SSO_AUTHORIZE_URL` is wrong.
   A refused-handoff screen naming a reason is the validator working — read the
   reason.
8. **Send an invite** and check the link points at the identity app, not Forge.
   That is `FRONTEND_URL`.
