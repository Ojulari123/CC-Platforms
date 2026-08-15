import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import DatasetPreviewTable from "../components/DatasetPreviewTable.vue";

const COLUMNS = ["region", "quarter", "revenue"];

function rows(n: number): string[][] {
  return Array.from({ length: n }, (_, i) => [`region ${i + 1}`, "Q1", String(1000 + i)]);
}

function mountTable(count: number) {
  return mount(DatasetPreviewTable, {
    props: {
      columns: COLUMNS,
      rows: rows(count),
      rowCount: count,
      totalColumns: COLUMNS.length,
      label: "revenue.csv",
    },
  });
}

describe("DatasetPreviewTable", () => {
  it("uses the dataset's own column names as headers, never spreadsheet letters", () => {
    const wrapper = mountTable(4);
    const headers = wrapper.findAll("thead th").map((th) => th.text().trim());

    expect(headers[0]).toBe("#");
    expect(headers.slice(1).map((h) => h.split(/\s+/)[0])).toEqual(COLUMNS);
    expect(headers).not.toContain("A");
    expect(headers).not.toContain("B");
    expect(wrapper.findAll("thead th").every((th) => th.attributes("scope") === "col")).toBe(true);
  });

  it("marks the categorical column, and only that one, with `text`", () => {
    const wrapper = mountTable(4);
    const headers = wrapper.findAll("thead th").map((th) => th.text().replace(/\s+/g, " ").trim());

    expect(headers[1]).toBe("region text");
    expect(headers[2]).toBe("quarter");
    expect(headers[3]).toBe("revenue");
  });

  it("caps the body at ten rows and says how many of how many are shown", () => {
    const wrapper = mountTable(48);
    const body = wrapper.findAll("tbody tr");

    expect(body).toHaveLength(10);
    expect(body[0]!.findAll("td")[0]!.text()).toBe("1");
    expect(body[9]!.findAll("td")[0]!.text()).toBe("10");
    expect(wrapper.text().replace(/\s+/g, " ")).toContain("first 10 of 48 rows · 3 of 3 columns shown");
  });

  it("does not pad short datasets up to the cap", () => {
    const wrapper = mountTable(3);
    expect(wrapper.findAll("tbody tr")).toHaveLength(3);
    expect(wrapper.text().replace(/\s+/g, " ")).toContain("first 3 of 3 rows");
    expect(wrapper.get("caption").text()).toBe("First 3 rows of revenue.csv");
  });

  it("marks no column when every column is a number or a date", () => {
    const wrapper = mount(DatasetPreviewTable, {
      props: {
        columns: ["week", "opened"],
        rows: [
          ["2026-06-01", "84"],
          ["2026-06-08", "77"],
        ],
        rowCount: 2,
        label: "tickets.csv",
      },
    });
    expect(wrapper.text()).not.toContain("text");
  });
});
