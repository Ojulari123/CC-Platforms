import { describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";
import { IDENTITY_URL, apiError, chrome, deferred, installNuxt } from "./pageHarness";

const TOKEN = "inv_7c1d9a44be20f3";

function previewBody(overrides: Record<string, unknown> = {}) {
  return {
    email: "temi.balogun@cyphercrescent.com",
    dept_name: "Engineering",
    team_name: null,
    role: "engineer",
    needs_account: true,
    invited_by_name: "Ada Okoro",
    // Two days out, so the label is a distance rather than a date.
    expires_at: new Date(Date.now() + 48 * 3600 * 1000).toISOString(),
    ...overrides,
  };
}

function nextFrame() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

async function mountPage(options: { token?: string | null; fetch?: ReturnType<typeof vi.fn> } = {}) {
  const token = options.token === undefined ? TOKEN : options.token;
  const harness = installNuxt({ query: token === null ? {} : { token }, fetch: options.fetch });
  const Page = (await import("../pages/invites/accept.vue")).default;
  const wrapper = mount(Page, { global: { components: chrome } });
  await nextFrame();
  return { harness, wrapper };
}

describe("invite acceptance sequencing", () => {
  it("waits for the preview before offering a form, then shows what is being joined first", async () => {
    const pending = deferred<unknown>();
    const fetch = vi.fn().mockReturnValue(pending.promise);
    const { wrapper } = await mountPage({ fetch });

    // Mid-flight: the check is announced and nothing is typeable yet.
    expect(wrapper.find('[data-testid="checking"]').exists()).toBe(true);
    expect(wrapper.findAll("input")).toHaveLength(0);
    expect(fetch).toHaveBeenCalledWith(`${IDENTITY_URL}/invites/preview`, { query: { token: TOKEN } });

    pending.resolve(previewBody());
    await nextFrame();

    const facts = wrapper.get('[data-testid="invite-facts"]');
    const factText = facts.text();
    expect(factText).toContain("temi.balogun@cyphercrescent.com");
    expect(factText).toContain("Engineering");
    // Both fields GET /invites/preview grew recently.
    expect(factText).toContain("Ada Okoro");
    expect(factText).toMatch(/in 48 hours|in 2 days/);

    // The read-back sits ahead of the first input in the document, not beside it.
    const html = wrapper.html();
    expect(html.indexOf('data-testid="invite-facts"')).toBeLessThan(html.indexOf('id="invite-first"'));
    expect(wrapper.find('[data-testid="invite-form"]').exists()).toBe(true);
  });

  it("asks for nothing but the button when the address already has an account", async () => {
    const fetch = vi.fn().mockResolvedValue(previewBody({ needs_account: false, team_name: "Platform" }));
    const { wrapper } = await mountPage({ fetch });

    expect(wrapper.findAll("input")).toHaveLength(0);
    expect(wrapper.get('button[type="submit"]').text()).toContain("Accept invitation");
    expect(wrapper.get('[data-testid="invite-facts"]').text()).toContain("Platform");
  });

  it("sends the names and password with the token, then adopts the session it gets back", async () => {
    const pair = { access_token: "a", refresh_token: "r", token_type: "bearer", expires_in: 900, user: {} };
    const fetch = vi.fn()
      .mockResolvedValueOnce(previewBody())
      .mockResolvedValueOnce(pair);
    const { harness, wrapper } = await mountPage({ fetch });

    await wrapper.get("#invite-first").setValue("Temi");
    await wrapper.get("#invite-last").setValue("Balogun");
    await wrapper.get("#invite-pw").setValue("Correct-Horse-9");
    await wrapper.get("form").trigger("submit");
    await nextFrame();

    expect(fetch).toHaveBeenLastCalledWith(`${IDENTITY_URL}/invites/accept`, {
      method: "POST",
      body: { token: TOKEN, first_name: "Temi", last_name: "Balogun", password: "Correct-Horse-9" },
    });
    expect(harness.adoptSession).toHaveBeenCalledWith(pair);
    expect(harness.replace).toHaveBeenCalledWith("/");
  });

  it("holds an incomplete form back from the network", async () => {
    const fetch = vi.fn().mockResolvedValue(previewBody());
    const { wrapper } = await mountPage({ fetch });

    await wrapper.get("#invite-pw").setValue("short");
    await wrapper.get("form").trigger("submit");
    await nextFrame();

    expect(fetch).toHaveBeenCalledTimes(1); // the preview, and nothing since
    expect(wrapper.get("#invite-first-err").text()).toMatch(/enter your first name/i);
    expect(wrapper.get("#invite-pw-err").text()).toMatch(/does not meet the rules/i);
    expect(wrapper.get("#invite-pw").attributes("aria-describedby")).toBe("invite-pw-err invite-pw-rules");
  });
});

describe("invite dead states", () => {
  const cases: [string, string, RegExp, RegExp][] = [
    ["invalid", "Invalid invite link", /cannot be read/i, /open the link straight from the email/i],
    ["expired", "This invite has expired, so ask for a new one", /has expired/i, /invite you again/i],
    ["used", "This invite has already been used", /already been used/i, /tell your department admin/i],
  ];

  it.each(cases)("tells %s apart from the others", async (_kind, detail, headline, advice) => {
    const { wrapper } = await mountPage({ fetch: vi.fn().mockRejectedValue(apiError(400, detail)) });

    const dead = wrapper.get('[data-testid="dead"]');
    expect(dead.text()).toMatch(headline);
    expect(dead.text()).toMatch(advice);
    expect(wrapper.find('[data-testid="invite-form"]').exists()).toBe(false);
    expect(wrapper.findAll("input")).toHaveLength(0);
  });

  it("treats a link with no token as unreadable in its own words", async () => {
    const { harness, wrapper } = await mountPage({ token: null });

    expect(harness.fetch).not.toHaveBeenCalled();
    expect(wrapper.get('[data-testid="dead"]').get('[role="alert"]').text()).toMatch(/no token in it at all/i);
  });

  it("closes the invitation when identity says the membership is already there", async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(previewBody({ needs_account: false }))
      .mockRejectedValueOnce(apiError(409, "You're already a member of this department."));
    const { wrapper } = await mountPage({ fetch });

    await wrapper.get("form").trigger("submit");
    await nextFrame();

    const dead = wrapper.get('[data-testid="dead"]');
    expect(dead.text()).toMatch(/already been used/i);
    expect(dead.get('[role="alert"]').text()).toContain("already a member of this department");
  });

  it("never renders the invite token beyond a truncated fragment", async () => {
    const { wrapper } = await mountPage({ fetch: vi.fn().mockResolvedValue(previewBody()) });

    expect(wrapper.html()).not.toContain(TOKEN);
    expect(wrapper.text()).toContain(`invite ${TOKEN.slice(0, 8)}…`);
  });
});
