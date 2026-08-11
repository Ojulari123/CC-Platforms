# Pulse frontend

Nuxt 3 + TypeScript + Tailwind + TanStack Query. Same stack as the Forge frontend;
auth comes from the shared `packages/ui` Nuxt layer rather than being copied.

| Route           | What it is                                                                   |
| --------------- | ---------------------------------------------------------------------------- |
| `/`             | Activity dashboard: counts + recent commits/PRs/reviews/issues, for you or a teammate |
| `/login`        | Identity-backed sign-in, no app shell. No sign-up; Pulse accounts come from identity |
| `/reports`      | Report list with the API's four filters, plus starting a new weekly report    |
| `/reports/{id}` | Summaries, status, edit/submit, approve/reject/request-changes, approval history, comments, PDF |
| `/review`       | The approver's inbox, with an inline decision panel                           |

`/reports/{id}` is the destination of the `{FRONTEND_URL}/reports/{id}` link in the
report-ready notification email.

## Run it

```bash
npm install
npm run dev        # http://localhost:3000
```

Port 3000 is the only origin identity and pulse allow through CORS, and the Forge
frontend uses the same port, so only one of the two can run at a time until
`CORS_ORIGINS` lists more than one origin.

### Build / preview

```bash
npm run build
npm run preview
npm run typecheck
```

## Backends must be running

This is a UI only. Run the stack in Docker:

- **identity** on `http://localhost:8001`: login, refresh, `/me`, `/departments`
- **pulse** on `http://localhost:8002`: `/activity`, `/reports`, `/github/*`

## Env vars (override the API URLs)

Public runtime config, overridable with `NUXT_PUBLIC_*` env vars:

| Setting              | Env var                       | Default                 |
| -------------------- | ----------------------------- | ----------------------- |
| `identityUrl`        | `NUXT_PUBLIC_IDENTITY_URL`    | `http://localhost:8001` |
| `pulseUrl`           | `NUXT_PUBLIC_PULSE_URL`       | `http://localhost:8002` |
| `authStoragePrefix`  | `NUXT_PUBLIC_AUTH_STORAGE_PREFIX` | `pulse`             |

## How auth works

It doesn't live here. `nuxt.config.ts` extends `../../../packages/ui`, a Nuxt layer
that provides `useAuth()`, `useApiClient()`, `useTokenStorage()` and the `auth` route
middleware. Behaviour: login stores the token pair, the API client attaches the bearer
header and on a 401 refreshes once and retries, and a failed refresh clears the session
and sends you to `/login`. See `packages/ui/README.md`.

The only auth code in this service is `composables/useApi.ts`, which points the shared
client at Pulse (and, for the department member list, at identity).

## Names, and when they're missing

Pulse resolves `author` / `actor` / `lead` / `user` objects from identity and sends
them alongside the raw ids. When identity can't be reached those objects come back
`null`, so every screen renders names through `personName()` in `utils/format.ts`,
which falls back to `Unknown user (#12)` rather than blank or `null`.

## Empty states

An engineer whose week looks empty gets told why, on `/`: GitHub not connected (with a
connect button), or connected but nothing synced for the period, with the last few sync
passes and their failure detail.
