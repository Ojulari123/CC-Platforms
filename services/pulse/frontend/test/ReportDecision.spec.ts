import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import ReportDecision from "~/components/ReportDecision.vue";

function buttons(wrapper: ReturnType<typeof mount>) {
  return wrapper.findAll("button").filter((b) => ["Approve", "Changes", "Reject"].includes(b.text()));
}

describe("ReportDecision", () => {
  // The note is cleared after each emit, so a second decision needs its own words. That
  // is deliberate: the same sentence should not be reused on a different verdict.
  it.each([
    [0, "approve"],
    [1, "request-changes"],
    [2, "reject"],
  ])("emits the decision behind button %i", async (index, decision) => {
    const wrapper = mount(ReportDecision, { props: { reportId: 341, allowed: true } });
    await wrapper.find("textarea").setValue("Needs the blocker named.");

    await buttons(wrapper)[index]!.trigger("click");

    expect(wrapper.emitted("decide")).toEqual([[decision, "Needs the blocker named."]]);
    expect((wrapper.find("textarea").element as HTMLTextAreaElement).value).toBe("");
  });

  it("approves with no note", async () => {
    const wrapper = mount(ReportDecision, { props: { reportId: 341, allowed: true } });
    await buttons(wrapper)[0]!.trigger("click");
    expect(wrapper.emitted("decide")).toEqual([["approve", ""]]);
  });

  it("will not send work back without saying why, and says so in a live error", async () => {
    const wrapper = mount(ReportDecision, { props: { reportId: 341, allowed: true } });

    await buttons(wrapper)[1]!.trigger("click");
    expect(wrapper.emitted("decide")).toBeUndefined();

    const alert = wrapper.find('[role="alert"]');
    expect(alert.exists()).toBe(true);
    expect(alert.text()).toMatch(/a note is required/i);
  });

  it("disables all three and explains why when the decision is not yours", () => {
    const wrapper = mount(ReportDecision, {
      props: {
        reportId: 341,
        allowed: false,
        reason: "You wrote this report, so you cannot decide it.",
      },
    });

    expect(buttons(wrapper).every((b) => b.attributes("disabled") !== undefined)).toBe(true);
    expect(wrapper.find("textarea").attributes("disabled")).toBeDefined();
    expect(wrapper.text()).toContain("You wrote this report, so you cannot decide it.");
  });

  it("takes its controls out of the tab order while its panel is collapsed", () => {
    const wrapper = mount(ReportDecision, {
      props: { reportId: 341, allowed: true, active: false },
    });
    expect(buttons(wrapper).every((b) => b.attributes("disabled") !== undefined)).toBe(true);
  });

  it("labels the note with the author's name and associates it with the field", () => {
    const wrapper = mount(ReportDecision, {
      props: { reportId: 341, allowed: true, authorName: "Ada Nwosu" },
    });
    const label = wrapper.find("label");
    expect(label.text()).toContain("Ada Nwosu");
    expect(label.find("textarea").exists()).toBe(true);
  });
});
