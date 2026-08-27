import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import StepCard from "../components/StepCard.vue";
import Select from "../../../../packages/ui/components/Select.vue";

function mountCard(props: Record<string, unknown> = {}) {
  return mount(StepCard, {
    props: {
      kind: "handle_missing",
      params: { strategy: "median", columns: ["age"] },
      position: 3,
      total: 6,
      label: "Handle missing values",
      summary: "Drop rows with gaps, or fill them.",
      workflowKind: "tabular_classification",
      columns: ["age", "fare", "class"],
      ...props,
    },
    global: { components: { Select } },
  });
}

describe("StepCard", () => {
  it("puts the step's place in the run order on the card", () => {
    expect(mountCard().text()).toContain("step 3 of 6");
  });

  it("says what this step will do to the data with the settings as they stand", () => {
    expect(mountCard().text()).toContain("Fills gaps in age using Median.");
  });

  it("carries the summary the server's step catalog wrote", () => {
    expect(mountCard().text()).toContain("Drop rows with gaps, or fill them.");
  });

  it("spells out what the chosen strategy costs, not just its name", () => {
    expect(mountCard({ params: { strategy: "drop_rows", columns: [] } }).text())
      .toContain("Every row with a gap goes");
    expect(mountCard({ params: { strategy: "one_hot", columns: [] }, kind: "encode_categorical" }).text())
      .toContain("Adds one 0/1 column per distinct value");
  });

  it("offers the dataset's own columns as the things to act on, and marks the chosen ones", () => {
    const buttons = mountCard().findAll('button[aria-pressed]');
    expect(buttons.map((b) => b.text())).toEqual(["age", "fare", "class"]);
    expect(buttons[0]!.attributes("aria-pressed")).toBe("true");
    expect(buttons[1]!.attributes("aria-pressed")).toBe("false");
  });

  it("hands the edited parameters back rather than mutating them in place", async () => {
    const wrapper = mountCard();
    await wrapper.findAll('button[aria-pressed]')[1]!.trigger("click");
    expect(wrapper.emitted("update:params")![0]![0]).toEqual({ strategy: "median", columns: ["age", "fare"] });
  });

  it("only asks for a fill value when the strategy needs one", () => {
    expect(mountCard().text()).not.toContain("Fill value");
    expect(mountCard({ params: { strategy: "constant", columns: [] } }).text()).toContain("Fill value");
  });

  it("shows the prompt, its grounding text and the cost ceiling on an LLM step", () => {
    const wrapper = mountCard({
      kind: "prompt",
      workflowKind: "llm_playground",
      label: "Prompt",
      summary: "Send instructions and your own text to the language model.",
      params: { system: "You are terse.", prompt: "Summarise this.", context: "some notes", max_tokens: 500 },
      columns: [],
    });
    expect(wrapper.findAll("textarea").length).toBe(3);
    expect(wrapper.text()).toContain("Reply length ceiling");
    expect(wrapper.text()).toContain("Sends your prompt with your own text as the only source.");
  });

  it("refuses to hide the last step behind a remove button", () => {
    expect(mountCard({ removable: false }).text()).not.toContain("Remove");
  });
});
