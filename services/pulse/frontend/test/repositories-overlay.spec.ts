import { describe, expect, it } from "vitest";
// The page's own source, read through Vite rather than node:fs so the spec needs no
// Node typings of its own.
import page from "~/pages/repositories.vue?raw";

/* The department listbox on /repositories was sliced in half: `Select` used to render its
   popup as an absolute child, and two ancestors clipped it — the table's `overflow-x-auto`
   scroller (a clipped x axis clips y too) and `.sec-collapse > *`, which is `overflow:
   hidden` so the row panel can animate 0fr → 1fr. The page carried two workarounds for
   that, both keyed off `data-overlay-open`.

   `Select` now teleports its listbox to <body>, so nothing on this page can clip it and
   both workarounds are gone. What is guarded here is that they do not come back — a
   scroller that grows 280px whenever a listbox opens is a layout bug waiting to happen. */

describe("/repositories · the department listbox is not clipped", () => {
  it("leaves the table scroller a plain scroller, with no open-listbox padding swap", () => {
    const scroller = page.match(/class="sec relative mt-1 overflow-x-auto[^"]*"/)?.[0];
    expect(scroller).toBeDefined();
    expect(scroller).not.toContain("data-overlay-open");
  });

  it("does not reach for an overflow escape anywhere on the page", () => {
    expect(page).not.toContain("has-[[data-overlay-open]]");
  });

  it("still names the panel sec-collapse, because Tailwind owns .collapse", () => {
    expect(page).toContain('class="sec-collapse"');
    expect(page).not.toMatch(/class="collapse"/);
  });
});
