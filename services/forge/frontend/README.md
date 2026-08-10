# Forge frontend

Nuxt 3 + TypeScript + Tailwind + TanStack Query. First frontend in the repo.

Working today: signup, login, dashboard, dataset upload with preview, and the
bundled sample datasets. `/learning` and `/canvas` are navigable descriptions of
what's coming in Week 6 — they're labelled as previews and nothing on them runs.

| Route                | What it is                                      |
| -------------------- | ----------------------------------------------- |
| `/`                  | Dashboard: counts, recent datasets, first-run onboarding |
| `/login`, `/signup`  | Identity-backed auth, no app shell               |
| `/datasets`          | Upload form + full dataset list                  |
| `/datasets/{id}`     | Metadata, row preview, delete                    |
| `/learning`          | The four learning paths (stubs)                  |
| `/canvas`            | Workflow builder layout sketch (stub)            |

## Run it

```bash
npm install
npm run dev        # http://localhost:3000
```

The dev server runs on port 3000, which identity and forge already allow via CORS.

### Build / preview

```bash
npm run build
npm run preview
```

## Backends must be running

This is a UI only — it talks to two backend services (run them in Docker):

- **identity** on `http://localhost:8001` — login, refresh, `/me`
- **forge** on `http://localhost:8003` — `/datasets`

Without them, the login form and datasets page have nothing to talk to.

## Env vars (override the API URLs)

Public runtime config, overridable with `NUXT_PUBLIC_*` env vars:

| Setting        | Env var                   | Default                 |
| -------------- | ------------------------- | ----------------------- |
| `identityUrl`  | `NUXT_PUBLIC_IDENTITY_URL`| `http://localhost:8001` |
| `forgeUrl`     | `NUXT_PUBLIC_FORGE_URL`   | `http://localhost:8003` |

Example:

```bash
NUXT_PUBLIC_IDENTITY_URL=http://localhost:9001 npm run dev
```

## How auth works

- `login()` POSTs to `{identityUrl}/auth/login`, stores the `access_token` +
  `refresh_token` in `localStorage`, and pulls `/me` to show who's signed in.
- The API client attaches `Authorization: Bearer <access_token>` to Forge calls.
  On a `401` it tries `refresh()` once (POST `{identityUrl}/auth/refresh` with
  `{ refresh_token }`) and retries; if refresh fails it clears tokens and
  redirects to `/login`.
- Route middleware (`auth`) redirects unauthenticated users to `/login` for
  protected pages.

- `signup()` POSTs to `{identityUrl}/auth/signup` and gets back the same token
  pair as login, so a new account is signed in immediately. It has no department
  until an admin places the user.

All of that lives in the shared Nuxt layer at `packages/ui`, which this app
`extends` — `useAuth`, `useTokenStorage`, `useApiClient` and the `auth`
middleware are auto-imported from there, not from this directory. Forge only
adds `composables/useApi.ts`, a one-liner that points the shared client at
`forgeUrl`.

Tokens are kept in `localStorage`, so all token access is client-side only.
`packages/ui/composables/useTokenStorage.ts` is the only file that touches
`localStorage` — moving tokens to cookies is a change to that one file, for
every product on the layer. The keys stay namespaced per product via
`authStoragePrefix` (`forge.access_token`, `forge.refresh_token`), so sessions
created before the move still work.
