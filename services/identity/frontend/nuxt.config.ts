export default defineNuxtConfig({
  // Login, token storage, the API client and the route guard come from the shared
  // Nuxt layer in packages/ui, so a token-handling fix is made once for all products.
  extends: ["../../../packages/ui"],
  compatibilityDate: "2025-01-01",
  devtools: { enabled: false },
  // Pinned so all three can run side by side: Forge 3000, Pulse 3001, this 3002.
  devServer: { port: 3002 },
  modules: ["@nuxtjs/tailwindcss"],
  typescript: { strict: true },
  runtimeConfig: {
    public: {
      identityUrl: "http://localhost:8001",
      // Its own namespace, so signing in here doesn't collide with a Pulse or Forge
      // session held in the same browser.
      authStoragePrefix: "identity",
      // This app's own front door, as an absolute URL. `identityUrl` is the API on :8001;
      // Pulse and Forge need this one to link back to the product picker and the account
      // screen, so it is named here and copied into their configs.
      identityWebUrl: "http://localhost:3002",
      // Cross-product links. Absolute because the three products are three origins;
      // the umbrella pages are the only place they are named.
      pulseUrl: "http://localhost:3001",
      forgeUrl: "http://localhost:3000",
      // Their APIs, read only for the counts on the product picker. Those are separate
      // origins, so the calls fail quietly until each service's CORS list names this app;
      // the picker drops the line rather than showing a zero it cannot stand behind.
      pulseApiUrl: "http://localhost:8002",
      forgeApiUrl: "http://localhost:8003",
      // The identity screen that hands a signed-in browser a token for another product.
      ssoAuthorizeUrl: "http://localhost:3002/sso/authorize",
      // The only addresses a token may be handed back to. Comma-separated so one
      // environment variable can replace the whole list at deploy time. Anything not on
      // this list is refused — see packages/ui/composables/useSSO.ts.
      ssoReturnAllowlist: [
        "http://localhost:3000/auth/callback",
        "http://localhost:3001/auth/callback",
        "http://localhost:3002/auth/callback",
      ].join(","),
    },
  },
});
