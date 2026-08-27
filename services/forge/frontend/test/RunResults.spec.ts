import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import ConfusionMatrix from "../components/ConfusionMatrix.vue";
import PredictionScatter from "../components/PredictionScatter.vue";
import RunResults from "../components/RunResults.vue";
import type { RunResponse } from "../types/api";

const BASE: RunResponse = {
  id: 12,
  workflow_id: 3,
  status: "succeeded",
  error: null,
  metrics: null,
  result: null,
  started_at: null,
  finished_at: null,
  duration_ms: 2400,
  created_at: "2026-08-27T09:00:00Z",
};

function run(patch: Partial<RunResponse>): RunResponse {
  return { ...BASE, ...patch };
}

const components = { ConfusionMatrix, PredictionScatter };

describe("RunResults", () => {
  it("names each metric and says what it means, not just the number", () => {
    const wrapper = mount(RunResults, {
      props: { run: run({ metrics: { accuracy: 0.8421, f1_macro: 0.79 } }) },
      global: { components },
    });
    expect(wrapper.text()).toContain("Accuracy");
    expect(wrapper.text()).toContain("0.8421");
    expect(wrapper.text()).toContain("Share of held-back rows the model got right.");
  });

  it("draws a confusion matrix as a grid, one cell per actual-against-predicted pair", () => {
    const wrapper = mount(RunResults, {
      props: {
        run: run({
          metrics: { accuracy: 0.75 },
          result: { class_labels: ["no", "yes"], confusion_matrix: [[3, 1], [0, 4]] },
        }),
      },
      global: { components },
    });
    const cells = wrapper.findAll("tbody td");
    expect(cells.length).toBe(4);
    expect(cells[0]!.text()).toContain("3");
    expect(cells[3]!.text()).toContain("4");
    expect(wrapper.findAll("tbody th").map((th) => th.text())).toEqual(["no", "yes"]);
  });

  it("plots actual against predicted for a regression instead of a matrix", () => {
    const wrapper = mount(RunResults, {
      props: {
        run: run({
          metrics: { r2: 0.61 },
          result: {
            target: "price",
            predictions_sample: [
              { actual: 10, predicted: 11 },
              { actual: 20, predicted: 18 },
              { actual: 30, predicted: 31 },
            ],
          },
        }),
      },
      global: { components },
    });
    expect(wrapper.findComponent(PredictionScatter).exists()).toBe(true);
    expect(wrapper.findAll("svg circle").length).toBe(3);
    expect(wrapper.findComponent(ConfusionMatrix).exists()).toBe(false);
  });

  it("shows the model's reply as text, never as markup", () => {
    const wrapper = mount(RunResults, {
      props: {
        run: run({ metrics: { tokens: 412 }, result: { model: "gpt-4o-mini", reply: "<b>hello</b>", grounded: true } }),
      },
      global: { components },
    });
    expect(wrapper.text()).toContain("<b>hello</b>");
    expect(wrapper.html()).not.toContain("<b>hello</b>");
    expect(wrapper.text()).toContain("answered from your text only");
    expect(wrapper.text()).toContain("412");
  });

  it("says how the data was split, so the score has something to stand on", () => {
    const wrapper = mount(RunResults, {
      props: {
        run: run({
          metrics: { accuracy: 0.9 },
          result: { algorithm: "random_forest_classifier", target: "survived", rows_used: 800, train_rows: 640, test_rows: 160 },
        }),
      },
      global: { components },
    });
    expect(wrapper.text()).toContain("800 used · 640 train · 160 test");
    expect(wrapper.text()).toContain("random_forest_classifier");
  });
});
