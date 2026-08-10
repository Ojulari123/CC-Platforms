// Pulse's API contract, mirrored from services/pulse/app/schemas.
// Identity's contract and the pagination envelope come from the shared layer.
export type { MembershipResponse, Page, UserMeResponse, UserResponse } from "@crescent/ui/types/api";

// pulse: UserRef — a person as Pulse is allowed to know them. Always sits alongside
// the user_id it describes, and is null when identity couldn't be reached.
export interface UserRef {
  user_id: number;
  first_name: string;
  last_name: string;
  avatar_url: string | null;
  is_active: boolean;
}

// pulse: ReportStatus
export type ReportStatus =
  | "draft"
  | "submitted"
  | "changes_requested"
  | "approved"
  | "rejected";

// pulse: ReportResponse
export interface ReportResponse {
  id: number;
  author_user_id: number;
  author: UserRef | null;
  repo_id: number;
  dept_id: number | null;
  week_start: string;
  status: string;
  summary_manager: string | null;
  summary_exec: string | null;
  next_week_goals: string | null;
  generated_at: string | null;
  prompt_version: string | null;
  created_at: string;
  updated_at: string;
}

// pulse: ApprovalResponse
export interface ApprovalResponse {
  id: number;
  report_id: number;
  actor_user_id: number;
  actor: UserRef | null;
  action: string;
  note: string | null;
  created_at: string;
}

// pulse: CommentResponse
export interface CommentResponse {
  id: number;
  report_id: number;
  author_user_id: number;
  author: UserRef | null;
  body: string;
  created_at: string;
  edited_at: string | null;
}

// pulse: RepositoryResponse
export interface RepositoryResponse {
  id: number;
  github_repo_id: number;
  full_name: string;
  owner: string;
  name: string;
  private: boolean;
  is_tracked: boolean;
  default_branch: string | null;
  dept_id: number | null;
  lead_user_id: number | null;
  lead: UserRef | null;
  deputy_user_id: number | null;
  deputy: UserRef | null;
  last_synced_at: string | null;
}

// pulse: ActivityResponse and its item types
export interface ActivityCounts {
  commits: number;
  pull_requests: number;
  reviews: number;
  issues: number;
}

export interface CommitItem {
  repo_id: number;
  sha: string;
  message: string | null;
  url: string | null;
  committed_at: string;
}

export interface PullRequestItem {
  repo_id: number;
  number: number;
  title: string | null;
  state: string;
  merged: boolean;
  url: string | null;
  gh_created_at: string | null;
}

export interface ReviewItem {
  pull_request_id: number;
  state: string;
  submitted_at: string | null;
  url: string | null;
}

export interface IssueItem {
  repo_id: number;
  number: number;
  title: string | null;
  state: string;
  url: string | null;
  gh_created_at: string | null;
}

export interface ActivityResponse {
  user_id: number;
  user: UserRef | null;
  since: string | null;
  counts: ActivityCounts;
  recent_commits: CommitItem[];
  recent_pull_requests: PullRequestItem[];
  recent_reviews: ReviewItem[];
  recent_issues: IssueItem[];
}

// pulse: GitHubAccountResponse
export interface GitHubAccountResponse {
  user_id: number;
  github_user_id: number;
  github_login: string;
  scopes: string | null;
  connected_at: string;
}

// pulse: SyncRunResponse
export interface SyncRunResponse {
  id: number;
  repo_id: number | null;
  repo_full_name: string | null;
  status: string;
  detail: string | null;
  started_at: string;
  finished_at: string | null;
}

// identity: DepartmentResponse (GET /departments)
export interface DepartmentResponse {
  id: number;
  name: string;
  slug: string;
  head_user_id: number | null;
  head_name: string | null;
}

// identity: MemberResponse / MemberListResponse (GET /departments/{id}/members)
export interface MemberResponse {
  user_id: number;
  email: string;
  first_name: string;
  last_name: string;
  role: string;
  team_id: number | null;
}

export interface MemberListResponse {
  items: MemberResponse[];
  total: number;
  limit: number;
  offset: number;
}
