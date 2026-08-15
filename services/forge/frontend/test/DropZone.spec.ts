import { mount } from "@vue/test-utils";
import type { VueWrapper } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import DropZone from "../components/DropZone.vue";
import { MAX_UPLOAD_BYTES } from "../utils/upload";

// happy-dom derives File.size from the blob parts, so the byte count is overridden
// rather than allocating five megabytes of real buffer per test.
function file(name: string, size: number): File {
  const f = new File(["header\n"], name, { type: "text/csv" });
  Object.defineProperty(f, "size", { value: size });
  return f;
}

// Dispatched by hand: happy-dom has no DragEvent constructor with a writable
// dataTransfer, and Object.assign onto a readonly accessor throws under ESM strict.
function drag(wrapper: VueWrapper, type: string, dropped?: File) {
  const event = new Event(type, { bubbles: true, cancelable: true });
  if (dropped) Object.defineProperty(event, "dataTransfer", { value: { files: [dropped] } });
  wrapper.get("[data-drop-zone]").element.dispatchEvent(event);
}

// The alert carries a mono heading and the reason. This reads the reason.
function alertText(wrapper: VueWrapper): string {
  const parts = wrapper.findAll('[role="alert"] p');
  expect(parts[0]!.text()).toBe("upload rejected");
  return parts[parts.length - 1]!.text().replace(/\s+/g, " ");
}

describe("DropZone", () => {
  it("refuses a file over the 5 MB cap and names the size and the limit", async () => {
    const wrapper = mount(DropZone);
    drag(wrapper, "drop", file("huge.csv", 7 * 1024 * 1024));
    await wrapper.vm.$nextTick();

    expect(wrapper.emitted("accept")).toBeUndefined();
    expect(wrapper.emitted("reject")?.[0]).toEqual(["size"]);
    expect(alertText(wrapper)).toBe(
      "huge.csv is 7.00 MB, over the 5.00 MB cap. The upload is refused while streaming rather than buffered and then thrown away.",
    );
  });

  it("puts the cap on the byte after the limit, not the byte before it", async () => {
    const wrapper = mount(DropZone);

    drag(wrapper, "drop", file("exact.csv", MAX_UPLOAD_BYTES));
    await wrapper.vm.$nextTick();
    expect(wrapper.emitted("accept")).toHaveLength(1);

    drag(wrapper, "drop", file("over.csv", MAX_UPLOAD_BYTES + 1));
    await wrapper.vm.$nextTick();
    expect(wrapper.emitted("accept")).toHaveLength(1);
    expect(wrapper.emitted("reject")?.[0]).toEqual(["size"]);
    expect(alertText(wrapper)).toContain("over the 5.00 MB cap");
  });

  it("accepts a CSV inside the cap and reports its size back", async () => {
    const wrapper = mount(DropZone);
    drag(wrapper, "drop", file("revenue.csv", 2048));
    await wrapper.vm.$nextTick();

    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
    const accepted = wrapper.emitted("accept")?.[0]?.[0] as File;
    expect(accepted.name).toBe("revenue.csv");
    expect(wrapper.text()).toContain("revenue.csv");
    expect(wrapper.text()).toContain("2.0 KB");
    expect(wrapper.text()).toContain("2,048 bytes");
  });

  it("refuses a file that is not a .csv, and an empty one, each by name", async () => {
    const wrapper = mount(DropZone);

    drag(wrapper, "drop", file("notes.xlsx", 900));
    await wrapper.vm.$nextTick();
    expect(alertText(wrapper)).toContain("notes.xlsx is not a .csv file");
    expect(wrapper.emitted("accept")).toBeUndefined();

    drag(wrapper, "drop", file("blank.csv", 0));
    await wrapper.vm.$nextTick();
    expect(alertText(wrapper)).toContain("blank.csv is 0 B");
    expect(wrapper.emitted("reject")?.[1]).toEqual(["empty"]);
  });

  it("runs the dragover / dragleave / drop state machine", async () => {
    const wrapper = mount(DropZone);
    const zone = wrapper.get("[data-drop-zone]");
    expect(zone.attributes("data-dragging")).toBe("false");
    expect(wrapper.text()).toContain("Drop a CSV here");

    drag(wrapper, "dragenter");
    await wrapper.vm.$nextTick();
    expect(zone.attributes("data-dragging")).toBe("true");
    expect(wrapper.text()).toContain("Release to check the file");

    drag(wrapper, "dragleave");
    await wrapper.vm.$nextTick();
    expect(zone.attributes("data-dragging")).toBe("false");

    drag(wrapper, "dragover");
    await wrapper.vm.$nextTick();
    expect(zone.attributes("data-dragging")).toBe("true");

    drag(wrapper, "drop", file("revenue.csv", 512));
    await wrapper.vm.$nextTick();
    expect(zone.attributes("data-dragging")).toBe("false");
    expect(wrapper.emitted("accept")).toHaveLength(1);
  });

  it("is operable without a mouse: a labelled file input carries the same gate", async () => {
    const wrapper = mount(DropZone);
    const input = wrapper.get('input[type="file"]');
    expect(input.attributes("aria-label")).toBe("Choose a CSV file to upload");
    expect(input.attributes("disabled")).toBeUndefined();

    const el = input.element as HTMLInputElement;
    Object.defineProperty(el, "files", { value: [file("huge.csv", MAX_UPLOAD_BYTES + 1)], configurable: true });
    await input.trigger("change");

    expect(wrapper.emitted("accept")).toBeUndefined();
    expect(alertText(wrapper)).toContain("over the 5.00 MB cap");
  });

  it("shows a server refusal in the same alert region", async () => {
    const wrapper = mount(DropZone, { props: { serverError: "File is not valid UTF-8 text" } });
    expect(alertText(wrapper)).toBe("File is not valid UTF-8 text");
  });
});
