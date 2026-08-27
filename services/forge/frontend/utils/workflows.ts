// The canvas vocabulary, mirrored from services/forge/app/services/steps.py. The server
// validates all of it again and its refusals are what the UI shows; this copy exists so a
// step can be drawn as a form with its choices on display instead of a JSON box.
import type { RunResponse, RunStatus, WorkflowKind } from "~/types/api";
import { statusOf } from "~/utils/upload";

export const KIND_OPTIONS: { value: WorkflowKind; label: string; blurb: string; needsDataset: boolean }[] = [
  {
    value: "tabular_classification",
    label: "Classification",
    blurb: "Predict which class a row belongs to, e.g. survived or not. Scored on accuracy and a confusion matrix.",
    needsDataset: true,
  },
  {
    value: "tabular_regression",
    label: "Regression",
    blurb: "Predict a number from the other columns, e.g. a price. Scored on R², mean absolute error and RMSE.",
    needsDataset: true,
  },
  {
    value: "timeseries_forecast",
    label: "Forecast",
    blurb: "Predict the next values of one column from its own past. The lag step is what turns the series into rows.",
    needsDataset: true,
  },
  {
    value: "llm_playground",
    label: "LLM playground",
    blurb: "Send a prompt, and optionally your own text, to the language model and read the reply and its token cost.",
    needsDataset: false,
  },
];

export const MISSING_STRATEGIES = ["drop_rows", "mean", "median", "most_frequent", "constant"] as const;
export const ENCODE_STRATEGIES = ["one_hot", "ordinal"] as const;
export const SCALE_STRATEGIES = ["standard", "minmax"] as const;

const CLASSIFIER_ALGORITHMS = ["logistic_regression", "random_forest_classifier", "decision_tree_classifier"];
const REGRESSOR_ALGORITHMS = ["linear_regression", "ridge", "random_forest_regressor"];

export const ALGORITHMS_FOR_KIND: Record<WorkflowKind, string[]> = {
  tabular_classification: CLASSIFIER_ALGORITHMS,
  tabular_regression: REGRESSOR_ALGORITHMS,
  timeseries_forecast: REGRESSOR_ALGORITHMS,
  llm_playground: [],
};

export const ALLOWED_HYPERPARAMETERS = ["n_estimators", "max_depth", "min_samples_leaf", "max_iter", "C", "alpha", "random_state"];

export function humanise(value: string): string {
  return value.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

export type FieldType = "select" | "columns" | "column" | "number" | "text" | "textarea" | "toggle" | "hyperparameters";

export interface StepField {
  key: string;
  label: string;
  type: FieldType;
  options?: string[];
  /** Shown under the control. Plain language about what the choice costs you. */
  note?: string;
  placeholder?: string;
  min?: number;
  max?: number;
  step?: number;
  rows?: number;
  /** Only rendered when this predicate holds for the current params. */
  when?: (params: Record<string, unknown>) => boolean;
}

const STRATEGY_NOTES: Record<string, string> = {
  drop_rows: "Every row with a gap goes, so a column with many blanks can take most of your data with it.",
  mean: "Keeps the row count. The average is pulled around by outliers.",
  median: "Keeps the row count. The middle value holds up better when a few rows are extreme.",
  most_frequent: "Fills with the commonest value, which is the sensible choice for a category column.",
  constant: "Fills every gap with the one value you give, so a missing reading stays visible as itself.",
  one_hot: "Adds one 0/1 column per distinct value. A column with hundreds of values becomes hundreds of columns.",
  ordinal: "Numbers the values 0, 1, 2. The model reads that as an ordering, so use it when the order is real.",
  standard: "Centres each column on 0 with a spread of 1. Fitted after the split, so the test rows stay unseen.",
  minmax: "Squeezes each column into 0 to 1, which keeps outliers visible as the extremes.",
};

export function strategyNote(value: unknown): string | undefined {
  return typeof value === "string" ? STRATEGY_NOTES[value] : undefined;
}

// Which controls each step draws, in the order they read.
export const STEP_FIELDS: Record<string, StepField[]> = {
  load_csv: [],
  select_target: [
    { key: "column", label: "Target column", type: "column", note: "The column the model predicts. It is held out of the features automatically." },
  ],
  lag_features: [
    { key: "column", label: "Value column", type: "column", note: "The series being forecast. It has to be numeric." },
    { key: "lags", label: "Lags", type: "number", min: 1, max: 50, step: 1, note: "How many previous readings each row sees. More history per row means fewer usable rows." },
    { key: "horizon", label: "Horizon", type: "number", min: 1, max: 50, step: 1, note: "How many steps ahead to predict. Further ahead is a harder question." },
  ],
  handle_missing: [
    { key: "strategy", label: "Strategy", type: "select", options: [...MISSING_STRATEGIES] },
    { key: "fill_value", label: "Fill value", type: "text", when: (p) => p.strategy === "constant", note: "Required by the constant strategy." },
    { key: "columns", label: "Columns", type: "columns", note: "Leave empty to apply this to every column." },
  ],
  encode_categorical: [
    { key: "strategy", label: "Strategy", type: "select", options: [...ENCODE_STRATEGIES] },
    { key: "columns", label: "Columns", type: "columns", note: "Leave empty to encode every text column." },
  ],
  scale_features: [
    { key: "strategy", label: "Strategy", type: "select", options: [...SCALE_STRATEGIES] },
    { key: "columns", label: "Columns", type: "columns", note: "Leave empty to scale every numeric feature." },
  ],
  select_features: [
    { key: "columns", label: "Feature columns", type: "columns", note: "The columns the model learns from. Empty means everything except the target." },
  ],
  train_test_split: [
    { key: "test_size", label: "Held back share", type: "number", min: 0.05, max: 0.5, step: 0.05, note: "0.2 keeps a fifth of the rows back. A bigger share gives a more honest score and less data to learn from." },
    { key: "random_state", label: "Random state", type: "number", step: 1, note: "The same number gives the same split every run, which is what makes two runs comparable." },
    { key: "shuffle", label: "Shuffle rows", type: "toggle", note: "Turn this off for a forecast: the test rows have to come after the training rows in time." },
  ],
  train_model: [
    { key: "algorithm", label: "Algorithm", type: "select" },
    { key: "hyperparameters", label: "Hyperparameters", type: "hyperparameters", note: "Passed straight to scikit-learn. Anything outside the allowed list is refused rather than ignored." },
  ],
  evaluate: [],
  prompt: [
    { key: "system", label: "System instruction", type: "textarea", rows: 2, note: "How the model should behave before it sees your question." },
    { key: "prompt", label: "Prompt", type: "textarea", rows: 4, placeholder: "Summarise this in three bullet points." },
    { key: "context", label: "Your text", type: "textarea", rows: 6, note: "Optional. Anything here becomes the only source the answer may draw on, which is how you ground a reply in your own document." },
    { key: "max_tokens", label: "Reply length ceiling", type: "number", min: 1, max: 4000, step: 50, note: "Tokens are what you are billed for, so this is the cost ceiling for one run." },
  ],
};

export function defaultParams(kind: string, workflowKind: WorkflowKind): Record<string, unknown> {
  switch (kind) {
    case "handle_missing":
      return { strategy: "median", columns: [] };
    case "encode_categorical":
      return { strategy: "one_hot", columns: [] };
    case "scale_features":
      return { strategy: "standard", columns: [] };
    case "select_features":
      return { columns: [] };
    case "select_target":
      return { column: "" };
    case "lag_features":
      return { column: "", lags: 3, horizon: 1 };
    case "train_test_split":
      return { test_size: 0.2, random_state: 42, shuffle: workflowKind !== "timeseries_forecast" };
    case "train_model":
      return { algorithm: ALGORITHMS_FOR_KIND[workflowKind][0] ?? "", hyperparameters: {} };
    case "prompt":
      return { system: "You are a helpful assistant.", prompt: "", context: "", max_tokens: 500 };
    default:
      return {};
  }
}

/* The shortest sequence that passes validate_sequence, so a new workflow opens on
   something runnable rather than an empty page. The column has to be picked before the
   workflow is created: steps.py refuses a select_target with no column, so a starter with
   a blank one would be rejected at creation and the learner would never see the canvas. */
export function starterSteps(kind: WorkflowKind, column = ""): { kind: string; params: Record<string, unknown> }[] {
  // The prompt is the column's opposite number: steps.py refuses an empty one, so the
  // playground is created with the first question already in it.
  if (kind === "llm_playground") return [{ kind: "prompt", params: { ...defaultParams("prompt", kind), prompt: column } }];
  const kinds = kind === "timeseries_forecast"
    ? ["load_csv", "lag_features", "train_test_split", "train_model", "evaluate"]
    : ["load_csv", "select_target", "handle_missing", "train_test_split", "train_model", "evaluate"];
  return kinds.map((k) => {
    const params = defaultParams(k, kind);
    if (k === "select_target" || k === "lag_features") params.column = column;
    return { kind: k, params };
  });
}

// steps.py CANONICAL_ORDER. A pipeline only works one way round, so the canvas shows the
// order the run will use rather than the order the steps were added.
const CANONICAL_ORDER: Record<string, number> = {
  load_csv: 0,
  lag_features: 1,
  select_target: 2,
  handle_missing: 3,
  encode_categorical: 4,
  select_features: 5,
  train_test_split: 6,
  scale_features: 7,
  train_model: 8,
  evaluate: 9,
  prompt: 0,
};

export function orderSteps<T extends { kind: string }>(steps: T[]): T[] {
  return steps
    .map((step, index) => ({ step, index }))
    .sort((a, b) => (CANONICAL_ORDER[a.step.kind] ?? 99) - (CANONICAL_ORDER[b.step.kind] ?? 99) || a.index - b.index)
    .map((entry) => entry.step);
}

/* What this step will do to the data, given the parameters as they stand. The point of
   the canvas is that a learner can read down it before pressing Run, and a line that says
   "median, 3 columns" says more than the step's name does. */
export function describeStep(kind: string, params: Record<string, unknown>): string {
  const columns = Array.isArray(params.columns) ? (params.columns as string[]) : [];
  const scope = columns.length ? columns.join(", ") : "every applicable column";
  switch (kind) {
    case "load_csv":
      return "Reads the attached dataset into a table.";
    case "select_target":
      return params.column ? `Predicts ${params.column}.` : "No target chosen yet.";
    case "lag_features":
      return params.column
        ? `Rebuilds ${params.column} as ${params.lags} previous readings per row, predicting ${params.horizon} step(s) ahead.`
        : "No value column chosen yet.";
    case "handle_missing":
      return params.strategy === "drop_rows"
        ? `Drops rows with gaps in ${scope}.`
        : `Fills gaps in ${scope} using ${humanise(String(params.strategy ?? ""))}.`;
    case "encode_categorical":
      return `Turns ${scope} into numbers using ${humanise(String(params.strategy ?? ""))}.`;
    case "scale_features":
      return `Rescales ${scope} using ${humanise(String(params.strategy ?? ""))}.`;
    case "select_features":
      return columns.length ? `Learns from ${columns.join(", ")}.` : "Learns from every column except the target.";
    case "train_test_split": {
      const percent = Math.round(Number(params.test_size ?? 0) * 100);
      return `Holds back ${percent}% of the rows, ${params.shuffle ? "shuffled" : "in order"}, seed ${params.random_state}.`;
    }
    case "train_model":
      return `Fits ${humanise(String(params.algorithm ?? ""))} on the training rows.`;
    case "evaluate":
      return "Scores the fitted model on the held-back rows.";
    case "prompt":
      return params.context ? "Sends your prompt with your own text as the only source." : "Sends your prompt on its own.";
    default:
      return "";
  }
}

/* One block of the generated script. codegen.py writes `# step N of M — kind: text` above
   every block, so the mapping from canvas to code is something the server already states
   and the browser only has to read. Nothing is inferred from line content. */
export interface CodeBlock {
  heading: string;
  /** The step kind this block came from, or "" for the header and imports. */
  kind: string;
  position: number | null;
  lines: string[];
}

const HEADING = /^# step (\d+) of \d+ — ([a-z_]+): (.*)$/;

export function parseCodeBlocks(code: string): CodeBlock[] {
  const blocks: CodeBlock[] = [];
  let current: CodeBlock = { heading: "Header and imports", kind: "", position: null, lines: [] };
  for (const line of code.split("\n")) {
    const match = HEADING.exec(line);
    if (match) {
      blocks.push(current);
      current = { heading: match[3]!, kind: match[2]!, position: Number(match[1]), lines: [] };
    } else {
      current.lines.push(line);
    }
  }
  blocks.push(current);
  return blocks.map((block) => ({ ...block, lines: trimBlank(block.lines) }));
}

function trimBlank(lines: string[]): string[] {
  let start = 0;
  let end = lines.length;
  while (start < end && lines[start]!.trim() === "") start += 1;
  while (end > start && lines[end - 1]!.trim() === "") end -= 1;
  return lines.slice(start, end);
}

export const RUN_TONES: Record<RunStatus, "muted" | "info" | "ok" | "bad"> = {
  queued: "muted",
  running: "info",
  succeeded: "ok",
  failed: "bad",
};

export function isSettled(run: RunResponse | undefined | null): boolean {
  return run?.status === "succeeded" || run?.status === "failed";
}

export function formatDuration(ms: number | null): string {
  if (ms === null) return "";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

// Higher is better for these; the error measures read the other way.
const HIGHER_IS_BETTER = new Set(["accuracy", "precision_macro", "recall_macro", "f1_macro", "r2"]);

export const METRIC_LABELS: Record<string, string> = {
  accuracy: "Accuracy",
  precision_macro: "Precision",
  recall_macro: "Recall",
  f1_macro: "F1",
  r2: "R²",
  mae: "Mean absolute error",
  rmse: "RMSE",
  mape_percent: "MAPE",
  tokens: "Tokens used",
};

export const METRIC_MEANS: Record<string, string> = {
  accuracy: "Share of held-back rows the model got right.",
  precision_macro: "Of the rows it called a class, how many were that class. Averaged over classes.",
  recall_macro: "Of the rows that were a class, how many it found. Averaged over classes.",
  f1_macro: "Precision and recall in one number, averaged over classes.",
  r2: "How much of the variation the model explains. 1.0 is perfect, 0 is no better than the average.",
  mae: "Average size of the miss, in the target's own units.",
  rmse: "Like the average miss, but large misses count for more.",
  mape_percent: "Average miss as a percentage of the actual value.",
  tokens: "What this run cost against your budget.",
};

/** A 0 to 1 bar only makes sense for the bounded scores. */
export function barFraction(name: string, value: number): number | null {
  if (!HIGHER_IS_BETTER.has(name)) return null;
  if (name === "r2") return Math.max(0, Math.min(1, value));
  return Math.max(0, Math.min(1, value));
}

export function formatMetric(name: string, value: number): string {
  if (name === "mape_percent") return `${value.toFixed(2)}%`;
  if (name === "tokens") return String(value);
  return Number.isInteger(value) ? String(value) : value.toFixed(4);
}

/* The sentence the server wrote for the learner, when the server was talking to them. A
   4xx detail names the thing to change; a 5xx detail is an exception message and not copy. */
export function apiDetail(err: unknown, fallback: string): string {
  const detail = (err as { data?: { detail?: unknown } })?.data?.detail;
  const text = typeof detail === "string" && detail.trim() ? detail.trim() : "";
  const status = statusOf(err);
  if (!text || status === undefined || status >= 500 || status === 401) return fallback;
  return text;
}
