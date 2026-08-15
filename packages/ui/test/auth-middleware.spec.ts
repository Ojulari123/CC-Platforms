import { beforeEach, describe, expect, it, vi } from "vitest";

/* The real guard, with the Nuxt auto-imports it uses stubbed on globalThis before it is
   imported — that is what an auto-import is at runtime, so what runs here is the shipped
   module rather than a restatement of its logic.

   Everything is asserted on the argument handed to navigateTo, because that argument is
   the address the browser ends up at, and the address is the thing that leaks. */

type RouteGuard = (to: { path: string; fullPath: string }) => unknown;

declare global {
  /* Importing the guard is what first brings middleware/auth.ts into this project's
     typecheck, so the Nuxt surface it uses has to come with it. `defineNuxtRouteMiddleware`
     lives in test/nuxt-globals.d.ts with the rest — declaring it in a .ts file collides with
     Nuxt's own global when an app typechecks this layer. This is an interface merge, so it
     does not. */
  interface ImportMeta {
    readonly server: boolean;
  }
}

const globals = globalThis as Record<string, unknown>;

const PROBE_TOKEN = "eyJhbGciOiJSUzI1NiJ9.PROBE.SIG";

let authenticated = false;
const hydrate = vi.fn(() => {
  authenticated = localStorage.getItem("pulse.access_token") !== null;
});
const navigateTo = vi.fn((to: string) => to);

async function loadMiddleware() {
  globals.defineNuxtRouteMiddleware = (fn: RouteGuard) => fn;
  globals.useAuth = () => ({
    hydrate,
    isAuthenticated: {
      get value() {
        return authenticated;
      },
    },
  });
  globals.navigateTo = navigateTo;
  const module = await import("../middleware/auth");
  return module.default as RouteGuard;
}

function visit(path: string, fullPath = path) {
  return loadMiddleware().then((middleware) => String(middleware({ path, fullPath }) ?? ""));
}

/* Raw and encoded, because the redirect is built with encodeURIComponent: a "#" that
   survived would read as "%23" in the address bar and still be a token in the query. */
function expectNoToken(redirect: string) {
  expect(redirect).not.toContain("access_token");
  expect(redirect).not.toContain("PROBE");
  expect(decodeURIComponent(redirect)).not.toContain("access_token");
}

describe("auth middleware — the fragment never becomes a query string", () => {
  beforeEach(() => {
    authenticated = false;
    localStorage.clear();
    navigateTo.mockClear();
    hydrate.mockClear();
  });

  it("drops a token-shaped fragment from the sign-in redirect", async () => {
    const redirect = await visit("/reports", `/reports#access_token=${PROBE_TOKEN}&state=abc`);

    expectNoToken(redirect);
    expect(navigateTo).toHaveBeenCalledWith("/login?next=%2Freports");
    expect(redirect).toBe("/login?next=%2Freports");
  });

  it("drops the fragment but keeps the query string it followed", async () => {
    const redirect = await visit("/reports", `/reports?tab=queue#access_token=${PROBE_TOKEN}&state=abc`);

    expectNoToken(redirect);
    expect(navigateTo).toHaveBeenCalledWith("/login?next=%2Freports%3Ftab%3Dqueue");
  });

  it("does not resurrect a percent-encoded fragment", async () => {
    const redirect = await visit("/reports", `/reports%23access_token=${PROBE_TOKEN}%26state=abc`);

    expectNoToken(redirect);
    expect(navigateTo).toHaveBeenCalledWith("/login?next=%2Freports");
  });

  it("does not resurrect a double-encoded fragment", async () => {
    const redirect = await visit("/reports", `/reports%2523access_token=${PROBE_TOKEN}`);

    expectNoToken(redirect);
    expect(navigateTo).toHaveBeenCalledWith("/login?next=%2Freports");
  });

  it("refuses rather than trims an encoding it cannot cut cleanly", async () => {
    // "%25%3233" is a "#" after two rounds of decoding. Nothing here is worth a guess, so
    // the whole value is dropped instead of half-trimmed.
    const redirect = await visit("/reports", `/reports%25%3233access_token=${PROBE_TOKEN}`);

    expectNoToken(redirect);
    expect(navigateTo).toHaveBeenCalledWith("/login");
  });

  it("sends a bare fragment to the plain sign-in screen", async () => {
    const redirect = await visit("/", `/#access_token=${PROBE_TOKEN}`);

    expectNoToken(redirect);
    expect(navigateTo).toHaveBeenCalledWith("/login");
  });
});

describe("auth middleware — the deep link still works", () => {
  beforeEach(() => {
    authenticated = false;
    localStorage.clear();
    navigateTo.mockClear();
    hydrate.mockClear();
  });

  it("round-trips a deep link with a query string", async () => {
    const redirect = await visit("/reports", "/reports?tab=queue");

    expect(navigateTo).toHaveBeenCalledWith("/login?next=%2Freports%3Ftab%3Dqueue");
    // What the sign-in screen reads back out of the query is the route that was asked for.
    const next = new URL(redirect, "http://localhost:3001").searchParams.get("next");
    expect(next).toBe("/reports?tab=queue");
  });

  it("round-trips a nested path", async () => {
    await visit("/reports/12", "/reports/12");

    expect(navigateTo).toHaveBeenCalledWith("/login?next=%2Freports%2F12");
  });

  it("does not carry a next for the app root", async () => {
    await visit("/", "/");

    expect(navigateTo).toHaveBeenCalledWith("/login");
  });

  it("lets a signed-in visitor through untouched", async () => {
    localStorage.setItem("pulse.access_token", "tok.abc");
    const middleware = await loadMiddleware();

    const result = middleware({ path: "/reports", fullPath: "/reports?tab=queue" });

    expect(navigateTo).not.toHaveBeenCalled();
    expect(result).toBeUndefined();
  });

  it("does not bounce the sign-in screen back at itself", async () => {
    const middleware = await loadMiddleware();

    const result = middleware({ path: "/login", fullPath: "/login?next=%2Freports" });

    expect(navigateTo).not.toHaveBeenCalled();
    expect(result).toBeUndefined();
  });
});

describe("auth middleware — values that would leave the origin", () => {
  beforeEach(() => {
    authenticated = false;
    localStorage.clear();
    navigateTo.mockClear();
    hydrate.mockClear();
  });

  it.each([
    ["protocol-relative", "//evil.example"],
    ["backslash", "/\\evil.example"],
    ["absolute url", "http://evil.example/reports"],
    ["scheme-only", "javascript:alert(1)"],
    ["bare host", "evil.example"],
    // Tab, CR and LF are deleted by the URL parser, so this is "//evil.example" by the time
    // anything navigates to it.
    ["tab-smuggled protocol-relative", "/\t/evil.example"],
    ["newline-smuggled protocol-relative", "/\n/evil.example"],
  ])("refuses a %s next", async (_label, hostile) => {
    const redirect = await visit("/reports", hostile);

    expect(navigateTo).toHaveBeenCalledWith("/login");
    expect(redirect).toBe("/login");
  });
});
