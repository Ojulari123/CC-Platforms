/* The return allowlist is the open-redirect guard, and it matters most here: identity
   is the end that actually hands the access token out, so every address on this list is
   somewhere a live token can be delivered. NUXT_PUBLIC_SSO_RETURN_ALLOWLIST replaces the
   whole list at deploy time, which means the deployed value is the one that matters — so
   it is checked here rather than trusted. Vercel exposes environment variables to the
   build, and a changed variable needs a redeploy to take effect anyway, so a bad list
   fails the build instead of reaching a browser. Nothing is checked when the variable is
   unset: that is the localhost default below, which docker-compose and `nuxt dev` use. */
function checkedAllowlist(fallback: string[]): string {
  // Read through globalThis: a Nuxt config runs in Node, but these apps do not
  // depend on @types/node, so a bare `process` is untyped and `raw` would fall
  // back to any, taking the checks below with it.
  const env = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env ?? {};
  const raw = env.NUXT_PUBLIC_SSO_RETURN_ALLOWLIST;
  if (raw === undefined) return fallback.join(",");

  const refuse = (entry: string, why: string): never => {
    throw new Error(`NUXT_PUBLIC_SSO_RETURN_ALLOWLIST entry ${JSON.stringify(entry)} ${why}`);
  };
  const entries = raw.split(",").map((entry) => entry.trim()).filter(Boolean);
  if (!entries.length) throw new Error("NUXT_PUBLIC_SSO_RETURN_ALLOWLIST is set but empty, which refuses every sign-in handoff. Unset it to keep the built-in default.");

  for (const entry of entries) {
    // A "*" is already inert — useSSO compares parsed origins, so it would match
    // nothing — but it means someone believed it widened the list, so say so.
    if (entry.includes("*")) refuse(entry, "contains a wildcard. This list is exact origins only; a wildcard matches nothing and hides the fact that sign-in is broken.");
    let url: URL;
    try {
      url = new URL(entry);
    } catch {
      return refuse(entry, "is not an absolute URL. Write the full callback, e.g. https://pulse.example.com/auth/callback.");
    }
    const loopback = url.hostname === "localhost" || url.hostname === "127.0.0.1";
    if (url.protocol !== "https:" && !loopback) refuse(entry, "is not https. The access token travels in this URL's fragment, so plain http puts it on the wire.");
    if (url.username || url.password) refuse(entry, "carries credentials in the host part, which reads like one host and resolves to another.");
    if (url.search || url.hash) refuse(entry, "has a query or fragment. Only the origin and path are matched, so anything after them is a false promise.");
    if (!url.pathname.replace(/\/+$/, "")) refuse(entry, "is a bare origin, which allows EVERY path on that host to receive a token. Name the callback path.");
  }
  return entries.join(",");
}

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
      ssoReturnAllowlist: checkedAllowlist([
        "http://localhost:3000/auth/callback",
        "http://localhost:3001/auth/callback",
        "http://localhost:3002/auth/callback",
      ]),
    },
  },
});
