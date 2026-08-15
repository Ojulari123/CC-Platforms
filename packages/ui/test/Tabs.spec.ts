import { mount } from "@vue/test-utils";
import { defineComponent, h, ref } from "vue";
import { describe, expect, it } from "vitest";
import TabPanel from "../components/TabPanel.vue";
import Tabs from "../components/Tabs.vue";

const items = [
  { id: "mine", label: "My reports" },
  { id: "queue", label: "Review queue", hint: "3" },
  { id: "all", label: "Everything" },
];

// A real v-model host, so arrow keys move selection the way a screen wires it.
const Host = defineComponent({
  setup() {
    const value = ref("mine");
    return () =>
      h(Tabs, {
        id: "reports",
        items,
        label: "Report scope",
        modelValue: value.value,
        "onUpdate:modelValue": (next: string) => {
          value.value = next;
        },
      });
  },
});

describe("Tabs", () => {
  it("is a real tablist with a roving tabindex", () => {
    const wrapper = mount(Host, { attachTo: document.body });
    expect(wrapper.get('[role="tablist"]').attributes("aria-label")).toBe("Report scope");
    const tabs = wrapper.findAll('[role="tab"]');
    expect(tabs.map((t) => t.attributes("tabindex"))).toEqual(["0", "-1", "-1"]);
    expect(tabs.map((t) => t.attributes("aria-selected"))).toEqual(["true", "false", "false"]);
  });

  it("moves selection and focus with ArrowRight, wrapping at the end", async () => {
    const wrapper = mount(Host, { attachTo: document.body });
    const list = wrapper.get('[role="tablist"]');

    await list.trigger("keydown", { key: "ArrowRight" });
    await wrapper.vm.$nextTick();
    let tabs = wrapper.findAll('[role="tab"]');
    expect(tabs.map((t) => t.attributes("aria-selected"))).toEqual(["false", "true", "false"]);
    expect(tabs.map((t) => t.attributes("tabindex"))).toEqual(["-1", "0", "-1"]);
    expect(document.activeElement).toBe(tabs[1]!.element);

    await list.trigger("keydown", { key: "ArrowRight" });
    await list.trigger("keydown", { key: "ArrowRight" });
    await wrapper.vm.$nextTick();
    tabs = wrapper.findAll('[role="tab"]');
    expect(tabs.map((t) => t.attributes("aria-selected"))).toEqual(["true", "false", "false"]);
  });

  it("moves back with ArrowLeft and jumps with Home and End", async () => {
    const wrapper = mount(Host, { attachTo: document.body });
    const list = wrapper.get('[role="tablist"]');

    await list.trigger("keydown", { key: "End" });
    expect(wrapper.findAll('[role="tab"]')[2]!.attributes("aria-selected")).toBe("true");
    await list.trigger("keydown", { key: "ArrowLeft" });
    expect(wrapper.findAll('[role="tab"]')[1]!.attributes("aria-selected")).toBe("true");
    await list.trigger("keydown", { key: "Home" });
    expect(wrapper.findAll('[role="tab"]')[0]!.attributes("aria-selected")).toBe("true");
  });

  it("has one indicator that travels rather than one per tab", async () => {
    const wrapper = mount(Host, { attachTo: document.body });
    const indicators = wrapper.findAll('[aria-hidden="true"]');
    expect(indicators).toHaveLength(1);
    expect(indicators[0]!.attributes("style")).toContain("transition");
  });

  it("only claims aria-controls when a panel is in the document", async () => {
    const noPanels = mount(Tabs, {
      props: { id: "filter", items, label: "Filter", modelValue: "mine" },
    });
    expect(noPanels.findAll('[role="tab"]').every((t) => t.attributes("aria-controls") === undefined)).toBe(true);

    const withPanel = mount(Tabs, {
      props: { id: "filter", items, label: "Filter", modelValue: "mine", hasPanel: true },
    });
    const controls = withPanel.findAll('[role="tab"]').map((t) => t.attributes("aria-controls"));
    expect(controls).toEqual(["filter-panel-mine", undefined, undefined]);
  });

  it("wires TabPanel back to its tab and takes a tab stop only when it holds nothing focusable", async () => {
    const plain = mount(TabPanel, {
      props: { id: "filter", tab: "mine" },
      slots: { default: "<p>Nothing to click.</p>" },
    });
    expect(plain.attributes("id")).toBe("filter-panel-mine");
    expect(plain.attributes("role")).toBe("tabpanel");
    expect(plain.attributes("aria-labelledby")).toBe("filter-tab-mine");
    // The panel's own contents decide this, so it settles a tick after mount.
    await plain.vm.$nextTick();
    expect(plain.attributes("tabindex")).toBe("0");

    const interactive = mount(TabPanel, {
      props: { id: "filter", tab: "mine" },
      slots: { default: "<button>Open</button>" },
    });
    await interactive.vm.$nextTick();
    expect(interactive.attributes("tabindex")).toBe("-1");
  });
});
