import { computed, onBeforeUnmount, ref } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { chrome, installNuxt } from "./pageHarness";
import { safeNextPath } from "../composables/useSSO";
import type { SsoResult } from "../composables/useSSO";

/* The cross-product callback. useSSO is mocked rather than driven for real, because what
   is under test here is what the page does with each answer — in particular that no answer
   ends in a silent redirect, and that every failure leaves one legible line behind. */

const ACCESS_TOKEN = "eyJhbGciOiJSUzI1NiJ9.stub-access-token-value.sig";
const STATE = "9f2c41ab7d0e6c58f0b3a17d4c9e2b60";
const WARN_LINE = "[sso] callback did not complete";

// STALL_MS in pages/auth/callback.vue.
const STALL_MS = 6000;

interface MountOptions {
  query?: Record<string, unknown>;
  hash?: string;
  result?: SsoResult;
  configured?: boolean;
  startHandoff?: (next: string) => void;
  storedToken?: string;
  fetchMe?: () => Promise<void>;
}

async function mountPage(options: MountOptions = {}) {
  installNuxt({ query: options.query });

  const g = globalThis as Record<string, unknown>;
  g.onBeforeUnmount = onBeforeUnmount;
  g.safeNextPath = safeNextPath;

  if (options.hash !== undefined) window.location.hash = options.hash;

  const accessToken = ref<string | null>(options.storedToken ?? null);
  const hydrate = vi.fn();
  const fetchMe = vi.fn(options.fetchMe ?? (async () => undefined));
  g.useAuth = () => ({
    accessToken,
    isAuthenticated: computed(() => !!accessToken.value),
    hydrate,
    fetchMe,
  });

  const write = vi.fn();
  g.useTokenStorage = () => ({ write, read: () => ({ accessToken: null, refreshToken: null }), clear: vi.fn() });

  const result: SsoResult = options.result ?? { ok: false, reason: "no-handoff" };
  // The real consumeHandoff erases the fragment before it returns anything, whatever the
  // outcome, so the stub does too — otherwise the token would still be in the address bar.
  const consumeHandoff = vi.fn(() => {
    window.location.hash = "";
    return result;
  });
  const startHandoff = vi.fn(options.startHandoff ?? (() => undefined));
  g.useSSO = () => ({ configured: computed(() => options.configured ?? true), consumeHandoff, startHandoff });

  const navigate = vi.fn(async () => undefined);
  g.navigateTo = navigate;

  const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);

  const Page = (await import("../pages/auth/callback.vue")).default;
  const wrapper = mount(Page, { global: { components: chrome } });
  await flushPromises();

  return { wrapper, warn, navigate, write, startHandoff, consumeHandoff, fetchMe, hydrate, accessToken };
}

/** The single structured line, as an object, for the last warning recorded. */
function breadcrumb(warn: ReturnType<typeof vi.spyOn>): Record<string, unknown> {
  const call = warn.mock.calls.at(-1) as unknown[] | undefined;
  expect(call?.[0]).toBe(WARN_LINE);
  return call?.[1] as Record<string, unknown>;
}

afterEach(() => {
  window.location.hash = "";
  vi.useRealTimers();
});

describe("sso callback, the leg that works", () => {
  it("takes the token out of the fragment, stores it, and carries on to next", async () => {
    const { wrapper, warn, navigate, write, fetchMe, accessToken, hydrate } = await mountPage({
      hash: `#access_token=${ACCESS_TOKEN}&expires_in=900&state=${STATE}&next=/reports`,
      result: { ok: true, tokens: { accessToken: ACCESS_TOKEN, expiresIn: 900 }, next: "/reports" },
    });

    expect(hydrate).toHaveBeenCalled();
    expect(window.location.hash).toBe("");
    expect(accessToken.value).toBe(ACCESS_TOKEN);
    // Empty refresh token, not a copy of identity's: see the note in useSSO.
    expect(write).toHaveBeenCalledWith({ accessToken: ACCESS_TOKEN, refreshToken: "" });
    expect(fetchMe).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith("/reports", { replace: true });

    // Nothing said, nothing logged, no failure UI on the way through.
    expect(warn).not.toHaveBeenCalled();
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
    expect(wrapper.text()).toContain("One moment.");
  });

  it("still lands the session when the /me call fails", async () => {
    const { navigate, write } = await mountPage({
      result: { ok: true, tokens: { accessToken: ACCESS_TOKEN, expiresIn: 900 }, next: "/" },
      fetchMe: async () => {
        throw new Error("network");
      },
    });

    expect(write).toHaveBeenCalledWith({ accessToken: ACCESS_TOKEN, refreshToken: "" });
    expect(navigate).toHaveBeenCalledWith("/", { replace: true });
  });

  it("sends an already signed-in visitor straight on without starting a handoff", async () => {
    const { navigate, startHandoff, warn } = await mountPage({
      query: { start: "1", next: "/reports" },
      storedToken: ACCESS_TOKEN,
    });

    expect(navigate).toHaveBeenCalledWith("/reports", { replace: true });
    expect(startHandoff).not.toHaveBeenCalled();
    expect(warn).not.toHaveBeenCalled();
  });

  it("hands the outbound leg the next path and shows the waiting copy", async () => {
    const { wrapper, startHandoff, warn } = await mountPage({ query: { start: "1", next: "/reports" } });

    expect(startHandoff).toHaveBeenCalledWith("/reports");
    expect(wrapper.text()).toContain("One moment.");
    expect(warn).not.toHaveBeenCalled();
  });
});

describe("sso callback, the legs that do not", () => {
  it("says so when the product has no sso config, instead of quietly landing on next", async () => {
    const { wrapper, navigate, startHandoff, warn } = await mountPage({
      query: { start: "1", next: "/reports" },
      configured: false,
    });

    // The defect this replaces: navigateTo(next), and the product's own guard telling a
    // different story about why.
    expect(navigate).not.toHaveBeenCalled();
    expect(startHandoff).not.toHaveBeenCalled();

    expect(wrapper.get('[role="alert"]').text()).toContain("not configured for this product yet");
    expect(wrapper.text()).toContain("Reason: unconfigured");
    expect(wrapper.text()).toContain("Handoff did not start");
    expect(wrapper.get('a[href="/login"]').text()).toContain("Sign in here instead");

    expect(warn).toHaveBeenCalledTimes(1);
    expect(breadcrumb(warn)).toEqual({
      branch: "outbound:unconfigured",
      reason: "unconfigured",
      configured: false,
      start: true,
      hadSession: false,
    });
  });

  it("shows a reason when startHandoff throws, rather than waiting for ever", async () => {
    const boom = new Error("[@crescent/ui] runtimeConfig.public.ssoReturnAllowlist is not set, so the cross-product sign-in handoff is refused.");
    const { wrapper, navigate, warn } = await mountPage({
      query: { start: "1" },
      startHandoff: () => {
        throw boom;
      },
    });

    expect(wrapper.text()).not.toContain("One moment.");
    expect(wrapper.get('[role="alert"]').text()).toContain("could not hand the sign-in over to identity");
    expect(wrapper.text()).toContain("Reason: handoff-failed");
    expect(navigate).not.toHaveBeenCalled();

    expect(warn).toHaveBeenCalledTimes(1);
    expect(breadcrumb(warn)).toEqual({
      branch: "outbound:threw",
      reason: "handoff-failed",
      configured: true,
      start: true,
      hadSession: false,
      detail: boom.message,
    });
  });

  it("stops waiting when the outbound leg goes nowhere", async () => {
    // setImmediate left alone: flushPromises is built on it.
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const { wrapper, warn } = await mountPage({ query: { start: "1" } });

    expect(wrapper.text()).toContain("One moment.");
    expect(warn).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(STALL_MS);
    await flushPromises();

    expect(wrapper.text()).not.toContain("One moment.");
    expect(wrapper.get('[role="alert"]').text()).toContain("nothing came back");
    expect(wrapper.text()).toContain("Reason: handoff-stalled");
    expect(wrapper.find('a[href="/login"]').exists()).toBe(true);
    expect(breadcrumb(warn).branch).toBe("outbound:stalled");
  });

  it("refuses a handoff this browser did not start, in the same words as before", async () => {
    const { wrapper, navigate } = await mountPage({
      hash: `#access_token=${ACCESS_TOKEN}&state=${STATE}`,
      result: { ok: false, reason: "state-mismatch" },
    });

    expect(wrapper.text()).toContain("Handoff refused");
    expect(wrapper.get('[role="alert"]').text()).toBe(
      "This browser did not start this sign-in, so the token was refused. If you followed a link from a message, ignore it and sign in from the product itself.",
    );
    expect(wrapper.text()).toContain("Reason: state-mismatch");
    expect(navigate).not.toHaveBeenCalled();
  });

  it("names the other refusals and offers a way on from each", async () => {
    const cases: [string, RegExp][] = [
      ["no-handoff", /nothing here to finish/i],
      ["no-token", /without a token/i],
      ["denied", /did not recognise a session/i],
      ["something-new", /did not complete/i],
    ];

    for (const [reason, copy] of cases) {
      const { wrapper, warn } = await mountPage({ result: { ok: false, reason } });
      expect(wrapper.get('[role="alert"]').text()).toMatch(copy);
      expect(wrapper.find('a[href="/login"]').exists()).toBe(true);
      expect(breadcrumb(warn)).toMatchObject({ branch: "return", reason, start: false });
      wrapper.unmount();
    }
  });
});

describe("sso callback breadcrumbs", () => {
  it("never writes token or state material to the console, on any failure path", async () => {
    const paths: MountOptions[] = [
      { query: { start: "1" }, configured: false, hash: `#access_token=${ACCESS_TOKEN}&state=${STATE}` },
      {
        query: { start: "1" },
        hash: `#access_token=${ACCESS_TOKEN}&state=${STATE}`,
        startHandoff: () => {
          throw new Error(`refused for ${window.location.origin}/auth/callback`);
        },
      },
      { hash: `#access_token=${ACCESS_TOKEN}&state=${STATE}`, result: { ok: false, reason: "state-mismatch" } },
      { hash: `#access_token=${ACCESS_TOKEN}&state=${STATE}`, result: { ok: false, reason: "no-token" } },
    ];

    for (const path of paths) {
      const { wrapper, warn } = await mountPage(path);
      expect(warn).toHaveBeenCalledTimes(1);

      const logged = JSON.stringify(warn.mock.calls);
      expect(logged).not.toContain(ACCESS_TOKEN);
      expect(logged).not.toContain(STATE);
      // Nothing of that shape under another name either: no jwt, no long hex blob.
      // ("no-token" is a reason code, so the word itself is not the test.)
      expect(logged).not.toMatch(/[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{8,}/);
      expect(logged).not.toMatch(/[0-9a-f]{16,}/i);

      // The payload is the four inputs plus the branch, and nothing that came off the wire.
      const keys = Object.keys(breadcrumb(warn)).sort();
      expect(keys.filter((key) => !["detail"].includes(key))).toEqual(["branch", "configured", "hadSession", "reason", "start"]);
      wrapper.unmount();
    }
  });
});
