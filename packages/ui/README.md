# @crescent/ui (Vue 3 / Nuxt)

Shared frontend code for the Crescent products' Nuxt apps. Right now that means the
**login flow**: call identity's `/auth/login`, store the tokens, refresh once on a 401,
attach the `Authorization` header, and bounce unauthenticated routes to `/login`.

It ships as a **Nuxt layer** — a directory a product `extends`. Nuxt merges the layer's
`composables/`, `middleware/` and config into the product as if they were the product's
own files, so call sites stay `useAuth()` / `middleware: "auth"` with no imports and no
build step. Editing a file here lands in every product on the next dev reload.

## What's in it
| File | What it does |
| --- | --- |
| `composables/useTokenStorage.ts` | The **only** place tokens are read or written. Moving to httpOnly cookies is a change to this file and nothing else. |
| `composables/useAuth.ts` | `login`, `signup`, `refresh`, `fetchMe`, `logout`, `hydrate`, `isAuthenticated`. |
| `composables/useApiClient.ts` | `useApiClient(baseUrl)` → `request()`: bearer header, refresh-once-on-401 then retry, else clear the session and go to `/login`. |
| `middleware/auth.ts` | Route guard. Use as `definePageMeta({ middleware: "auth" })`. |
| `types/api.ts` | Identity's contract (`TokenPair`, `UserMeResponse`, `MembershipResponse`, …) plus `crescent_core`'s `Page<T>`. |

## The layer turns SSR off (`ssr: false`)
Tokens live in `localStorage`, which the server can't read, so the server can never tell
a signed-in visitor from a logged-out one. With SSR on it rendered the protected page for
everybody and the guard bounced logged-out visitors *after* the HTML had already shipped —
a flash of protected layout plus a Vue hydration mismatch. Client-only rendering removes
both. The cost: on a hard page load a signed-in user sees a blank page until the JS boots
(~70ms extra to first contentful paint on localhost, production build) instead of markup
straight from the server. In-app navigation is unchanged. Revisit when tokens move to
httpOnly cookies (`docs/backlog.md`).

## `authStoragePrefix` is required
It has no usable default. A product that omits it fails `nuxt dev` / `build` / `typecheck`
at startup with a message naming the key, because silently falling back to a shared default
would change the localStorage keys and sign out every existing session for that product.

## Ground rule
No product-specific components here. If it only makes sense in Pulse, it lives in
`services/pulse/frontend/`.

## Use it from a product

`nuxt.config.ts`:

```ts
export default defineNuxtConfig({
  extends: ["../../../packages/ui"],
  runtimeConfig: {
    public: {
      identityUrl: "http://localhost:8001",
      authStoragePrefix: "pulse", // namespaces this product's localStorage keys
      pulseUrl: "http://localhost:8002",
    },
  },
});
```

Then wrap the client once per backend the product talks to:

```ts
// composables/useApi.ts
export function useApi() {
  return useApiClient(useRuntimeConfig().public.pulseUrl);
}
```

Shared types import through the `@crescent/ui` alias the layer registers:

```ts
import type { Page, UserMeResponse } from "@crescent/ui/types/api";
```
