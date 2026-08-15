/* The return allowlist is the open-redirect guard: identity hands a live access token
   to any address on it, so a loose entry is a token-theft bug rather than a typo.
   NUXT_PUBLIC_SSO_RETURN_ALLOWLIST replaces the whole list at deploy time, which means
   the deployed value is the one that matters — so it is checked here rather than
   trusted. Vercel exposes environment variables to the build, and a changed variable
   needs a redeploy to take effect anyway, so a bad list fails the build instead of
   reaching a browser. Nothing is checked when the variable is unset: that is the
   localhost default below, which docker-compose and `nuxt dev` both use. */
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
      return refuse(entry, "is not an absolute URL. Write the full callback, e.g. https://forge.example.com/auth/callback.");
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
      ssoReturnAllowlist: checkedAllowlist(["http://localhost:3000/auth/callback"]),
    },
  },
});
