// The canvas vocabulary: twelve modules in four groups. Nothing here runs — it is the
// shape of the builder, written down before it exists, and both the workspace roadmap
// and /canvas draw from this one list so they cannot describe different products.

export interface ModuleGroup {
  group: string;
  modules: string[];
}

export const MODULE_GROUPS: ModuleGroup[] = [
  { group: "Data in", modules: ["Dataset", "Join", "Filter rows"] },
  { group: "Prepare", modules: ["Drop columns", "Fill blanks", "Encode text"] },
  { group: "Model", modules: ["Classify", "Regress", "Forecast"] },
  { group: "Results out", modules: ["Score card", "Chart", "Export CSV"] },
];
