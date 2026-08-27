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
    expect(wrapper.text()).toContain("Build status");
    expect(wrapper.text()).toContain("build ledger · four tasks · canvas vocabulary · not-yet list");
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
    expect(text).toContain("Anything marked planned is written down and not built");
    expect(text).toContain("The four guided walkthroughs are still a written specification.");
  });

  /* The panel used to mark all four tasks "Not built", which read as "Forge cannot do
     classification" rather than "there is no walkthrough for it". These two pin the
     distinction so it cannot quietly rot back. */
  it("marks the walkthrough as missing without claiming the task does not run", async () => {
    const wrapper = mount(RoadmapPanel);
    await wrapper.get('[aria-controls="forge-not-built"]').trigger("click");
    const text = wrapper.get("#forge-not-built").text().replace(/\s+/g, " ");

    expect(text).toContain("Walkthrough not built");
    expect(text).toContain("Four tasks, all runnable today");
    expect(text).toContain("Every task below is on the canvas today");
    expect(text).not.toContain("none of them can be started");
  });

  it("sends a person to the canvas that runs the task they are reading about", async () => {
    const wrapper = mount(RoadmapPanel);
    await wrapper.get('[aria-controls="forge-not-built"]').trigger("click");

    const link = wrapper.get('#forge-not-built a[href="/canvas?task=tabular_classification"]');
    expect(link.text()).toContain("open Classification on the canvas");

    // Switching path switches where the link points.
    const paths = wrapper.findAll("#forge-not-built button[aria-pressed]");
    await paths[1]!.trigger("click");
    expect(wrapper.get('#forge-not-built a[href="/canvas?task=tabular_regression"]').text())
      .toContain("open Regression on the canvas");
  });

  it("counts the LLM playground among what is live", async () => {
    const wrapper = mount(RoadmapPanel);
    await wrapper.get('[aria-controls="forge-not-built"]').trigger("click");
    expect(wrapper.get("#forge-not-built").text()).toContain("LLM playground");
  });
});
