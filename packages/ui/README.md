# @crescent/ui (Vue 3 / Nuxt)

Shared frontend components + login helpers. Consumed by Pulse's and the ML
platform's Nuxt frontends.

**Not yet populated.** First real occupant will be the login flow (call
identity's `/auth/login`, store tokens, refresh on 401, attach `Authorization`
header) — so both products get the same behaviour for free.

## Ground rule
No product-specific components here. If it only makes sense in Pulse, it lives
in `services/pulse/frontend/`.
