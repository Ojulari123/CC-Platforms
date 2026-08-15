import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import RowMenu from "~/components/RowMenu.vue";

const ITEMS = [
  { id: "deactivate", label: "Deactivate" },
  { id: "grant-admin", label: "Make platform admin" },
  { id: "delete", label: "Delete account", tone: "bad" as const, separatorBefore: true },
];

describe("the row action menu", () => {
  it("says whether it is open, and does not render a panel until it is", () => {
    const w = mount(RowMenu, { props: { open: false, label: "Actions for Ada", items: ITEMS } });
    const trigger = w.get("button[aria-haspopup='menu']");
    expect(trigger.attributes("aria-expanded")).toBe("false");
    expect(w.find("[role='menu']").exists()).toBe(false);
  });

  it("asks to open when the trigger is clicked", async () => {
    const w = mount(RowMenu, { props: { open: false, label: "Actions for Ada", items: ITEMS } });
    await w.get("button[aria-haspopup='menu']").trigger("click");
    expect(w.emitted("update:open")).toEqual([[true]]);
  });

  it("renders every item as a real menuitem once open", () => {
    const w = mount(RowMenu, { props: { open: true, label: "Actions for Ada", items: ITEMS } });
    const items = w.findAll("[role='menuitem']");
    expect(items).toHaveLength(3);
    expect(items.map((i) => i.text())).toEqual(["Deactivate", "Make platform admin", "Delete account"]);
    expect(w.get("button[aria-haspopup='menu']").attributes("aria-expanded")).toBe("true");
  });

  it("its items are actually clickable — a click selects and closes", async () => {
    const w = mount(RowMenu, { props: { open: true, label: "Actions for Ada", items: ITEMS } });
    await w.findAll("[role='menuitem']")[2]!.trigger("click");
    expect(w.emitted("select")).toEqual([["delete"]]);
    expect(w.emitted("update:open")).toEqual([[false]]);
  });

  it("closes on Escape", async () => {
    const w = mount(RowMenu, {
      props: { open: true, label: "Actions for Ada", items: ITEMS },
      attachTo: document.body,
    });
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    await w.vm.$nextTick();
    expect(w.emitted("update:open")).toEqual([[false]]);
    w.unmount();
  });

  it("closes on a mousedown outside itself", async () => {
    const w = mount(RowMenu, {
      props: { open: true, label: "Actions for Ada", items: ITEMS },
      attachTo: document.body,
    });
    const outside = document.createElement("div");
    document.body.appendChild(outside);
    outside.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    await w.vm.$nextTick();
    expect(w.emitted("update:open")).toEqual([[false]]);
    w.unmount();
  });

  it("does not close when the mousedown is on its own trigger", async () => {
    const w = mount(RowMenu, {
      props: { open: true, label: "Actions for Ada", items: ITEMS },
      attachTo: document.body,
    });
    // With the listener scoped to the panel alone, this counted as an outside click,
    // closed the menu, and the click that followed reopened it.
    w.get("button[aria-haspopup='menu']").element.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    await w.vm.$nextTick();
    expect(w.emitted("update:open")).toBeUndefined();
    w.unmount();
  });

  it("stops listening once it is closed, so a stray Escape does not fire again", async () => {
    const w = mount(RowMenu, {
      props: { open: true, label: "Actions for Ada", items: ITEMS },
      attachTo: document.body,
    });
    await w.setProps({ open: false });
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    await w.vm.$nextTick();
    expect(w.emitted("update:open")).toBeUndefined();
    w.unmount();
  });

  it("stays reachable without a hover: focus-visible and coarse pointers reveal it", () => {
    const w = mount(RowMenu, { props: { open: false, label: "Actions for Ada", items: ITEMS } });
    const cls = w.get("button[aria-haspopup='menu']").classes().join(" ");
    expect(cls).toContain("focus-visible:opacity-100");
    expect(cls).toContain("[@media(hover:none)]:opacity-100");
  });
});
