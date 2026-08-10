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
    },
  },
});
