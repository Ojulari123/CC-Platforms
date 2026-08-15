import { describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";
import { IDENTITY_URL, apiError, chrome, installNuxt } from "./pageHarness";

const TOKEN = "rst_9f2c41ba7d0e5817";
const GOOD_PASSWORD = "Correct-Horse-9";

function nextFrame() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

async function mountPage(options: { token?: string | null; fetch?: ReturnType<typeof vi.fn> } = {}) {
  const token = options.token === undefined ? TOKEN : options.token;
  const harness = installNuxt({ query: token === null ? {} : { token }, fetch: options.fetch });
  const Page = (await import("../pages/reset-password.vue")).default;
  const wrapper = mount(Page, { global: { components: chrome } });
  await nextFrame();
  return { harness, wrapper };
}

async function fillAndSubmit(
  wrapper: Awaited<ReturnType<typeof mountPage>>["wrapper"],
  password: string,
  confirm = password,
) {
  await wrapper.get("#reset-pw").setValue(password);
  await wrapper.get("#reset-confirm").setValue(confirm);
  await wrapper.get("form").trigger("submit");
  await nextFrame();
}

// Every dead state has to offer the way back to a fresh link.
function linksToForgot(html: string) {
  return html.includes('href="/forgot-password"');
}

describe("reset-password dead links", () => {
  it("treats a link with no token as unreadable and says so in its own words", async () => {
    const { wrapper } = await mountPage({ token: null });

    const dead = wrapper.get('[data-testid="dead"]');
    expect(dead.text()).toMatch(/this link cannot be read/i);
    expect(dead.get('[role="alert"]').text()).toMatch(/no token in it at all/i);
    expect(linksToForgot(wrapper.html())).toBe(true);
    expect(wrapper.find("#reset-pw").exists()).toBe(false);
  });

  it("separates an expired link from a spent one, with different advice", async () => {
    const expired = await mountPage({
      fetch: vi.fn().mockRejectedValue(apiError(400, "This reset link has expired, so request a new one")),
    });
    await fillAndSubmit(expired.wrapper, GOOD_PASSWORD);

    const expiredText = expired.wrapper.get('[data-testid="dead"]').text();
    expect(expiredText).toMatch(/this link has expired/i);
    expect(expiredText).toMatch(/good for 30 minutes/i);
    expect(linksToForgot(expired.wrapper.html())).toBe(true);

    const used = await mountPage({
      fetch: vi.fn().mockRejectedValue(apiError(400, "Invalid or already-used reset link")),
    });
    await fillAndSubmit(used.wrapper, GOOD_PASSWORD);

    const usedText = used.wrapper.get('[data-testid="dead"]').text();
    expect(usedText).toMatch(/already been used/i);
    expect(linksToForgot(used.wrapper.html())).toBe(true);

    // Three states, three pieces of advice — not one message with three names.
    expect(usedText).not.toBe(expiredText);
    expect(usedText).toMatch(/somebody else may have opened this one/i);
  });

  it("falls back to the unreadable state for a 400 it does not recognise", async () => {
    const { wrapper } = await mountPage({ fetch: vi.fn().mockRejectedValue(apiError(400, "Nope")) });
    await fillAndSubmit(wrapper, GOOD_PASSWORD);

    expect(wrapper.get('[data-testid="dead"]').text()).toMatch(/this link cannot be read/i);
    expect(wrapper.get('[data-testid="dead"]').get('[role="alert"]').text()).toBe("Nope");
  });

  it("never renders the token beyond a truncated fragment", async () => {
    const { wrapper } = await mountPage();
    const html = wrapper.html();

    expect(html).not.toContain(TOKEN);
    expect(wrapper.text()).toContain(`token ${TOKEN.slice(0, 8)}…`);
  });
});

describe("reset-password rules", () => {
  it("holds a password that misses a rule back from the network", async () => {
    const { harness, wrapper } = await mountPage();
    await fillAndSubmit(wrapper, "alllowercase");

    expect(harness.fetch).not.toHaveBeenCalled();
    expect(wrapper.get("#reset-pw-err").text()).toMatch(/does not meet the rules/i);
    expect(wrapper.get("#reset-pw").attributes("aria-invalid")).toBe("true");
    expect(wrapper.get("#reset-pw").attributes("aria-describedby")).toBe("reset-pw-err reset-pw-rules");
  });

  it("holds a mismatched confirmation back from the network", async () => {
    const { harness, wrapper } = await mountPage();
    await fillAndSubmit(wrapper, GOOD_PASSWORD, `${GOOD_PASSWORD}x`);

    expect(harness.fetch).not.toHaveBeenCalled();
    expect(wrapper.get("#reset-confirm-err").text()).toMatch(/do not match/i);
  });

  it("shows each rule as it is met", async () => {
    const { wrapper } = await mountPage();
    const rules = () => wrapper.findAll("#reset-pw-rules li");

    const met = () => rules().filter((li) => li.text().includes("— met"));

    expect(rules()).toHaveLength(5);
    // Nothing is claimed as done before anything has been typed.
    expect(met()).toHaveLength(0);

    await wrapper.get("#reset-pw").setValue(GOOD_PASSWORD);
    expect(met()).toHaveLength(5);
  });

  it("sends the token with the new password, then clears the token from the address bar", async () => {
    const { harness, wrapper } = await mountPage();
    await fillAndSubmit(wrapper, GOOD_PASSWORD);

    expect(harness.fetch).toHaveBeenCalledWith(`${IDENTITY_URL}/auth/reset-password`, {
      method: "POST",
      body: { token: TOKEN, new_password: GOOD_PASSWORD },
    });
    expect(harness.replace).toHaveBeenCalledWith({ query: {} });
    expect(wrapper.text()).toMatch(/password changed/i);
    expect(wrapper.text()).toMatch(/every session on the account was revoked/i);
    expect(wrapper.find("#reset-pw").exists()).toBe(false);
  });

  it("keeps a server-side password complaint inline instead of killing the link", async () => {
    const { wrapper } = await mountPage({
      fetch: vi.fn().mockRejectedValue(apiError(400, "Password must contain a number")),
    });
    await fillAndSubmit(wrapper, GOOD_PASSWORD);

    expect(wrapper.find('[data-testid="dead"]').exists()).toBe(false);
    expect(wrapper.text()).toContain("Password must contain a number");
    expect(wrapper.find("#reset-pw").exists()).toBe(true);
  });

  it("asks the browser for a new password, never the current one", async () => {
    const { wrapper } = await mountPage();

    expect(wrapper.get("#reset-pw").attributes("autocomplete")).toBe("new-password");
    expect(wrapper.get("#reset-pw").attributes("type")).toBe("password");
    expect(wrapper.get("#reset-confirm").attributes("autocomplete")).toBe("new-password");
    expect(wrapper.find('label[for="reset-pw"]').exists()).toBe(true);
    expect(wrapper.find('label[for="reset-confirm"]').exists()).toBe(true);
  });
});
