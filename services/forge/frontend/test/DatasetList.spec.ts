import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import DatasetList from "../components/DatasetList.vue";
import type { DatasetResponse } from "../types/api";

const MINE: DatasetResponse = {
  id: 61,
  owner_user_id: 7,
  is_sample: false,
  name: "revenue.csv",
  original_filename: "revenue.csv",
  columns: ["region", "quarter", "revenue"],
  row_count: 4,
  created_at: "2026-08-10T11:20:00",
};

const SAMPLE: DatasetResponse = {
  id: 12,
  owner_user_id: null,
  is_sample: true,
  name: "monthly-sales.csv",
  original_filename: null,
  columns: ["month", "revenue"],
  row_count: 8412,
  created_at: "2026-07-28T16:41:00",
};

function mountList() {
  return mount(DatasetList, {
    props: { datasets: [MINE, SAMPLE], currentUserId: 7 },
    attachTo: document.body,
  });
}

function dialog(): HTMLElement | null {
  return document.querySelector<HTMLElement>('[role="dialog"]');
}

// The dialog animates out, so its removal is two frames behind the click. Microtasks
// alone would assert on a panel that is still mid-exit.
async function settle() {
  await flushPromises();
  await new Promise((resolve) => setTimeout(resolve, 120));
  await flushPromises();
}

function dialogButton(label: string): HTMLElement {
  const found = Array.from(dialog()?.querySelectorAll("button") ?? []).find(
    (b) => b.textContent?.trim() === label,
  );
  if (!found) throw new Error(`no "${label}" button in the dialog`);
  return found;
}

describe("DatasetList", () => {
  it("shows the counts, owner and timestamp as readable values", () => {
    const wrapper = mountList();
    const rows = wrapper.findAll("tbody tr");

    for (const value of ["revenue.csv", "4", "3", "10 Aug 11:20", "yours"]) {
      expect(rows[0]!.text()).toContain(value);
    }
    for (const value of ["monthly-sales.csv", "8,412", "2", "28 Jul 16:41", "sample"]) {
      expect(rows[1]!.text()).toContain(value);
    }
  });

  /* The rows used to be a flex line, so a row carrying a Delete pushed its own counts
     left and nothing lined up between rows. Real columns are the fix, and the thing
     worth guarding is that every row still has the same number of them. */
  it("lays the rows out as columns that line up", () => {
    const wrapper = mountList();

    const headings = wrapper.findAll("thead th").map((th) => th.text());
    expect(headings).toEqual(["Dataset", "Rows", "Cols", "Uploaded", "Owner", "Actions"]);

    const rows = wrapper.findAll("tbody tr");
    expect(rows).toHaveLength(2);
    for (const row of rows) expect(row.findAll("td")).toHaveLength(headings.length);

    // The two figures are the only right-aligned columns, and they are data, not chrome.
    const mine = rows[0]!.findAll("td");
    expect(mine[1]!.text()).toBe("4");
    expect(mine[2]!.text()).toBe("3");
    for (const cell of [mine[1]!, mine[2]!]) {
      expect(cell.classes()).toContain("text-right");
      expect(cell.classes()).toContain("text-ink-muted");
      expect(cell.classes()).not.toContain("text-ink-faint");
      // Right alignment only lines the figures up if the digits are the same width.
      expect(cell.classes()).toContain("tabular-nums");
    }
  });

  it("offers delete only where the service would allow it", () => {
    const wrapper = mountList();
    const labels = wrapper.findAll("button").map((b) => b.attributes("aria-label"));

    expect(labels).toEqual(["Delete revenue.csv"]);
    // The shared sample keeps its action cell so the columns hold, but the cell is empty
    // rather than carrying a control that can only earn a 403.
    const sample = wrapper.findAll("tbody tr")[1]!;
    expect(sample.findAll("button")).toHaveLength(0);
    expect(sample.findAll("td")[5]!.text()).toBe("");
  });

  it("puts a confirmation in front of the delete and only then emits", async () => {
    const wrapper = mountList();
    expect(dialog()).toBeNull();

    await wrapper.get('[aria-label="Delete revenue.csv"]').trigger("click");
    await flushPromises();

    const panel = dialog();
    expect(panel).not.toBeNull();
    expect(panel!.getAttribute("aria-modal")).toBe("true");
    expect(panel!.textContent).toContain("revenue.csv — 4 rows, 3 columns");
    expect(panel!.textContent).toContain("dataset_id 61");
    // Nothing has been asked for yet.
    expect(wrapper.emitted("confirm")).toBeUndefined();

    dialogButton("Delete dataset").click();
    await settle();

    expect(wrapper.emitted("confirm")?.[0]).toEqual([MINE]);
    expect(dialog()).toBeNull();
  });

  it("keeps the dataset when the confirmation is declined", async () => {
    const wrapper = mountList();
    await wrapper.get('[aria-label="Delete revenue.csv"]').trigger("click");
    await flushPromises();

    dialogButton("Keep it").click();
    await settle();

    expect(wrapper.emitted("confirm")).toBeUndefined();
    expect(dialog()).toBeNull();
  });

  it("stands the row controls down while a delete is in flight", () => {
    const wrapper = mount(DatasetList, {
      props: { datasets: [MINE], currentUserId: 7, busy: true },
    });
    expect(wrapper.get('[aria-label="Delete revenue.csv"]').attributes("disabled")).toBeDefined();
  });

  it("says so plainly when there is nothing to list", () => {
    const wrapper = mount(DatasetList, { props: { datasets: [], currentUserId: 7 } });
    expect(wrapper.text()).toContain("nothing to list · upload a csv to start");
    expect(wrapper.findAll("table")).toHaveLength(0);
  });
});
