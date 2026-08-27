import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import { computed, onMounted, ref } from "vue";
import Cross from "@crescent/ui/components/Cross.vue";
import Eyebrow from "@crescent/ui/components/Eyebrow.vue";
import Icon from "@crescent/ui/components/Icon.vue";
import Mark from "@crescent/ui/components/Mark.vue";
import RuleTicks from "@crescent/ui/components/RuleTicks.vue";
import RulerStrip from "@crescent/ui/components/RulerStrip.vue";
import StatusDot from "@crescent/ui/components/StatusDot.vue";
import TopBar from "@crescent/ui/components/TopBar.vue";
import { handoffPath } from "~/pages/login.vue";

/* The one way into Forge. Signing in and creating an account both happen at identity, so
   this page is a handoff and nothing else: no form, no password field, no credential ever
   passing through Forge. The tests below hold it that way.

   Mounting a Nuxt page outside Nuxt: the pages carry no imports for `ref`, `useAuth` and
   friends because Nuxt injects them, and unresolved identifiers in compiled SFC code fall
   through to globalThis — so putting them there runs the real page rather than a copy. */

const chrome = { Cross, Eyebrow, Icon, Mark, RuleTicks, RulerStrip, StatusDot, TopBar };

interface HarnessOptions {
  authenticated?: boolean;
  query?: Record<string, unknown>;
}

function installNuxt(options: HarnessOptions = {}) {
  const g = globalThis as Record<string, unknown>;

  g.ref = ref;
  g.computed = computed;
  g.onMounted = onMounted;
  g.definePageMeta = () => {};
  g.useHead = () => {};
  g.useRuntimeConfig = () => ({ public: { identityWebUrl: "http://localhost:3002" } });

  const push = vi.fn(async () => undefined);
  const replace = vi.fn(async () => undefined);
  const hydrate = vi.fn();
  const announce = vi.fn();

  g.useRoute = () => ({ query: options.query ?? {} });
  g.useRouter = () => ({ push, replace });
  g.useAnnounce = () => announce;
  g.useAuth = () => ({
    hydrate,
    isAuthenticated: computed(() => options.authenticated ?? false),
  });

  return { push, replace, hydrate, announce };
}

function settle() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

async function mountPage(options: HarnessOptions = {}) {
  const harness = installNuxt(options);
  const Page = (await import("../pages/login.vue")).default;
  const wrapper = mount(Page, { global: { components: chrome } });
  await settle();
  return { harness, wrapper };
}

describe("the handoff to identity", () => {
  it("starts from the callback the layer ships, which is the address on Forge's allowlist", () => {
    expect(handoffPath("/")).toBe("/auth/callback?start=1&next=%2F");
    expect(handoffPath("/datasets/4")).toBe("/auth/callback?start=1&next=%2Fdatasets%2F4");
  });

  it.each(["https://evil.example/steal", "//evil.example", "/\\evil.example", ""])(
    "refuses to carry %s out of the app",
    (next) => {
      expect(handoffPath(next)).toBe("/auth/callback?start=1&next=%2F");
    },
  );

  it("is the leading control on the screen, and it is a link rather than a button", async () => {
    const { wrapper } = await mountPage();
    const cta = wrapper.get('a[href^="/auth/callback"]');
    expect(cta.attributes("href")).toBe("/auth/callback?start=1&next=%2F");
    expect(cta.text()).toMatch(/Meridian/);
    // Primary surface: near-white on the app colour, never a coloured fill.
    expect(cta.classes()).toContain("bg-ink");
    expect(cta.classes()).toContain("text-app");
  });

  it("carries a requested destination through the handoff", async () => {
    const { wrapper } = await mountPage({ query: { next: "/datasets" } });
    expect(wrapper.get('a[href^="/auth/callback"]').attributes("href")).toBe(
      "/auth/callback?start=1&next=%2Fdatasets",
    );
  });
});

describe("sign-in is the handoff and nothing else", () => {
  it("offers no password path at all: no form, no password field, no credential submit", async () => {
    const { wrapper } = await mountPage();

    expect(wrapper.find("form").exists()).toBe(false);
    expect(wrapper.find('input[type="password"]').exists()).toBe(false);
    expect(wrapper.findAll("input")).toHaveLength(0);
    expect(wrapper.find('button[type="submit"]').exists()).toBe(false);
    expect(wrapper.find('a[href="/forgot-password"]').exists()).toBe(false);
    // The one control that starts a sign-in is the handoff to identity.
    expect(wrapper.findAll('a[href^="/auth/callback"]')).toHaveLength(1);
  });

  it("points a stuck signer-in at identity's own screen rather than a form here", async () => {
    const { wrapper } = await mountPage();
    expect(wrapper.get('a[href="http://localhost:3002/login"]').text()).toBe("Sign in at Meridian");
  });

  it("names the destination it was asked for", async () => {
    const { wrapper } = await mountPage({ query: { next: "/datasets" } });
    expect(wrapper.text()).toContain("continuing to /datasets");
  });

  it("sends a browser that already holds a session straight on", async () => {
    const { harness } = await mountPage({ authenticated: true });
    expect(harness.hydrate).toHaveBeenCalled();
    expect(harness.replace).toHaveBeenCalledWith("/");
  });
});

describe("the shape this screen has to keep", () => {
  it("has exactly one h1, a skip link and a main to skip to", async () => {
    const { wrapper } = await mountPage();
    expect(wrapper.findAll("h1")).toHaveLength(1);
    expect(wrapper.get('a[href="#main"]').text()).toBe("Skip to content");
    expect(wrapper.find("main#main").exists()).toBe(true);
  });

  it("sends someone without an account to identity, not to a form here", async () => {
    const { wrapper } = await mountPage();
    const create = wrapper.findAll('a[href="http://localhost:3002/login?mode=signup"]');
    expect(create.length).toBeGreaterThan(0);
    expect(create.some((a) => a.text().includes("Create one at Meridian"))).toBe(true);
    expect(wrapper.find('a[href="/signup"]').exists()).toBe(false);
  });
});
