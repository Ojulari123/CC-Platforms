import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import Btn from "../components/Btn.vue";

describe("Btn", () => {
  it("carries the primary variant as near-white on near-black, never a coloured fill", () => {
    const wrapper = mount(Btn, { slots: { default: "Get started" } });
    const cls = wrapper.classes();
    expect(cls).toContain("bg-ink");
    expect(cls).toContain("text-app");
    expect(wrapper.attributes("type")).toBe("button");
  });

  it("gives every variant press feedback", () => {
    for (const variant of ["primary", "secondary", "ghost", "destructive"] as const) {
      const wrapper = mount(Btn, { props: { variant }, slots: { default: "x" } });
      expect(wrapper.classes(), variant).toContain("active:scale-[0.98]");
    }
  });

  it("uses ring-line-strong on secondary, because that ring is the only boundary", () => {
    const wrapper = mount(Btn, { props: { variant: "secondary" }, slots: { default: "x" } });
    expect(wrapper.classes()).toContain("ring-line-strong");
    expect(wrapper.classes()).not.toContain("ring-line");
  });

  it("applies the size scale", () => {
    expect(mount(Btn, { props: { size: "sm" } }).classes()).toContain("text-[13px]");
    expect(mount(Btn, { props: { size: "md" } }).classes()).toContain("text-[13.5px]");
    expect(mount(Btn, { props: { size: "lg" } }).classes()).toContain("text-[14px]");
  });

  it("carries a visible focus ring", () => {
    const wrapper = mount(Btn);
    expect(wrapper.classes()).toContain("focus-visible:ring-2");
    expect(wrapper.classes()).toContain("focus-visible:ring-[var(--accent-ink)]");
  });

  it("does not emit click while disabled", async () => {
    const wrapper = mount(Btn, { props: { disabled: true } });
    expect(wrapper.attributes("disabled")).toBeDefined();
    await wrapper.trigger("click");
    expect(wrapper.emitted("click")).toBeUndefined();
  });

  it("does not emit click while busy, and marks itself aria-busy", async () => {
    const wrapper = mount(Btn, { props: { busy: true } });
    expect(wrapper.classes()).toContain("btn-busy");
    expect(wrapper.attributes("aria-busy")).toBe("true");
    expect(wrapper.attributes("disabled")).toBeDefined();
    await wrapper.trigger("click");
    expect(wrapper.emitted("click")).toBeUndefined();
  });

  it("emits click when it is neither disabled nor busy", async () => {
    const wrapper = mount(Btn);
    await wrapper.trigger("click");
    expect(wrapper.emitted("click")).toHaveLength(1);
  });

  it("keeps the arrow mounted while busy so the button does not resize mid-wait", () => {
    const wrapper = mount(Btn, { props: { arrow: true, busy: true } });
    const arrow = wrapper.find("svg");
    expect(arrow.exists()).toBe(true);
    expect(arrow.classes()).toContain("opacity-0");
  });
});
