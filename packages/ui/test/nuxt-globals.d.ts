import type { TokenPair } from "../types/api";

/* The layer's pages are written for Nuxt, which auto-imports Vue's reactivity, its own
   composables and this layer's. Vitest mounts them outside Nuxt, so the harness assigns
   those names onto globalThis (see test/pageHarness.ts) and this file is what makes them
   typed rather than errors. `var`, not `const`: only `var` in a global block puts the
   name on `typeof globalThis`, which is what the assignment needs.

   Only the surface the three recovery pages actually touch is declared. Anything wider
   would be a second, drifting copy of Nuxt's generated types. */

declare global {
  var ref: typeof import("vue").ref;
  var computed: typeof import("vue").computed;
  var onMounted: typeof import("vue").onMounted;
  var onBeforeUnmount: typeof import("vue").onBeforeUnmount;
  var nextTick: typeof import("vue").nextTick;

  var definePageMeta: (meta: Record<string, unknown>) => void;
  var useHead: (input: Record<string, unknown>) => void;
  var useRuntimeConfig: () => { public: { identityUrl: string } & Record<string, unknown> };
  var useRoute: () => { query: Record<string, unknown> };
  var useRouter: () => {
    push: (to: string | Record<string, unknown>) => Promise<unknown>;
    replace: (to: string | Record<string, unknown>) => Promise<unknown>;
  };
  var $fetch: <T = unknown>(url: string, options?: Record<string, unknown>) => Promise<T>;

  var navigateTo: (to: string, options?: Record<string, unknown>) => Promise<unknown>;
  /* Used by middleware/auth.ts, which the middleware spec imports. It belongs here with
     the rest rather than in that spec: a declaration in a .ts file is checked against
     Nuxt's own generated global when an app typechecks this layer, and the two collide. */
  var defineNuxtRouteMiddleware: <T extends (to: { path: string; fullPath: string }) => unknown>(middleware: T) => T;

  var useAnnounce: () => (message: string) => void;
  var useAuth: () => {
    adoptSession: (pair: TokenPair) => Promise<void>;
    accessToken: { value: string | null };
    isAuthenticated: { value: boolean };
    hydrate: () => void;
    fetchMe: () => Promise<void>;
    logout: () => void;
  };
  var useSSO: () => {
    configured: { value: boolean };
    consumeHandoff: () => import("../composables/useSSO").SsoResult;
    startHandoff: (next?: string) => void;
  };
  var useTokenStorage: () => {
    read: () => { accessToken: string | null; refreshToken: string | null };
    write: (tokens: { accessToken: string; refreshToken: string }) => void;
    clear: () => void;
  };
  var safeNextPath: typeof import("../composables/useSSO").safeNextPath;
  var usePasswordRules: typeof import("../composables/usePasswordRules").usePasswordRules;
}

export {};
