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
    },
  },
});
