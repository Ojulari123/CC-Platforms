// Forge's API contract, mirrored from services/forge/app/schemas.
// Identity's contract and the pagination envelope come from the shared layer.
export type {
  MembershipResponse,
  Page,
  TokenPair,
  UserMeResponse,
  UserResponse,
} from "@crescent/ui/types/api";

export interface DatasetResponse {
  id: number;
  owner_user_id: number | null;
  is_sample: boolean;
  name: string;
  original_filename: string | null;
  columns: string[];
  row_count: number;
  created_at: string;
}

export interface DatasetSummary {
  owned_count: number;
  sample_count: number;
  recent: DatasetResponse[];
}

export interface DatasetPreview {
  columns: string[];
  rows: string[][];
  row_count: number; // total data rows in the dataset, not just the previewed ones
  truncated: boolean; // True when row_count exceeds the number of rows returned
}

// Workflows, runs and generated code. Mirrors services/forge/app/schemas/workflows.py.

export type WorkflowKind =
  | "tabular_classification"
  | "tabular_regression"
  | "timeseries_forecast"
  | "llm_playground";

export type RunStatus = "queued" | "running" | "succeeded" | "failed";

export interface StepResponse {
  id: number;
  position: number;
  kind: string;
  params: Record<string, unknown>;
}

export interface StepIn {
  kind: string;
  params: Record<string, unknown>;
}

export interface WorkflowResponse {
  id: number;
  owner_user_id: number;
  name: string;
  kind: WorkflowKind;
  dataset_id: number | null;
  steps: StepResponse[];
  created_at: string;
}

export interface RunResponse {
  id: number;
  workflow_id: number;
  status: RunStatus;
  error: string | null;
  metrics: Record<string, number | null> | null;
  result: RunResult | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  created_at: string;
}

// What execution.py and runs.py put on the run row. Every field is optional here
// because a classification run, a forecast and a playground answer share one column.
export interface RunResult {
  target?: string;
  features?: string[];
  algorithm?: string;
  hyperparameters?: Record<string, number>;
  rows_used?: number;
  train_rows?: number;
  test_rows?: number;
  scaled?: boolean;
  dataset?: string;
  predictions_sample?: { actual: string | number; predicted: string | number }[];
  class_labels?: string[];
  confusion_matrix?: number[][];
  model?: string;
  reply?: string;
  prompt?: string;
  grounded?: boolean;
}

export interface GeneratedCode {
  filename: string;
  language: string;
  code: string;
}

export interface StepCatalogEntry {
  kind: string;
  label: string;
  summary: string;
  params: Record<string, unknown>;
}

export interface StepCatalog {
  steps: StepCatalogEntry[];
  steps_by_workflow_kind: Record<string, string[]>;
}
