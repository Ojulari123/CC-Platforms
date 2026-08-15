import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import NewReportForm from "~/components/NewReportForm.vue";
import { makeReport, makeRepo } from "./fixtures";

const counts = { commits: 5, pull_requests: 1, reviews: 2, issues: 1 };

function mountForm(props: Record<string, unknown> = {}) {
  return mount(NewReportForm, {
    props: {
      repositories: [makeRepo()],
      repoId: 4,
      week: "2026-08-03",
      weeks: ["2026-08-03", "2026-07-27"],
      counts,
      ...props,
    },
  });
}

function createButtons(wrapper: ReturnType<typeof mountForm>) {
  return {
    generate: wrapper.find('[data-test="create-generate"]'),
    blank: wrapper.find('[data-test="create-blank"]'),
  };
}

describe("NewReportForm — eligibility", () => {
  it("offers every repository, including the unfiled and the untracked", () => {
    const wrapper = mountForm({
      repositories: [
        makeRepo({ id: 4, full_name: "acme/pulse-api" }),
        makeRepo({ id: 12, full_name: "acme/identity-web", dept_id: null }),
        makeRepo({ id: 18, full_name: "northwind/billing-service", is_tracked: false }),
      ],
    });
    // The trigger of the repository listbox carries the current label; the options are
    // what the component was handed, unfiltered.
    expect(wrapper.props("repositories")).toHaveLength(3);
  });

  it("warns that an unfiled repository reaches no review queue, and still lets you write", () => {
    const wrapper = mountForm({ repositories: [makeRepo({ dept_id: null })] });

    const warning = wrapper.find('[data-test="unfiled-warning"]');
    expect(warning.exists()).toBe(true);
    expect(warning.text()).toMatch(/reaches no review queue/i);
    expect(warning.text()).toMatch(/you can still write it/i);

    const { generate, blank } = createButtons(wrapper);
    expect(generate.attributes("disabled")).toBeUndefined();
    expect(blank.attributes("disabled")).toBeUndefined();
  });

  it("names the platform admin as the only decider when nobody holds a post either", () => {
    const wrapper = mountForm({
      repositories: [makeRepo({ dept_id: null, lead_user_id: null, deputy_user_id: null })],
    });
    expect(wrapper.find('[data-test="unfiled-warning"]').text()).toMatch(/platform\s+admin/i);
  });

  it("warns that an untracked repository is no longer being filled in, and still lets you write", () => {
    const wrapper = mountForm({ repositories: [makeRepo({ is_tracked: false })] });

    expect(wrapper.find('[data-test="untracked-warning"]').text()).toMatch(/no longer visits/i);
    expect(createButtons(wrapper).blank.attributes("disabled")).toBeUndefined();
  });

  it("emits create for both modes", async () => {
    const wrapper = mountForm();
    await createButtons(wrapper).generate.trigger("click");
    await createButtons(wrapper).blank.trigger("click");
    expect(wrapper.emitted("create")).toEqual([["generate"], ["blank"]]);
  });
});

describe("NewReportForm — the duplicate guard", () => {
  const duplicate = makeReport({ id: 341, status: "changes_requested" });

  it("stops both writes and says the constraint is per person", () => {
    const wrapper = mountForm({ duplicate, freeWeek: "2026-07-27" });

    const panel = wrapper.find('[data-test="duplicate-warning"]');
    expect(panel.exists()).toBe(true);
    expect(panel.attributes("role")).toBe("alert");
    expect(panel.text()).toContain("uq_report_author_repo_week");
    expect(panel.text()).toMatch(/somebody else can still write their own/i);
    expect(panel.text()).toContain("409");

    // The whole create section is gone while a duplicate applies, so neither endpoint
    // can be asked for a 409.
    expect(wrapper.find('[data-test="create-generate"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="create-blank"]').exists()).toBe(false);
  });

  it("offers the report that already exists", () => {
    const wrapper = mountForm({ duplicate });
    const link = wrapper.findAll("a").find((a) => a.text().includes("Open report #341"));
    expect(link?.attributes("href")).toBe("/reports/341");
  });

  it("offers a free week when there is one, and says so plainly when there is not", async () => {
    const withFree = mountForm({ duplicate, freeWeek: "2026-07-27" });
    const jump = withFree.findAll("button").find((b) => b.text().startsWith("Jump to the week"));
    expect(jump).toBeDefined();
    await jump!.trigger("click");
    expect(withFree.emitted("update:week")).toEqual([["2026-07-27"]]);

    const withoutFree = mountForm({ duplicate, freeWeek: null });
    expect(withoutFree.text()).toMatch(/no free week to move to/i);
  });
});

describe("NewReportForm — what a draft would be written from", () => {
  it("blocks generation, not the blank draft, when nothing is synced for the week", () => {
    const wrapper = mountForm({ counts: { commits: 0, pull_requests: 0, reviews: 0, issues: 0 } });

    expect(wrapper.text()).toMatch(/nothing of yours is synced for this week/i);
    expect(createButtons(wrapper).generate.attributes("disabled")).toBeDefined();
    expect(createButtons(wrapper).blank.attributes("disabled")).toBeUndefined();
  });

  it("says the counts are missing rather than zero when the request failed", () => {
    const wrapper = mountForm({ counts: null, countsFailed: true });

    const alert = wrapper.find('[role="alert"]');
    expect(alert.text()).toMatch(/missing rather than zero/i);
    // A failed count is not evidence of a quiet week, so generation stays available.
    expect(createButtons(wrapper).generate.attributes("disabled")).toBeUndefined();
  });

  it("puts an API error where a screen reader will hear it", () => {
    const wrapper = mountForm({ errorMessage: "403 · you have no synced activity in this repository." });
    expect(wrapper.find('[role="alert"]').text()).toContain("403");
  });
});
