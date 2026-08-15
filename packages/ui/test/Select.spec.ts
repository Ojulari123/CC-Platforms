import { mount } from "@vue/test-utils";
import { nextTick } from "vue";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import Select from "../components/Select.vue";

const options = [
  { value: "a", label: "Alpha" },
  { value: "b", label: "Bravo" },
  { value: "c", label: "Charlie" },
];

// An open Select keeps document-level mousedown and scroll listeners, so a wrapper left
// mounted would still answer events raised by the next test.
const mounted: ReturnType<typeof mount>[] = [];

function mountSelect(modelValue = "a") {
  const wrapper = mount(Select, {
    props: { modelValue, options, label: "Repository" },
    attachTo: document.body,
  });
  mounted.push(wrapper);
  return wrapper;
}

afterEach(() => {
  while (mounted.length) mounted.pop()!.unmount();
});

// The listbox is teleported to <body>, so it is not inside the wrapper's own tree.
const listbox = () => document.querySelector<HTMLElement>('[role="listbox"]');
const optionEls = () => Array.from(document.querySelectorAll<HTMLElement>('[role="option"]'));
const optionId = (i: number) => optionEls()[i]!.id;

async function clickOption(i: number) {
  optionEls()[i]!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  await nextTick();
}

const VIEWPORT = { width: 1024, height: 768 };

// happy-dom has no layout: every rect reads zero unless the trigger is told what it is.
function anchor(wrapper: ReturnType<typeof mountSelect>, rect: Partial<DOMRect>) {
  const el = wrapper.get('[role="combobox"]').element as HTMLElement;
  const full = { x: 0, y: 0, top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0, ...rect };
  el.getBoundingClientRect = () => ({ ...full, toJSON: () => full }) as DOMRect;
}

beforeEach(() => {
  for (const [key, value] of Object.entries(VIEWPORT)) {
    Object.defineProperty(document.documentElement, key === "width" ? "clientWidth" : "clientHeight", {
      configurable: true,
      value,
    });
  }
});

describe("Select", () => {
  it("is a combobox trigger, not a native select", () => {
    const wrapper = mountSelect();
    expect(wrapper.find("select").exists()).toBe(false);
    const trigger = wrapper.get('[role="combobox"]');
    expect(trigger.attributes("aria-haspopup")).toBe("listbox");
    expect(trigger.attributes("aria-expanded")).toBe("false");
    expect(trigger.attributes("aria-label")).toBe("Repository");
    expect(trigger.attributes("aria-controls")).toBeTruthy();
  });

  it("opens on ArrowDown and announces the active option through aria-activedescendant", async () => {
    const wrapper = mountSelect();
    const trigger = wrapper.get('[role="combobox"]');
    await trigger.trigger("keydown", { key: "ArrowDown" });

    expect(trigger.attributes("aria-expanded")).toBe("true");
    expect(listbox()!.id).toBe(trigger.attributes("aria-controls"));
    // Opens on the selected option, then ArrowDown moves off it.
    expect(trigger.attributes("aria-activedescendant")).toBe(optionId(0));

    await trigger.trigger("keydown", { key: "ArrowDown" });
    expect(trigger.attributes("aria-activedescendant")).toBe(optionId(1));
  });

  it("keeps focus on the trigger while the listbox is open", async () => {
    const wrapper = mountSelect();
    const trigger = wrapper.get('[role="combobox"]');
    (trigger.element as HTMLElement).focus();
    await trigger.trigger("keydown", { key: "ArrowDown" });
    expect(document.activeElement).toBe(trigger.element);
  });

  it("wraps with ArrowUp and jumps with Home and End", async () => {
    const wrapper = mountSelect();
    const trigger = wrapper.get('[role="combobox"]');
    await trigger.trigger("keydown", { key: "ArrowDown" });

    await trigger.trigger("keydown", { key: "End" });
    expect(trigger.attributes("aria-activedescendant")).toBe(optionId(2));
    await trigger.trigger("keydown", { key: "ArrowDown" });
    expect(trigger.attributes("aria-activedescendant")).toBe(optionId(0));
    await trigger.trigger("keydown", { key: "ArrowUp" });
    expect(trigger.attributes("aria-activedescendant")).toBe(optionId(2));
    await trigger.trigger("keydown", { key: "Home" });
    expect(trigger.attributes("aria-activedescendant")).toBe(optionId(0));
  });

  it("commits the active option on Enter and closes", async () => {
    const wrapper = mountSelect();
    const trigger = wrapper.get('[role="combobox"]');
    await trigger.trigger("keydown", { key: "ArrowDown" });
    await trigger.trigger("keydown", { key: "ArrowDown" });
    await trigger.trigger("keydown", { key: "Enter" });

    expect(wrapper.emitted("update:modelValue")).toEqual([["b"]]);
    expect(trigger.attributes("aria-expanded")).toBe("false");
    expect(listbox()).toBeNull();
  });

  it("closes on Escape without changing the value, and returns focus to the trigger", async () => {
    const wrapper = mountSelect();
    const trigger = wrapper.get('[role="combobox"]');
    (trigger.element as HTMLElement).focus();
    await trigger.trigger("keydown", { key: "ArrowDown" });
    await trigger.trigger("keydown", { key: "ArrowDown" });
    await trigger.trigger("keydown", { key: "Escape" });

    expect(wrapper.emitted("update:modelValue")).toBeUndefined();
    expect(trigger.attributes("aria-expanded")).toBe("false");
    expect(listbox()).toBeNull();
    expect(document.activeElement).toBe(trigger.element);
  });

  it("marks the selected option and flags itself as an open overlay", async () => {
    const wrapper = mountSelect("c");
    const trigger = wrapper.get('[role="combobox"]');
    await trigger.trigger("keydown", { key: "ArrowDown" });

    expect(wrapper.attributes("data-overlay-open")).toBe("true");
    expect(optionEls().map((o) => o.getAttribute("aria-selected"))).toEqual(["false", "false", "true"]);
  });

  it("commits on click", async () => {
    const wrapper = mountSelect();
    await wrapper.get('[role="combobox"]').trigger("click");
    await clickOption(2);
    expect(wrapper.emitted("update:modelValue")).toEqual([["c"]]);
  });

  it("closes on an outside mousedown but not on a mousedown inside the popup", async () => {
    const wrapper = mountSelect();
    await wrapper.get('[role="combobox"]').trigger("click");

    listbox()!.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    await nextTick();
    expect(listbox()).not.toBeNull();

    document.body.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    await nextTick();
    expect(listbox()).toBeNull();
  });
});

/* The listbox used to be an absolutely-positioned child, which put it at the mercy of
   whichever ancestor happened to establish the containing block — inside the repositories
   table it resolved against the wrong one and landed thousands of pixels below the fold,
   at left: 0. It is now teleported to <body> and placed `fixed` from the trigger's rect,
   so these assert the geometry rather than the DOM position. */
describe("Select · popup placement", () => {
  it("leaves the component's own tree and is fixed to the viewport", async () => {
    const wrapper = mountSelect();
    anchor(wrapper, { top: 100, bottom: 132, left: 40, right: 260, width: 220, height: 32 });
    await wrapper.get('[role="combobox"]').trigger("click");
    await nextTick();

    const list = listbox()!;
    expect(list.parentElement).toBe(document.body);
    expect(wrapper.element.contains(list)).toBe(false);
    expect(list.className).toContain("fixed");
  });

  it("anchors under the trigger, at the trigger's width", async () => {
    const wrapper = mountSelect();
    anchor(wrapper, { top: 100, bottom: 132, left: 40, right: 260, width: 220, height: 32 });
    await wrapper.get('[role="combobox"]').trigger("click");
    await nextTick();

    const list = listbox()!;
    expect(list.style.top).toBe("136px"); // trigger bottom + 4px gap
    expect(list.style.left).toBe("40px");
    expect(list.style.width).toBe("220px");
    expect(list.style.bottom).toBe("");
  });

  it("stays inside the viewport on all four edges", async () => {
    const wrapper = mountSelect();
    anchor(wrapper, { top: 100, bottom: 132, left: 40, right: 260, width: 220, height: 32 });
    await wrapper.get('[role="combobox"]').trigger("click");
    await nextTick();

    const list = listbox()!;
    const top = Number.parseFloat(list.style.top);
    const left = Number.parseFloat(list.style.left);
    const width = Number.parseFloat(list.style.width);
    const maxHeight = Number.parseFloat(list.style.maxHeight);
    expect(top).toBeGreaterThanOrEqual(0);
    expect(left).toBeGreaterThanOrEqual(0);
    expect(left + width).toBeLessThanOrEqual(VIEWPORT.width);
    expect(top + maxHeight).toBeLessThanOrEqual(VIEWPORT.height);
  });

  it("flips above the trigger when there is no room below", async () => {
    const wrapper = mountSelect();
    anchor(wrapper, { top: 700, bottom: 732, left: 40, right: 260, width: 220, height: 32 });
    await wrapper.get('[role="combobox"]').trigger("click");
    await nextTick();

    const list = listbox()!;
    expect(list.style.top).toBe("");
    // Viewport height − trigger top + the 4px gap: the popup's lower edge sits above it.
    expect(list.style.bottom).toBe("72px");
    expect(VIEWPORT.height - Number.parseFloat(list.style.bottom)).toBeLessThanOrEqual(700);
  });

  it("pulls back from the right edge instead of overflowing it", async () => {
    const wrapper = mountSelect();
    anchor(wrapper, { top: 100, bottom: 132, left: 1000, right: 1220, width: 220, height: 32 });
    await wrapper.get('[role="combobox"]').trigger("click");
    await nextTick();

    // 1024 − 220 − 8px edge inset.
    expect(listbox()!.style.left).toBe("796px");
  });

  it("never renders narrower than a readable minimum", async () => {
    const wrapper = mountSelect();
    anchor(wrapper, { top: 100, bottom: 132, left: 40, right: 90, width: 50, height: 32 });
    await wrapper.get('[role="combobox"]').trigger("click");
    await nextTick();

    expect(listbox()!.style.width).toBe("160px");
  });

  it("follows the trigger when an ancestor scroller moves under it", async () => {
    const wrapper = mountSelect();
    anchor(wrapper, { top: 100, bottom: 132, left: 40, right: 260, width: 220, height: 32 });
    await wrapper.get('[role="combobox"]').trigger("click");
    await nextTick();
    expect(listbox()!.style.top).toBe("136px");

    anchor(wrapper, { top: 300, bottom: 332, left: 40, right: 260, width: 220, height: 32 });
    window.dispatchEvent(new Event("scroll"));
    await nextTick();
    expect(listbox()!.style.top).toBe("336px");
  });
});
