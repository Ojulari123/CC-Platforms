export default defineNuxtConfig({
  // Login, token storage, the API client and the route guard come from the shared
  // Nuxt layer in packages/ui, so a token-handling fix is made once for all products.
  extends: ["../../../packages/ui"],
  compatibilityDate: "2025-01-01",
  devtools: { enabled: false },
  // Pinned so Pulse and Forge can run side by side: Forge holds 3000, Pulse 3001.
  devServer: { port: 3000 },
  modules: ["@nuxtjs/tailwindcss"],
  typescript: { strict: true },
  runtimeConfig: {
    public: {
      identityUrl: "http://localhost:8001",
      forgeUrl: "http://localhost:8003",
      // Keeps the localStorage keys browsers already hold from before the move.
      authStoragePrefix: "forge",
      // Identity's front end, as an absolute URL. `identityUrl` above is its API on
      // :8001; this is the site on :3002, which is what a cross-product control such as
      // "All products" links to.
      identityWebUrl: "http://localhost:3002",
      // The identity screen that hands a signed-in browser a token for this product.
      ssoAuthorizeUrl: "http://localhost:3002/sso/authorize",
      /* The only addresses a token may be handed back to. Forge only ever asks for a
         handoff, so the list holds Forge's own callback and nothing else: useSSO checks
         `${origin}${pathname}` against it before leaving for identity, and a wider list
         here would buy nothing and widen an open-redirect surface. Identity keeps the
         list of all three, because identity is the end that actually hands tokens out.
         Comma-separated so one environment variable can replace it at deploy time. */
      ssoReturnAllowlist: ["http://localhost:3000/auth/callback"].join(","),
    },
  },
});
