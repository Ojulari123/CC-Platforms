import { mount } from "@vue/test-utils";
import type { VueWrapper } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import { computed, nextTick, onMounted, ref } from "vue";
import Btn from "@crescent/ui/components/Btn.vue";
import Cross from "@crescent/ui/components/Cross.vue";
import Eyebrow from "@crescent/ui/components/Eyebrow.vue";
import Icon from "@crescent/ui/components/Icon.vue";
import Mark from "@crescent/ui/components/Mark.vue";
import PasswordField from "@crescent/ui/components/PasswordField.vue";
import RuleTicks from "@crescent/ui/components/RuleTicks.vue";
import RulerStrip from "@crescent/ui/components/RulerStrip.vue";
import StatusDot from "@crescent/ui/components/StatusDot.vue";
import TopBar from "@crescent/ui/components/TopBar.vue";
import { usePasswordRules } from "@crescent/ui/composables/usePasswordRules";
import { emailError, handoffPath, passwordError, signInMessage } from "~/pages/login.vue";
import { isEmailTaken, nameError, signUpMessage } from "~/pages/signup.vue";

/* The two ways into Forge. The pure rules are imported straight off the pages; the error
   and busy states are asserted on the mounted page, because "the button says Checking and
   cannot be pressed twice" is not something a pure function can be asked about.

   Mounting a Nuxt page outside Nuxt: the pages carry no imports for `ref`, `useAuth` and
   friends because Nuxt injects them, and unresolved identifiers in compiled SFC code fall
   through to globalThis — so putting them there runs the real page rather than a copy. */

const chrome = { Btn, Cross, Eyebrow, Icon, Mark, PasswordField, RuleTicks, RulerStrip, StatusDot, TopBar };

interface HarnessOptions {
  authenticated?: boolean;
  login?: ReturnType<typeof vi.fn>;
  signup?: ReturnType<typeof vi.fn>;
  query?: Record<string, unknown>;
}

function installNuxt(options: HarnessOptions = {}) {
  const g = globalThis as Record<string, unknown>;

  g.ref = ref;
  g.computed = computed;
  g.onMounted = onMounted;
  g.usePasswordRules = usePasswordRules;
  g.definePageMeta = () => {};
  g.useHead = () => {};

  const login = options.login ?? vi.fn(async () => undefined);
  const signup = options.signup ?? vi.fn(async () => undefined);
  const push = vi.fn(async () => undefined);
  const replace = vi.fn(async () => undefined);
  const hydrate = vi.fn();
  const announce = vi.fn();

  g.useRoute = () => ({ query: options.query ?? {} });
  g.useRouter = () => ({ push, replace });
  g.useAnnounce = () => announce;
  g.useAuth = () => ({
    hydrate,
    login,
    signup,
    isAuthenticated: computed(() => options.authenticated ?? false),
  });

  return { login, signup, push, replace, hydrate, announce };
}

function settle() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

async function mountPage(name: "login" | "signup", options: HarnessOptions = {}) {
  const harness = installNuxt(options);
  const Page = (await import(`../pages/${name}.vue`)).default;
  const wrapper = mount(Page, { global: { components: chrome } });
  await settle();
  return { harness, wrapper };
}

/** ofetch reports a failure with the status on the error itself. */
function apiError(status: number, detail?: string) {
  return Object.assign(new Error(`HTTP ${status}`), {
    status,
    statusCode: status,
    data: detail ? { detail } : undefined,
  });
}

async function fill(wrapper: VueWrapper, values: Record<string, string>) {
  for (const [selector, value] of Object.entries(values)) {
    await wrapper.get(selector).setValue(value);
  }
}

async function submit(wrapper: VueWrapper) {
  await wrapper.get("form").trigger("submit");
  await settle();
}

describe("sign-in validation", () => {
  it("asks for an address before it complains about the shape of one", () => {
    expect(emailError("")).toBe("Enter your work email.");
  });

  it.each(["nope", "no@dots", "@cyphercrescent.com", "two @spaces.com"])("rejects %s", (value) => {
    expect(emailError(value)).toBe("That is not a valid email address.");
  });

  it("accepts a work address", () => {
    expect(emailError("oj.demo@cyphercrescent.com")).toBeNull();
  });

  it("holds sign-in to the length only, because identity decides the rest", () => {
    expect(passwordError("short")).toBe("Password must be at least 8 characters.");
    expect(passwordError("Meridian!2026")).toBeNull();
  });

  it("requires both names when creating an account", () => {
    expect(nameError("   ", "first name")).toBe("A first name is required.");
    expect(nameError("Ada", "first name")).toBeNull();
  });
});

describe("what the screen says when identity refuses", () => {
  it("gives one message for a wrong address and a wrong password", () => {
    expect(signInMessage(apiError(401, "Invalid credentials"))).toBe(
      "That email and password do not match an account.",
    );
  });

  it("explains a deactivated account rather than blaming the password", () => {
    expect(signInMessage(apiError(403))).toContain("deactivated");
  });

  it("names the rate limit on both screens", () => {
    expect(signInMessage(apiError(429))).toContain("Too many attempts");
    expect(signUpMessage(apiError(429))).toContain("Too many attempts");
  });

  it("falls back to naming the service when there is no status at all", () => {
    expect(signInMessage(new Error("Failed to fetch"))).toContain("identity service");
    expect(signUpMessage(new Error("Failed to fetch"))).toContain("identity service");
  });

  it("passes identity's own reason through on the refusals that carry one", () => {
    expect(signUpMessage(apiError(403, "Only @cyphercrescent.com addresses"))).toBe(
      "Only @cyphercrescent.com addresses",
    );
    expect(signUpMessage(apiError(400, "Password must contain a symbol"))).toBe("Password must contain a symbol");
    expect(signUpMessage(apiError(422))).toBe("Check the details above and try again.");
  });

  it("marks a 409, and only a 409, as an address that already has an account", () => {
    expect(isEmailTaken(apiError(409))).toBe(true);
    expect(isEmailTaken(apiError(400))).toBe(false);
  });
});

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

  it("is the leading control on both screens, and it is a link rather than a button", async () => {
    for (const name of ["login", "signup"] as const) {
      const { wrapper } = await mountPage(name);
      const cta = wrapper.get('a[href^="/auth/callback"]');
      expect(cta.attributes("href")).toBe("/auth/callback?start=1&next=%2F");
      expect(cta.text()).toMatch(/Meridian/);
      // Primary surface: near-white on the app colour, never a coloured fill.
      expect(cta.classes()).toContain("bg-ink");
      expect(cta.classes()).toContain("text-app");
    }
  });

  it("carries a requested destination through the handoff", async () => {
    const { wrapper } = await mountPage("login", { query: { next: "/datasets" } });
    expect(wrapper.get('a[href^="/auth/callback"]').attributes("href")).toBe(
      "/auth/callback?start=1&next=%2Fdatasets",
    );
  });
});

describe("the sign-in form", () => {
  it("keeps a bad address off the network and names the field", async () => {
    const { harness, wrapper } = await mountPage("login");
    await fill(wrapper, { "#signin-email": "not-an-email", "#signin-password": "Meridian!2026" });
    await submit(wrapper);

    expect(harness.login).not.toHaveBeenCalled();
    const field = wrapper.get("#signin-email");
    expect(field.attributes("aria-invalid")).toBe("true");
    expect(field.attributes("aria-describedby")).toBe("signin-email-err");
    expect(wrapper.get("#signin-email-err").attributes("role")).toBe("alert");
    expect(wrapper.get("#signin-email-err").text()).toBe("That is not a valid email address.");
  });

  it("posts the trimmed address to identity and moves on", async () => {
    const { harness, wrapper } = await mountPage("login");
    await fill(wrapper, { "#signin-email": "  oj.demo@cyphercrescent.com ", "#signin-password": "Meridian!2026" });
    await submit(wrapper);

    expect(harness.login).toHaveBeenCalledWith("oj.demo@cyphercrescent.com", "Meridian!2026");
    expect(harness.announce).toHaveBeenCalledWith("Signed in.");
    expect(harness.push).toHaveBeenCalledWith("/");
  });

  it("shows identity's refusal in a live region and keeps the form up", async () => {
    const login = vi.fn().mockRejectedValue(apiError(401));
    const { wrapper } = await mountPage("login", { login });
    await fill(wrapper, { "#signin-email": "oj.demo@cyphercrescent.com", "#signin-password": "wrongpassword" });
    await submit(wrapper);

    const alerts = wrapper.findAll('[role="alert"]');
    const texts = alerts.map((a) => a.text());
    expect(texts).toContain("That email and password do not match an account.");
    expect(wrapper.find("#signin-email").exists()).toBe(true);
    // Nothing in the refusal that would let someone read an account's existence off it.
    expect(texts.join(" ")).not.toMatch(/not registered|unknown address|never signed up|wrong password/i);
  });

  it("wears the busy hairline while identity is thinking and cannot be submitted twice", async () => {
    let release!: () => void;
    const login = vi.fn(() => new Promise<void>((resolve) => (release = resolve)));
    const { wrapper } = await mountPage("login", { login });
    await fill(wrapper, { "#signin-email": "oj.demo@cyphercrescent.com", "#signin-password": "Meridian!2026" });

    await wrapper.get("form").trigger("submit");
    await nextTick();

    const button = wrapper.get('button[type="submit"]');
    expect(button.text()).toBe("Checking…");
    expect(button.classes()).toContain("btn-busy");
    expect(button.attributes("aria-busy")).toBe("true");
    expect(button.attributes("disabled")).toBeDefined();

    await wrapper.get("form").trigger("submit");
    expect(login).toHaveBeenCalledTimes(1);

    release();
    await settle();
    expect(wrapper.get('button[type="submit"]').classes()).not.toContain("btn-busy");
  });

  it("carries a requested destination into the redirect", async () => {
    const { harness, wrapper } = await mountPage("login", { query: { next: "/datasets" } });
    await fill(wrapper, { "#signin-email": "oj.demo@cyphercrescent.com", "#signin-password": "Meridian!2026" });
    await submit(wrapper);
    expect(harness.push).toHaveBeenCalledWith("/datasets");
  });

  it("sends a browser that already holds a session straight on", async () => {
    const { harness } = await mountPage("login", { authenticated: true });
    expect(harness.hydrate).toHaveBeenCalled();
    expect(harness.replace).toHaveBeenCalledWith("/");
  });
});

describe("the create-account form", () => {
  it("refuses a password that misses identity's rules and points at the list", async () => {
    const { harness, wrapper } = await mountPage("signup");
    await fill(wrapper, {
      "#signup-first": "Ada",
      "#signup-last": "Nwosu",
      "#signup-email": "ada@cyphercrescent.com",
      "#signup-password": "lowercase",
    });
    await submit(wrapper);

    expect(harness.signup).not.toHaveBeenCalled();
    const field = wrapper.get("#signup-password");
    expect(field.attributes("aria-invalid")).toBe("true");
    expect(field.attributes("aria-describedby")).toBe("signup-password-err signup-password-rules");
    expect(wrapper.get("#signup-password-err").text()).toBe("That password does not meet the rules below yet.");
  });

  it("ticks each of identity's rules off as the password satisfies it", async () => {
    const { wrapper } = await mountPage("signup");
    const rules = () => wrapper.findAll("#signup-password-rules li");

    // "short" has a lowercase letter; the other four fail.
    await fill(wrapper, { "#signup-password": "short" });
    expect(rules().filter((li) => li.text().includes("— met"))).toHaveLength(1);

    await fill(wrapper, { "#signup-password": "Meridian!2026" });
    expect(rules()).toHaveLength(5);
    expect(rules().every((li) => li.text().includes("— met"))).toBe(true);
  });

  it("sends the four fields identity's signup takes, trimmed", async () => {
    const { harness, wrapper } = await mountPage("signup");
    await fill(wrapper, {
      "#signup-first": " Ada ",
      "#signup-last": " Nwosu ",
      "#signup-email": " ada@cyphercrescent.com ",
      "#signup-password": "Meridian!2026",
    });
    await submit(wrapper);

    expect(harness.signup).toHaveBeenCalledWith({
      first_name: "Ada",
      last_name: "Nwosu",
      email: "ada@cyphercrescent.com",
      password: "Meridian!2026",
    });
    expect(harness.push).toHaveBeenCalledWith("/");
  });

  it("offers the way out of a taken address, and only for that refusal", async () => {
    const taken = await mountPage("signup", { signup: vi.fn().mockRejectedValue(apiError(409)) });
    await fill(taken.wrapper, {
      "#signup-first": "Ada",
      "#signup-last": "Nwosu",
      "#signup-email": "ada@cyphercrescent.com",
      "#signup-password": "Meridian!2026",
    });
    await submit(taken.wrapper);

    const alert = taken.wrapper.get('[role="alert"]');
    expect(alert.text()).toContain("An account with that email already exists.");
    expect(alert.get('a[href="/login"]').text()).toBe("Sign in instead");

    const domain = await mountPage("signup", { signup: vi.fn().mockRejectedValue(apiError(403)) });
    await fill(domain.wrapper, {
      "#signup-first": "Ada",
      "#signup-last": "Nwosu",
      "#signup-email": "ada@elsewhere.com",
      "#signup-password": "Meridian!2026",
    });
    await submit(domain.wrapper);

    const refusal = domain.wrapper.get('[role="alert"]');
    expect(refusal.text()).toContain("Sign-ups aren't open to that email domain.");
    expect(refusal.find('a[href="/login"]').exists()).toBe(false);
  });

  it("wears the busy hairline while the account is being created", async () => {
    let release!: () => void;
    const signup = vi.fn(() => new Promise<void>((resolve) => (release = resolve)));
    const { wrapper } = await mountPage("signup", { signup });
    await fill(wrapper, {
      "#signup-first": "Ada",
      "#signup-last": "Nwosu",
      "#signup-email": "ada@cyphercrescent.com",
      "#signup-password": "Meridian!2026",
    });

    await wrapper.get("form").trigger("submit");
    await nextTick();

    const button = wrapper.get('button[type="submit"]');
    expect(button.text()).toBe("Creating…");
    expect(button.classes()).toContain("btn-busy");
    expect(button.attributes("disabled")).toBeDefined();

    release();
    await settle();
    expect(wrapper.get('button[type="submit"]').text()).toBe("Create account with a password");
  });
});

describe("the shape both screens have to keep", () => {
  it("has exactly one h1, a skip link and a main to skip to", async () => {
    for (const name of ["login", "signup"] as const) {
      const { wrapper } = await mountPage(name);
      expect(wrapper.findAll("h1")).toHaveLength(1);
      expect(wrapper.get('a[href="#main"]').text()).toBe("Skip to content");
      expect(wrapper.find("main#main").exists()).toBe(true);
    }
  });

  it("labels every field and asks the browser for the right autofill", async () => {
    const login = await mountPage("login");
    expect(login.wrapper.get('label[for="signin-email"]').text()).toBe("Work email");
    expect(login.wrapper.get("#signin-email").attributes("autocomplete")).toBe("email");
    expect(login.wrapper.get("#signin-password").attributes("autocomplete")).toBe("current-password");
    expect(login.wrapper.get("#signin-password").attributes("type")).toBe("password");

    const signup = await mountPage("signup");
    expect(signup.wrapper.get('label[for="signup-first"]').text()).toBe("First name");
    expect(signup.wrapper.get("#signup-password").attributes("autocomplete")).toBe("new-password");
    expect(signup.wrapper.get("#signup-first").attributes("autocomplete")).toBe("given-name");
  });

  it("does not pop a keyboard open on a touch screen", async () => {
    const matchMedia = vi.fn(() => ({ matches: true }) as unknown as MediaQueryList);
    vi.stubGlobal("matchMedia", matchMedia);
    const { wrapper } = await mountPage("login");

    expect(matchMedia).toHaveBeenCalledWith("(pointer: coarse)");
    expect(document.activeElement).not.toBe(wrapper.get("#signin-email").element);
    vi.unstubAllGlobals();
  });
});
