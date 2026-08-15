import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RouteLocationNormalizedLoaded } from "vue-router";
import routerOptions, { isElementIdHash, scrollBehavior } from "../app/router.options";

/* The token that leaked. Real shape, three segments, taken from a handoff against the
   local stack and then expired — it is here so the assertions can look for it verbatim. */
const TOKEN = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI0MiIsImV4cCI6MTc4NjY1MDA0Mn0.aBcDeF-signature_1234567890";
const TOKEN_HASH = `#access_token=${TOKEN}&expires_in=900&state=9e52ebfac736b52ff94eae85a58fea4e&next=/`;

function route(path: string, hash = "", meta: Record<string, unknown> = {}): RouteLocationNormalizedLoaded {
  return { path, hash, meta, query: {}, params: {}, fullPath: `${path}${hash}`, name: undefined, matched: [], redirectedFrom: undefined, href: `${path}${hash}` } as unknown as RouteLocationNormalizedLoaded;
}

function run(to: RouteLocationNormalizedLoaded, from: RouteLocationNormalizedLoaded, saved: Parameters<typeof scrollBehavior>[2] = null) {
  // scrollBehavior may legally return a promise; nothing in this file does, but awaiting
  // the result keeps the tests honest if that ever changes.
  return (scrollBehavior as (...a: unknown[]) => unknown)(to, from, saved);
}

describe("router scrollBehavior", () => {
  let querySelector: ReturnType<typeof vi.spyOn>;
  let consoleOut: string[];

  beforeEach(() => {
    consoleOut = [];
    querySelector = vi.spyOn(document, "querySelector");
    for (const level of ["log", "info", "warn", "error", "debug"] as const) {
      vi.spyOn(console, level).mockImplementation((...args: unknown[]) => {
        consoleOut.push(args.map((a) => String(a)).join(" "));
      });
    }
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("is exported as the layer's default router options, so Nuxt picks it up", () => {
    expect(routerOptions.scrollBehavior).toBe(scrollBehavior);
  });

  it("refuses a sign-in fragment as a scroll target and never hands it to querySelector", () => {
    const result = run(route("/auth/callback", TOKEN_HASH), route("/login"));

    expect(result).toEqual({ left: 0, top: 0 });
    expect(result).not.toHaveProperty("el");
    expect(querySelector).not.toHaveBeenCalled();
  });

  it("refuses the fragment on a same-path navigation too", () => {
    const result = run(route("/auth/callback", TOKEN_HASH), route("/auth/callback"));

    expect(result).toBe(false);
    expect(querySelector).not.toHaveBeenCalled();
  });

  it("leaves no trace of the token in anything written to the console", () => {
    run(route("/auth/callback", TOKEN_HASH), route("/login"));
    run(route("/auth/callback", TOKEN_HASH), route("/auth/callback"));

    const written = consoleOut.join("\n");
    expect(written).not.toContain(TOKEN);
    expect(written).not.toContain("access_token");
    expect(written).not.toContain("eyJ");
    expect(consoleOut).toEqual([]);
  });

  it("still scrolls to a real in-page anchor", () => {
    document.body.innerHTML = '<main id="main">content</main>';

    expect(run(route("/reports", "#main"), route("/"))).toEqual({ el: "#main", top: 0 });
    expect(run(route("/reports", "#main"), route("/reports"))).toEqual({ el: "#main", top: 0 });
    expect(querySelector).not.toHaveBeenCalled();
  });

  it("returns savedPosition as-is on back and forward", () => {
    const saved = { left: 0, top: 640 };

    expect(run(route("/reports"), route("/"), saved)).toBe(saved);
    // Even when the entry being restored carries a fragment.
    expect(run(route("/reports", "#main"), route("/"), saved)).toBe(saved);
    expect(run(route("/auth/callback", TOKEN_HASH), route("/login"), saved)).toBe(saved);
    expect(querySelector).not.toHaveBeenCalled();
  });

  it("goes to the top when there is no hash", () => {
    expect(run(route("/reports"), route("/"))).toEqual({ left: 0, top: 0 });
  });

  it("holds the scroll position when only the query moved", () => {
    expect(run(route("/reports"), route("/reports"))).toBe(false);
  });

  it("returns to the top when a fragment is cleared on the same page", () => {
    expect(run(route("/reports"), route("/reports", "#main"))).toEqual({ left: 0, top: 0 });
  });

  it("honours scrollToTop: false, as a value and as a function", () => {
    expect(run(route("/reports", "", { scrollToTop: false }), route("/"))).toBe(false);
    expect(run(route("/reports", "", { scrollToTop: () => false }), route("/"))).toBe(false);
    expect(run(route("/reports", "", { scrollToTop: true }), route("/"))).toEqual({ left: 0, top: 0 });
  });

  it("adds the element's scroll-margin-top so a sticky header does not cover the anchor", () => {
    document.body.innerHTML = '<main id="main">content</main>';
    const el = document.getElementById("main")!;
    el.style.scrollMarginTop = "56px";

    expect(run(route("/reports", "#main"), route("/"))).toEqual({ el: "#main", top: 56 });
  });
});

describe("isElementIdHash", () => {
  it("accepts a plain element id", () => {
    for (const hash of ["#main", "#_private", "#step-2", "#a", "#Section_1-b"]) {
      expect(isElementIdHash(hash), hash).toBe(true);
    }
  });

  it("rejects every character a token fragment is made of", () => {
    for (const hash of ["#a=b", "#a&b", "#a.b", "#a/b", "#a b", "#a\tb", "#a\nb", TOKEN_HASH]) {
      expect(isElementIdHash(hash), JSON.stringify(hash)).toBe(false);
    }
  });

  it("rejects an empty hash, a bare hash and anything not starting with one", () => {
    for (const hash of ["", "#", "main", "?main"]) {
      expect(isElementIdHash(hash), JSON.stringify(hash)).toBe(false);
    }
  });

  it("rejects ids that do not start with a letter or underscore, and absurdly long ones", () => {
    expect(isElementIdHash("#1thing")).toBe(false);
    expect(isElementIdHash("#-thing")).toBe(false);
    expect(isElementIdHash(`#${"a".repeat(128)}`)).toBe(true);
    expect(isElementIdHash(`#${"a".repeat(129)}`)).toBe(false);
  });
});
