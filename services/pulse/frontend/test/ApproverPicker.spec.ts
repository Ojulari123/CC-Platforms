import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import ApproverPicker from "~/components/ApproverPicker.vue";
import { candidateOptions } from "~/utils/pulse";
import { makeCandidate, makeRepo } from "./fixtures";

describe("candidateOptions", () => {
  it("keeps a post-holder with no activity and labels them rather than dropping them", () => {
    const options = candidateOptions([
      makeCandidate({ user_id: 1043, has_activity: true }),
      makeCandidate({
        user_id: 1067,
        has_activity: false,
        is_lead: true,
        person: { user_id: 1067, first_name: "Chioma", last_name: "Eze", avatar_url: null, is_active: true },
      }),
    ]);

    expect(options.map((o) => o.label)).toEqual([
      "Nobody",
      "Tunde Balogun",
      "Chioma Eze · no activity here",
    ]);
  });

  it("never renders a bare id as though it were a name", () => {
    const options = candidateOptions([makeCandidate({ user_id: 1096, person: null })]);
    expect(options[1]!.label).toBe("Unknown user (#1096)");
  });

  it("offers nobody but Nobody when the endpoint returns an empty list", () => {
    expect(candidateOptions([])).toEqual([{ value: "none", label: "Nobody" }]);
  });
});

describe("ApproverPicker", () => {
  const candidates = [
    makeCandidate({ user_id: 1043 }),
    makeCandidate({
      user_id: 1051,
      person: { user_id: 1051, first_name: "Zainab", last_name: "Yusuf", avatar_url: null, is_active: true },
    }),
  ];

  it("emits the two ids the repository writes take", async () => {
    const wrapper = mount(ApproverPicker, {
      props: { repo: makeRepo({ lead_user_id: 1043, deputy_user_id: 1051 }), candidates },
    });

    await wrapper.find('[data-test="save-posts"]').trigger("click");
    expect(wrapper.emitted("save")).toEqual([[1043, 1051]]);
  });

  it("sends nulls when both posts are vacated", async () => {
    const wrapper = mount(ApproverPicker, { props: { repo: makeRepo(), candidates } });
    await wrapper.find('[data-test="save-posts"]').trigger("click");
    expect(wrapper.emitted("save")).toEqual([[null, null]]);
  });

  it("refuses one person in both posts before a request goes out, in a live error", async () => {
    const wrapper = mount(ApproverPicker, {
      props: { repo: makeRepo({ lead_user_id: 1043, deputy_user_id: 1043 }), candidates },
    });

    await wrapper.find('[data-test="save-posts"]').trigger("click");

    expect(wrapper.emitted("save")).toBeUndefined();
    const alert = wrapper.find('[role="alert"]');
    expect(alert.exists()).toBe(true);
    expect(alert.text()).toMatch(/two different people/i);
  });

  it("keeps a current post-holder the endpoint left out, rather than showing the post as vacant", async () => {
    // Left to the endpoint alone, the trigger would fall back to its placeholder and
    // saving from there would clear a post nobody asked to clear.
    const wrapper = mount(ApproverPicker, {
      props: {
        repo: makeRepo({
          lead_user_id: 1042,
          lead: { user_id: 1042, first_name: "Adeoluwa", last_name: "Ojulari", avatar_url: null, is_active: true },
        }),
        candidates,
      },
    });

    const leadTrigger = wrapper.findAll('[role="combobox"]')[0]!;
    expect(leadTrigger.text()).toContain("Adeoluwa Ojulari");

    await wrapper.find('[data-test="save-posts"]').trigger("click");
    expect(wrapper.emitted("save")).toEqual([[1042, null]]);
  });

  it("says why the list is empty rather than showing an empty picker with no explanation", () => {
    const wrapper = mount(ApproverPicker, { props: { repo: makeRepo(), candidates: [] } });
    expect(wrapper.find('[data-test="no-candidates"]').text()).toMatch(/nobody has synced work/i);
  });

  it("surfaces a server error next to the control that caused it", () => {
    const wrapper = mount(ApproverPicker, {
      props: { repo: makeRepo(), candidates, serverError: "403 · not a department admin" },
    });
    expect(wrapper.find('[role="alert"]').text()).toContain("403");
  });

  it("disables its controls while the panel around it is collapsed", () => {
    const wrapper = mount(ApproverPicker, {
      props: { repo: makeRepo(), candidates, active: false },
    });
    expect(wrapper.find('[data-test="save-posts"]').attributes("disabled")).toBeDefined();
    expect(
      wrapper.findAll('[role="combobox"]').every((c) => c.attributes("disabled") !== undefined),
    ).toBe(true);
  });
});
