/* The canvas vocabulary: twelve modules in four groups. Both the workspace roadmap and
   /canvas draw from this one list so they cannot describe different products.

   `live` is whether the canvas has a step that does it today, checked against the step
   catalog the server publishes at /workflows/steps. Nine of the twelve are built. The
   three that are not are the ones the not-yet list names, and this is the flag that keeps
   the two from drifting apart. */

export interface Module {
  name: string;
  live: boolean;
}

export interface ModuleGroup {
  group: string;
  modules: Module[];
}

export const MODULE_GROUPS: ModuleGroup[] = [
  {
    group: "Data in",
    modules: [
      { name: "Dataset", live: true }, // load_csv
      { name: "Join", live: false },
      { name: "Filter rows", live: false },
    ],
  },
  {
    group: "Prepare",
    modules: [
      { name: "Drop columns", live: true }, // select_features picks what to keep
      { name: "Fill blanks", live: true }, // handle_missing
      { name: "Encode text", live: true }, // encode_categorical
    ],
  },
  {
    group: "Model",
    modules: [
      { name: "Classify", live: true },
      { name: "Regress", live: true },
      { name: "Forecast", live: true }, // lag_features + train_model
    ],
  },
  {
    group: "Results out",
    modules: [
      { name: "Score card", live: true }, // evaluate
      { name: "Chart", live: true }, // confusion matrix and prediction scatter
      { name: "Export CSV", live: false },
    ],
  },
];
