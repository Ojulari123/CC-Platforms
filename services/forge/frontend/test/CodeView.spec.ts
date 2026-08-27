import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import CodeView from "../components/CodeView.vue";

const SCRIPT = `import pandas as pd

# step 1 of 2 — load_csv: read the CSV into a table
df = pd.read_csv(DATA_PATH)

# step 2 of 2 — prompt: what you asked the model
PROMPT = '<script>alert(1)</script>'
`;

describe("CodeView", () => {
  it("labels every block with the step number and kind it came from", () => {
    const sections = mount(CodeView, { props: { code: SCRIPT } }).findAll("section");
    expect(sections.length).toBe(3);
    expect(sections[1]!.text()).toContain("step 1");
    expect(sections[1]!.text()).toContain("load_csv");
    expect(sections[2]!.text()).toContain("step 2");
    expect(sections[2]!.text()).toContain("prompt");
  });

  it("marks the block belonging to the step the canvas is pointing at", () => {
    const wrapper = mount(CodeView, { props: { code: SCRIPT, activeKind: "prompt" } });
    const sections = wrapper.findAll("section");
    expect(sections[2]!.classes()).toContain("bg-surface-active");
    expect(sections[1]!.classes()).not.toContain("bg-surface-active");
  });

  it("tells the canvas which step a block belongs to when it is hovered", async () => {
    const wrapper = mount(CodeView, { props: { code: SCRIPT } });
    await wrapper.findAll("section")[1]!.trigger("mouseenter");
    expect(wrapper.emitted("hover")![0]).toEqual(["load_csv"]);
  });

  it("renders generated code as text, so a tag in a prompt stays a tag on screen", () => {
    const wrapper = mount(CodeView, { props: { code: SCRIPT } });
    expect(wrapper.text()).toContain("<script>alert(1)</script>");
    expect(wrapper.html()).not.toContain("<script>alert(1)");
    expect(wrapper.findAll("pre").length).toBe(3);
  });

  it("keeps the code monospace, unwrapped and scrollable sideways", () => {
    const pre = mount(CodeView, { props: { code: SCRIPT } }).findAll("pre")[1]!;
    expect(pre.classes()).toEqual(expect.arrayContaining(["mono", "whitespace-pre", "overflow-x-auto"]));
  });

  it("says so plainly when there is nothing to generate", () => {
    expect(mount(CodeView, { props: { code: "" } }).text()).toContain("Nothing to generate yet");
  });
});
