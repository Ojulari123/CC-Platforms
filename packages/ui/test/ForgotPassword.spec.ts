import { describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";
import { IDENTITY_URL, apiError, chrome, installNuxt } from "./pageHarness";

// The page is imported after the harness has put Nuxt's auto-imports on globalThis.
async function mountPage(harnessFetch?: ReturnType<typeof vi.fn>) {
  const harness = installNuxt({ fetch: harnessFetch });
  const Page = (await import("../pages/forgot-password.vue")).default;
  const wrapper = mount(Page, { global: { components: chrome } });
  await nextFrame();
  return { harness, wrapper };
}

function nextFrame() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

async function send(wrapper: Awaited<ReturnType<typeof mountPage>>["wrapper"], email: string) {
  await wrapper.get("#forgot-email").setValue(email);
  await wrapper.get("form").trigger("submit");
  await nextFrame();
}

describe("forgot-password", () => {
  it("posts the address to identity and confirms without saying whether it has an account", async () => {
    const { harness, wrapper } = await mountPage();
    await send(wrapper, "temi@cyphercrescent.com");

    expect(harness.fetch).toHaveBeenCalledWith(`${IDENTITY_URL}/auth/forgot-password`, {
      method: "POST",
      body: { email: "temi@cyphercrescent.com" },
    });

    const text = wrapper.text();
    expect(text).toMatch(/if that address has an account/i);
    // The expiry the service actually enforces: PASSWORD_RESET_EXPIRE_MINUTES = 30.
    expect(text).toMatch(/30 minutes/);
    // Nothing that would let someone read an account's existence off the screen.
    expect(text).not.toMatch(/no account|not registered|does not exist|unknown address|never signed up/i);
    expect(wrapper.find("#forgot-email").exists()).toBe(false);
  });

  it("says the same thing for an address that has an account and one that does not", async () => {
    // Identity answers 204 either way, so both runs take the same branch — the assertion
    // is that the screen adds no signal of its own on top of that.
    const first = await mountPage();
    await send(first.wrapper, "known@cyphercrescent.com");
    const second = await mountPage();
    await send(second.wrapper, "nobody@cyphercrescent.com");

    const strip = (html: string) => html.replace(/known@cyphercrescent\.com|nobody@cyphercrescent\.com/g, "ADDRESS");
    expect(strip(first.wrapper.html())).toBe(strip(second.wrapper.html()));
  });

  it("refuses an invalid address before it reaches the network", async () => {
    const { harness, wrapper } = await mountPage();
    await send(wrapper, "not-an-email");

    expect(harness.fetch).not.toHaveBeenCalled();
    const alert = wrapper.get('[role="alert"]');
    expect(alert.text()).toMatch(/not a valid email address/i);
    expect(wrapper.get("#forgot-email").attributes("aria-invalid")).toBe("true");
    expect(wrapper.get("#forgot-email").attributes("aria-describedby")).toBe("forgot-email-err");
  });

  it("keeps the form up and explains the wait when identity rate-limits the route", async () => {
    const fetch = vi.fn().mockRejectedValue(apiError(429));
    const { wrapper } = await mountPage(fetch);
    await send(wrapper, "temi@cyphercrescent.com");

    expect(wrapper.get('[role="alert"]').text()).toMatch(/wait a minute/i);
    // Still the form, not the confirmation: nothing was sent.
    expect(wrapper.find("#forgot-email").exists()).toBe(true);
    expect(wrapper.text()).not.toMatch(/if that address has an account/i);
  });

  it("labels the field and marks the submit busy while the request is out", async () => {
    const { wrapper } = await mountPage();
    const field = wrapper.get("#forgot-email");
    expect(wrapper.find('label[for="forgot-email"]').exists()).toBe(true);
    expect(field.attributes("type")).toBe("email");
    expect(field.attributes("autocomplete")).toBe("email");
    expect(field.attributes("aria-describedby")).toBe("forgot-email-hint");

    const button = wrapper.get('button[type="submit"]');
    expect(button.attributes("aria-busy")).toBeUndefined();
  });
});
