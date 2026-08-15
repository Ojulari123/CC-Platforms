import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import RoadmapPanel from "../components/RoadmapPanel.vue";
import { FOCUSABLE } from "@crescent/ui/utils/ui";

describe("RoadmapPanel", () => {
  it("opens closed: the workspace leads with the tool, not the roadmap", () => {
    const wrapper = mount(RoadmapPanel);
    const toggle = wrapper.get('[aria-controls="forge-not-built"]');
    const region = wrapper.get("#forge-not-built");

    expect(toggle.attributes("aria-expanded")).toBe("false");
    expect(region.attributes("data-open")).toBe("false");
    expect(region.attributes("aria-hidden")).toBe("true");
    expect(toggle.text()).toContain("show");
  });

  it("keeps a manifest of what is inside visible while it is shut", () => {
    const wrapper = mount(RoadmapPanel);
    expect(wrapper.text()).toContain("Not built yet");
    expect(wrapper.text()).toContain("build ledger · four learning paths · canvas vocabulary · not-yet list");
  });

  it("leaves nothing focusable inside the collapsed region", () => {
    const wrapper = mount(RoadmapPanel);
    const region = wrapper.get("#forge-not-built").element;

    expect(region.querySelectorAll("button").length).toBeGreaterThan(0);
    // The clipped content is still in the DOM, so every control in it has to be out of
    // the tab order on its own account.
    expect(region.querySelectorAll(FOCUSABLE).length).toBe(0);
  });

  it("opens on the toggle and hands its controls back", async () => {
    const wrapper = mount(RoadmapPanel);
    const toggle = wrapper.get('[aria-controls="forge-not-built"]');

    await toggle.trigger("click");

    const region = wrapper.get("#forge-not-built");
    expect(toggle.attributes("aria-expanded")).toBe("true");
    expect(region.attributes("data-open")).toBe("true");
    expect(region.attributes("aria-hidden")).toBe("false");
    expect(toggle.text()).toContain("hide");
    expect(region.element.querySelectorAll(FOCUSABLE).length).toBeGreaterThan(0);
  });

  it("switches the learning path panel once it is open", async () => {
    const wrapper = mount(RoadmapPanel);
    await wrapper.get('[aria-controls="forge-not-built"]').trigger("click");

    const paths = wrapper.findAll("#forge-not-built button[aria-pressed]");
    expect(paths.length).toBe(4);
    expect(paths[0]!.attributes("aria-pressed")).toBe("true");

    await paths[2]!.trigger("click");
    expect(paths[2]!.attributes("aria-pressed")).toBe("true");
    expect(paths[0]!.attributes("aria-pressed")).toBe("false");
    expect(wrapper.get("#forge-not-built").text()).toContain("Time series");
  });

  it("names both halves of the ledger without pretending either is the other", async () => {
    const wrapper = mount(RoadmapPanel);
    await wrapper.get('[aria-controls="forge-not-built"]').trigger("click");
    const text = wrapper.get("#forge-not-built").text().replace(/\s+/g, " ");

    expect(text).toContain("CSV upload, 5 MB cap");
    expect(text).toContain("Workflow canvas");
    expect(text).toContain("No ML libraries are installed yet");
    expect(text).toContain("No model training, scoring, forecasting or inference of any kind.");
  });
});
