export default defineNuxtConfig({
  extends: ["../../../packages/ui"],
  compatibilityDate: "2025-01-01",
  devtools: { enabled: false },
  // Pinned so Pulse and Forge can run side by side, and listed in both services'
  // CORS_ORIGINS: Forge holds 3000, Pulse 3001.
  devServer: { port: 3001 },
  modules: ["@nuxtjs/tailwindcss"],
  typescript: { strict: true },
  runtimeConfig: {
    public: {
      identityUrl: "http://localhost:8001",
      pulseUrl: "http://localhost:8002",
      authStoragePrefix: "pulse",
      // Identity's front end, as an absolute URL. `identityUrl` above is its API on
      // :8001; this is the site on :3002, which is what "All products", the account
      // link and the sign-in fallback point at.
      identityWebUrl: "http://localhost:3002",
      // The identity screen that hands a signed-in browser a token for this product.
      ssoAuthorizeUrl: "http://localhost:3002/sso/authorize",
      /* The only addresses a token may be handed back to. Pulse only ever asks for a
         handoff, so the list holds Pulse's own callback and nothing else: useSSO checks
         `${origin}${pathname}` against it before leaving for identity, and a wider list
         here would buy nothing and widen an open-redirect surface. Identity keeps the
         list of all three, because identity is the end that actually hands tokens out.
         Comma-separated so one environment variable can replace it at deploy time. */
      ssoReturnAllowlist: ["http://localhost:3001/auth/callback"].join(","),
    },
  },
});
