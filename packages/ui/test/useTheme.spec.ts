import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { THEME_BOOT_SCRIPT, THEME_DOMAIN_ATTR, THEME_KEY, readThemeCookie, writeThemeCookie } from "../utils/theme";

/* The composable keeps its state at module scope so every caller agrees, which means a
   test that wants a clean slate has to re-import it. `vue` is pulled from the same
   dynamic import so `onScopeDispose` is the one the composable actually calls. */
async function fresh() {
  vi.resetModules();
  const mod = await import("../composables/useTheme");
  const vue = await import("vue");
  return { useTheme: mod.useTheme, effectScope: vue.effectScope };
}

type Handler = (event: MediaQueryListEvent) => void;

function fakeMedia(matches: boolean) {
  const handlers = new Set<Handler>();
  const mql = {
    matches,
    media: "(prefers-color-scheme: dark)",
    addEventListener: vi.fn((_type: string, fn: Handler) => void handlers.add(fn)),
    removeEventListener: vi.fn((_type: string, fn: Handler) => void handlers.delete(fn)),
    flip(next: boolean) {
      mql.matches = next;
      for (const fn of handlers) fn({ matches: next } as MediaQueryListEvent);
    },
    get handlerCount() {
      return handlers.size;
    },
  };
  window.matchMedia = (() => mql) as unknown as typeof window.matchMedia;
  return mql;
}

function cookieValue(): string | null {
  const match = document.cookie.match(/(?:^|; )meridian\.theme=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : null;
}

const realMatchMedia = window.matchMedia;

/* document.cookie cannot be made to hold two entries of one name from inside the page —
   the store dedupes by name — and a Domain= attribute for a host the test is not on is
   dropped silently. Both cases are therefore driven through a stubbed accessor, which is
   also what makes the written string assertable. */
let written: string[] = [];

function stubCookie(initial: string) {
  written = [];
  let value = initial;
  Object.defineProperty(document, "cookie", {
    configurable: true,
    get: () => value,
    set: (next: string) => {
      written.push(next);
      value = next.split(";")[0]!;
    },
  });
}

function restoreCookie() {
  delete (document as unknown as Record<string, unknown>).cookie;
}

beforeEach(() => {
  window.localStorage.clear();
  document.cookie = `${THEME_KEY}=; path=/; max-age=0`;
  delete document.documentElement.dataset.theme;
  document.documentElement.removeAttribute(THEME_DOMAIN_ATTR);
});

afterEach(() => {
  window.matchMedia = realMatchMedia;
});

describe("useTheme", () => {
  it("defaults to system, and resolves it from the OS", async () => {
    fakeMedia(false);
    const { useTheme } = await fresh();
    const { theme, resolved } = useTheme();
    expect(theme.value).toBe("system");
    expect(resolved.value).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  /* A cookie rather than localStorage: the three products are three ports in dev, and
     localStorage is per-origin, so a choice made in one did not follow to the next. */
  it("persists an explicit choice to a shared cookie and reads it back on the next boot", async () => {
    fakeMedia(true);
    const first = await fresh();
    first.useTheme().setTheme("light");
    expect(cookieValue()).toBe("light");
    expect(document.cookie).not.toContain("Secure");
    expect(document.documentElement.dataset.theme).toBe("light");

    // Second boot: the OS still says dark, the stored choice must win.
    const second = await fresh();
    const { theme, resolved } = second.useTheme();
    expect(theme.value).toBe("light");
    expect(resolved.value).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("carries a pre-existing localStorage choice over to the cookie", async () => {
    fakeMedia(true);
    window.localStorage.setItem(THEME_KEY, "light");
    const { useTheme } = await fresh();
    const { theme } = useTheme();
    expect(theme.value).toBe("light");
    expect(cookieValue()).toBe("light");
    expect(window.localStorage.getItem(THEME_KEY)).toBeNull();
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("prefers the cookie over a stale localStorage value", async () => {
    fakeMedia(true);
    window.localStorage.setItem(THEME_KEY, "dark");
    document.cookie = `${THEME_KEY}=light; path=/`;
    const { useTheme } = await fresh();
    expect(useTheme().theme.value).toBe("light");
  });

  it("keeps following the OS while the app is open when the choice is system", async () => {
    const mql = fakeMedia(true);
    const { useTheme } = await fresh();
    const { resolved } = useTheme();
    expect(resolved.value).toBe("dark");

    mql.flip(false);
    expect(resolved.value).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("stops following once a theme is picked by hand", async () => {
    const mql = fakeMedia(true);
    const { useTheme } = await fresh();
    const { resolved, setTheme } = useTheme();
    setTheme("dark");
    mql.flip(false);
    expect(resolved.value).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("releases the media listener with the scope that took it", async () => {
    const mql = fakeMedia(false);
    const { useTheme, effectScope } = await fresh();
    const scope = effectScope();
    scope.run(() => useTheme());
    expect(mql.addEventListener).toHaveBeenCalledTimes(1);
    expect(mql.handlerCount).toBe(1);

    scope.stop();
    expect(mql.removeEventListener).toHaveBeenCalledTimes(1);
    expect(mql.handlerCount).toBe(0);
  });

  it("falls back to dark instead of throwing when the cookie store is unreadable", async () => {
    fakeMedia(false);
    Object.defineProperty(document, "cookie", {
      configurable: true,
      get() {
        throw new DOMException("The operation is insecure.", "SecurityError");
      },
      set() {
        throw new DOMException("The operation is insecure.", "SecurityError");
      },
    });
    try {
      const { useTheme } = await fresh();
      const { theme, resolved } = useTheme();
      expect(theme.value).toBe("dark");
      expect(resolved.value).toBe("dark");
      expect(document.documentElement.dataset.theme).toBe("dark");
      // A write that cannot land costs the choice its persistence, not the session.
      expect(() => useTheme().setTheme("light")).not.toThrow();
      expect(document.documentElement.dataset.theme).toBe("light");
    } finally {
      delete (document as unknown as Record<string, unknown>).cookie;
    }
  });

  it("falls back to dark instead of throwing when localStorage is unreadable", async () => {
    fakeMedia(false);
    const store = window.localStorage;
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      get() {
        throw new DOMException("The operation is insecure.", "SecurityError");
      },
    });
    try {
      const { useTheme } = await fresh();
      expect(useTheme().theme.value).toBe("dark");
      expect(document.documentElement.dataset.theme).toBe("dark");
    } finally {
      Object.defineProperty(window, "localStorage", { configurable: true, value: store });
    }
  });
});

/* The inline head script is what stops a light user seeing a dark frame on every hard
   load, and it is a string that nothing else imports, so nothing else would catch it
   breaking. Run it the way the browser does. */
describe("THEME_BOOT_SCRIPT", () => {
  function boot() {
    // eslint-disable-next-line no-new-func
    new Function(THEME_BOOT_SCRIPT)();
  }

  it("paints the cookie's choice before anything else runs", () => {
    fakeMedia(true);
    document.cookie = `${THEME_KEY}=light; path=/`;
    boot();
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("still paints a not-yet-migrated localStorage choice", () => {
    fakeMedia(true);
    window.localStorage.setItem(THEME_KEY, "light");
    boot();
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("asks the OS when the choice is system", () => {
    fakeMedia(false);
    document.cookie = `${THEME_KEY}=system; path=/`;
    window.localStorage.setItem(THEME_KEY, "dark");
    boot();
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  /* The deployment case. On subdomains the cookie is written on the parent domain, and a
     browser part-way through that move sends both copies under one name; the parent's is
     the newer, and equal-path cookies arrive oldest first. */
  it("takes the parent-domain cookie over a stale host-only one when a domain is configured", () => {
    fakeMedia(true);
    document.documentElement.setAttribute(THEME_DOMAIN_ATTR, ".example.com");
    stubCookie(`${THEME_KEY}=dark; ${THEME_KEY}=light`);
    try {
      boot();
      expect(document.documentElement.dataset.theme).toBe("light");
    } finally {
      restoreCookie();
    }
  });

  // With no domain there is only ever one cookie of this name, and the first is it.
  it("takes the first cookie when no domain is configured", () => {
    fakeMedia(true);
    stubCookie(`${THEME_KEY}=light; ${THEME_KEY}=dark`);
    try {
      boot();
      expect(document.documentElement.dataset.theme).toBe("light");
    } finally {
      restoreCookie();
    }
  });

  it("falls back to dark when neither store can be read", () => {
    fakeMedia(false);
    Object.defineProperty(document, "cookie", {
      configurable: true,
      get() {
        throw new DOMException("The operation is insecure.", "SecurityError");
      },
    });
    try {
      boot();
      expect(document.documentElement.dataset.theme).toBe("dark");
    } finally {
      delete (document as unknown as Record<string, unknown>).cookie;
    }
  });
});

/* Part of the same mechanism as the boot script above: where the cookie is written has to
   match where it is read, and on subdomains "here" is not good enough. */
describe("the theme cookie's scope", () => {
  it("writes a host-only cookie when no domain is configured", () => {
    stubCookie("");
    try {
      writeThemeCookie("light");
      expect(written).toEqual([expect.not.stringContaining("Domain=")]);
      expect(written[0]).toContain(`${THEME_KEY}=light`);
    } finally {
      restoreCookie();
    }
  });

  it("scopes the cookie to the parent domain when one is configured", () => {
    stubCookie("");
    try {
      writeThemeCookie("dark", ".example.com");
      expect(written.at(-1)).toContain("Domain=.example.com");
      expect(written.at(-1)).toContain(`${THEME_KEY}=dark`);
    } finally {
      restoreCookie();
    }
  });

  /* Without this the old host-only cookie outlives the new one under the same name and
     shadows every read, so picking a theme would appear to do nothing. */
  it("expires the host-only cookie first, so the two cannot shadow each other", () => {
    stubCookie(`${THEME_KEY}=light`);
    try {
      writeThemeCookie("dark", ".example.com");
      expect(written).toHaveLength(2);
      expect(written[0]).toContain("max-age=0");
      expect(written[0]).not.toContain("Domain=");
    } finally {
      restoreCookie();
    }
  });

  it("reads the parent-domain copy back when a domain is configured", () => {
    stubCookie(`${THEME_KEY}=dark; ${THEME_KEY}=system`);
    try {
      expect(readThemeCookie(".example.com")).toBe("system");
      expect(readThemeCookie()).toBe("dark");
    } finally {
      restoreCookie();
    }
  });
});
