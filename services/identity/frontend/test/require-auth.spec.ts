import { beforeEach, describe, expect, it, vi } from "vitest";
import { signInPath } from "~/utils/auth-form";

/* The real middleware module, with the four Nuxt auto-imports it uses stubbed on
   globalThis before it is imported. That is what auto-imports are at runtime, so the
   module under test is the shipped one rather than a copy of its logic. */

const globals = globalThis as Record<string, unknown>;

let authenticated = false;
const hydrate = vi.fn(() => {
  // Hydration is what makes the decision correct on a hard refresh; a guard that decides
  // before reading localStorage bounces someone who is signed in.
  authenticated = localStorage.getItem("identity.access_token") !== null;
});
const navigateTo = vi.fn((to: string) => to);

async function loadMiddleware() {
  globals.defineNuxtRouteMiddleware = (fn: unknown) => fn;
  // A getter, because the real isAuthenticated is a ref the guard reads *after* calling
  // hydrate(); a snapshot taken at useAuth() time would never see the stored session.
  globals.useAuth = () => ({
    hydrate,
    isAuthenticated: {
      get value() {
        return authenticated;
      },
    },
  });
  globals.navigateTo = navigateTo;
  globals.signInPath = signInPath;
  const module = await import("~/middleware/require-auth");
  return module.default as (to: { fullPath: string }) => unknown;
}

describe("require-auth", () => {
  beforeEach(() => {
    authenticated = false;
    localStorage.clear();
    navigateTo.mockClear();
    hydrate.mockClear();
  });

  it("sends a signed-out visitor to the sign-in screen carrying where they were going", async () => {
    const middleware = await loadMiddleware();

    const result = middleware({ fullPath: "/account" });

    expect(hydrate).toHaveBeenCalled();
    expect(navigateTo).toHaveBeenCalledWith("/login?next=%2Faccount");
    expect(result).toBe("/login?next=%2Faccount");
  });

  it("preserves the query string of the route that was refused", async () => {
    const middleware = await loadMiddleware();

    middleware({ fullPath: "/products?from=email" });

    expect(navigateTo).toHaveBeenCalledWith("/login?next=%2Fproducts%3Ffrom%3Demail");
  });

  it("lets a signed-in visitor through untouched", async () => {
    localStorage.setItem("identity.access_token", "tok.abc");
    const middleware = await loadMiddleware();

    const result = middleware({ fullPath: "/account" });

    expect(navigateTo).not.toHaveBeenCalled();
    expect(result).toBeUndefined();
  });
});
