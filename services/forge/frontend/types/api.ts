// Forge's API contract, mirrored from services/forge/app/schemas.
// Identity's contract and the pagination envelope come from the shared layer.
export type {
  MembershipResponse,
  Page,
  SignupPayload,
  TokenPair,
  UserMeResponse,
  UserResponse,
} from "@crescent/ui/types/api";

// forge: DatasetResponse
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

// forge: DatasetSummary (GET /datasets/summary) — the dashboard's single call
export interface DatasetSummary {
  owned_count: number;
  sample_count: number;
  recent: DatasetResponse[];
}

// forge: DatasetPreview (GET /datasets/{id}/preview)
export interface DatasetPreview {
  columns: string[];
  rows: string[][];
  row_count: number; // total data rows in the dataset, not just the previewed ones
  truncated: boolean; // True when row_count exceeds the number of rows returned
}
