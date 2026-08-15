import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import Modal from "../components/Modal.vue";

function open(slots: Record<string, string> = {}) {
  return mount(Modal, {
    props: { open: true, title: "Sign out everywhere", description: "Every session ends." },
    slots,
    attachTo: document.body,
  });
}

function panel(): HTMLElement {
  const el = document.querySelector<HTMLElement>('[role="dialog"]');
  if (!el) throw new Error("dialog not in the document");
  return el;
}

describe("Modal", () => {
  it("is a labelled modal dialog", () => {
    open();
    expect(panel().getAttribute("aria-modal")).toBe("true");
    expect(panel().getAttribute("aria-label")).toBe("Sign out everywhere");
    const describedBy = panel().getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();
    expect(document.getElementById(describedBy!)?.textContent).toContain("Every session ends.");
  });

  it("puts initial focus on the first field, not the close button", async () => {
    open({ default: '<input id="note" /><button id="other">Other</button>' });
    await Promise.resolve();
    expect(document.activeElement?.id).toBe("note");
  });

  it("falls back to the first control that is not the close button", async () => {
    open({ footer: '<button id="cancel">Cancel</button><button id="go">Sign out</button>' });
    await Promise.resolve();
    expect(document.activeElement?.id).toBe("cancel");
    expect((document.activeElement as HTMLElement).hasAttribute("data-modal-close")).toBe(false);
  });

  it("traps Tab inside the panel", async () => {
    open({ footer: '<button id="cancel">Cancel</button><button id="go">Sign out</button>' });
    await Promise.resolve();

    const items = Array.from(panel().querySelectorAll<HTMLElement>("button"));
    const first = items[0]!;
    const last = items[items.length - 1]!;

    last.focus();
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true }));
    expect(document.activeElement).toBe(first);

    first.focus();
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true }));
    expect(document.activeElement).toBe(last);
  });

  it("emits close on Escape", async () => {
    const wrapper = open({ default: '<input id="note" />' });
    await Promise.resolve();
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(wrapper.emitted("close")).toHaveLength(1);
  });

  it("yields Escape to an open listbox inside it", async () => {
    const wrapper = open({
      default: '<div data-overlay-open="true"><button id="opt">Alpha</button></div>',
    });
    await Promise.resolve();
    document.getElementById("opt")!.focus();
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(wrapper.emitted("close")).toBeUndefined();
  });

  it("locks body scroll while open and releases it on the logical close", async () => {
    const wrapper = mount(Modal, {
      props: { open: false, title: "Untrack repository" },
      attachTo: document.body,
    });
    expect(document.body.style.overflow).toBe("");

    await wrapper.setProps({ open: true });
    expect(document.body.style.overflow).toBe("hidden");

    await wrapper.setProps({ open: false });
    // Released with the decision, not with the exit animation.
    expect(document.body.style.overflow).toBe("");
  });

  it("restores focus to whatever opened it", async () => {
    const launcher = document.createElement("button");
    launcher.id = "launcher";
    document.body.appendChild(launcher);
    launcher.focus();

    const wrapper = mount(Modal, {
      props: { open: false, title: "Untrack repository" },
      slots: { default: '<input id="note" />' },
      attachTo: document.body,
    });

    await wrapper.setProps({ open: true });
    await Promise.resolve();
    expect(document.activeElement?.id).toBe("note");

    await wrapper.setProps({ open: false });
    expect(document.activeElement?.id).toBe("launcher");
  });

  it("stops listening once it is torn down", async () => {
    const wrapper = open({ default: '<input id="note" />' });
    await Promise.resolve();
    wrapper.unmount();
    expect(document.body.style.overflow).toBe("");
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(wrapper.emitted("close")).toBeUndefined();
  });
});
