import { beforeEach, describe, expect, it } from "vitest";
import { computed } from "vue";
import { isAllowedReturnUrl, isSafeNextPath, parseAllowlist, useSSO } from "@crescent/ui/composables/useSSO";

/* The security-critical half of the cross-product handoff. An open redirect here does not
   just send someone somewhere unexpected — it hands an access token to whoever asked. */

const ALLOW = ["http://localhost:3000/auth/callback", "http://localhost:3001/auth/callback"];

describe("isAllowedReturnUrl", () => {
  it("accepts an exact configured address", () => {
    expect(isAllowedReturnUrl("http://localhost:3001/auth/callback", ALLOW)).toBe(true);
  });

  it("accepts a deeper path under a configured one", () => {
    expect(isAllowedReturnUrl("http://localhost:3001/auth/callback/finish", ALLOW)).toBe(true);
  });

  it.each([
    ["a different host", "http://evil.example/auth/callback"],
    ["a host that only starts the same", "http://localhost:3001.evil.example/auth/callback"],
    ["a different port", "http://localhost:9999/auth/callback"],
    ["a different scheme", "https://localhost:3001/auth/callback"],
    ["a protocol-relative address", "//evil.example/auth/callback"],
    ["a relative path", "/auth/callback"],
    ["a javascript: URL", "javascript:alert(document.cookie)"],
    ["a data: URL", "data:text/html,<script>fetch(location.hash)</script>"],
    ["userinfo dressed as the real host", "http://localhost:3001@evil.example/auth/callback"],
    ["a path that only starts the same", "http://localhost:3001/auth/callback-evil"],
    ["an empty value", ""],
  ])("rejects %s", (_label, url) => {
    expect(isAllowedReturnUrl(url, ALLOW)).toBe(false);
  });

  it("rejects everything when the allowlist is empty", () => {
    expect(isAllowedReturnUrl("http://localhost:3001/auth/callback", [])).toBe(false);
  });
});

describe("isSafeNextPath", () => {
  it.each(["/", "/reports", "/reports/12?tab=evidence"])("accepts %s", (path) => {
    expect(isSafeNextPath(path)).toBe(true);
  });

  it.each(["//evil.example", "/\\evil.example", "http://evil.example", "evil"])("rejects %s", (path) => {
    expect(isSafeNextPath(path)).toBe(false);
  });
});

describe("parseAllowlist", () => {
  it("splits the comma-separated form used in runtimeConfig", () => {
    expect(parseAllowlist("http://a/cb, http://b/cb ")).toEqual(["http://a/cb", "http://b/cb"]);
  });

  it("takes an array unchanged and drops empties", () => {
    expect(parseAllowlist(["http://a/cb", ""])).toEqual(["http://a/cb"]);
  });
});

// useSSO() reaches for two Nuxt auto-imports. Stubbing them is enough: nothing else in the
// composable touches the framework.
function withConfig() {
  (globalThis as Record<string, unknown>).computed = computed;
  (globalThis as Record<string, unknown>).useRuntimeConfig = () => ({
    public: {
      authStoragePrefix: "pulse",
      ssoAuthorizeUrl: "http://localhost:3002/sso/authorize",
      ssoReturnAllowlist: ALLOW.join(","),
    },
  });
  return useSSO();
}

describe("consumeHandoff", () => {
  beforeEach(() => {
    history.replaceState(null, "", "/auth/callback");
    sessionStorage.clear();
  });

  it("takes the token when the state matches the one this browser stored", () => {
    sessionStorage.setItem("pulse.sso_state", "abc123");
    window.location.hash = "#access_token=tok.abc&expires_in=900&state=abc123&next=%2Freports";

    const result = withConfig().consumeHandoff();

    expect(result).toEqual({ ok: true, tokens: { accessToken: "tok.abc", expiresIn: 900 }, next: "/reports" });
  });

  it("refuses a handoff this browser never started", () => {
    window.location.hash = "#access_token=attacker.token&expires_in=900&state=whatever";

    const result = withConfig().consumeHandoff();

    expect(result).toEqual({ ok: false, reason: "state-mismatch" });
  });

  it("refuses a state that does not match the stored one", () => {
    sessionStorage.setItem("pulse.sso_state", "abc123");
    window.location.hash = "#access_token=attacker.token&state=abc124";

    expect(withConfig().consumeHandoff()).toEqual({ ok: false, reason: "state-mismatch" });
  });

  it("erases the fragment and the stored state before returning", () => {
    sessionStorage.setItem("pulse.sso_state", "abc123");
    window.location.hash = "#access_token=tok.abc&expires_in=900&state=abc123";

    withConfig().consumeHandoff();

    expect(window.location.hash).toBe("");
    expect(sessionStorage.getItem("pulse.sso_state")).toBeNull();
  });

  it("drops a next that would leave the app", () => {
    sessionStorage.setItem("pulse.sso_state", "abc123");
    window.location.hash = "#access_token=tok.abc&state=abc123&next=https%3A%2F%2Fevil.example";

    const result = withConfig().consumeHandoff();

    expect(result.ok && result.next).toBe("/");
  });

  it("says so when there is nothing to consume", () => {
    expect(withConfig().consumeHandoff()).toEqual({ ok: false, reason: "no-handoff" });
  });
});

describe("readRequest", () => {
  it("refuses a return address that is not on the allowlist", () => {
    expect(withConfig().readRequest({ return_to: "http://evil.example/auth/callback", state: "s" })).toBeNull();
  });

  it("refuses a request with no state to bind it to a browser", () => {
    expect(withConfig().readRequest({ return_to: "http://localhost:3001/auth/callback" })).toBeNull();
  });

  it("reads a well-formed request and sanitises next", () => {
    expect(
      withConfig().readRequest({
        return_to: "http://localhost:3001/auth/callback",
        state: "s",
        next: "//evil.example",
      }),
    ).toEqual({ returnTo: "http://localhost:3001/auth/callback", state: "s", next: "/" });
  });
});

describe("completeHandoff", () => {
  it("puts the token in the fragment, never the query string", () => {
    const url = withConfig().completeHandoff(
      { returnTo: "http://localhost:3001/auth/callback", state: "s", next: "/reports" },
      { access_token: "tok.abc", refresh_token: "should-not-travel", token_type: "bearer", expires_in: 900, user: {} as never },
    );

    const parsed = new URL(url);
    expect(parsed.search).toBe("");
    expect(parsed.hash).toContain("access_token=tok.abc");
    expect(url).not.toContain("should-not-travel");
  });

  it("refuses to build a redirect to an address that is not on the allowlist", () => {
    expect(() =>
      withConfig().completeHandoff(
        { returnTo: "http://evil.example/auth/callback", state: "s", next: "/" },
        { access_token: "tok.abc", refresh_token: "r", token_type: "bearer", expires_in: 900, user: {} as never },
      ),
    ).toThrow(/allowlist/);
  });
});
