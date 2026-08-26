export type { MembershipResponse, Page, UserMeResponse, UserResponse } from "@crescent/ui/types/api";

export interface UserRef {
  user_id: number;
  first_name: string;
  last_name: string;
  avatar_url: string | null;
  is_active: boolean;
}

export type ReportStatus =
  | "draft"
  | "submitted"
  | "changes_requested"
  | "approved"
  | "rejected";

/* A weekly report is one repository for one week; a custom report is any range, any
   repository — including one Pulse does not track — and one section per contributor.
   Both come back through the same shape, so the nullable fields are the ones that only
   one kind fills in. Mirrors services/pulse/app/schemas/reports.py. */

export type ReportKind = "weekly" | "adhoc";

export interface ReportSubjectResponse {
  id: number;
  report_id: number;
  subject_user_id: number | null;
  subject: UserRef | null;
  subject_github_login: string | null;
  section: string | null;
  position: number;
  created_at: string;
}

export interface ReportResponse {
  id: number;
  author_user_id: number;
  author: UserRef | null;
  subject_user_id: number | null;
  subject: UserRef | null;
  subject_github_login: string | null;
  // Null on a custom report for a repository Pulse does not track: repo_full_name
  // carries the name instead, and nothing may look the id up without a null check.
  repo_id: number | null;
  repo_full_name: string | null;
  dept_id: number | null;
  kind: string;
  week_start: string | null;
  range_start: string | null;
  range_end: string | null;
  subjects: ReportSubjectResponse[];
  status: string;
  summary_manager: string | null;
  summary_exec: string | null;
  next_week_goals: string | null;
  generated_at: string | null;
  prompt_version: string | null;
  persona_id: number | null;
  created_at: string;
  updated_at: string;
}

/* Personas: the four dials a report's wording is generated from. A persona whose
   owner_user_id is null is a system preset — readable by everyone, editable by nobody,
   and the API answers 403 to an edit or a delete of one. */

export type PersonaLength = "brief" | "standard" | "detailed";
export type PersonaAudience = "executive" | "manager" | "engineer";
export type PersonaTechnicalDepth = "low" | "medium" | "high";
export type PersonaFormality = "casual" | "neutral" | "formal";

export interface PersonaResponse {
  id: number;
  owner_user_id: number | null;
  name: string;
  length: string;
  audience: string;
  technical_depth: string;
  formality: string;
  instructions: string | null;
  is_default: boolean;
  is_system: boolean;
  created_at: string;
  updated_at: string;
}

/* An API key someone brought themselves. The key itself is never in a response: the
   server holds it encrypted and answers with its last four digits only. */

export type CredentialScope = "user" | "department";
export type CredentialProvider = "openai" | "anthropic";

export interface CredentialResponse {
  id: number;
  scope: string;
  owner_user_id: number | null;
  dept_id: number | null;
  provider: string;
  model: string | null;
  last_four: string;
  bypass_token_cap: boolean;
  created_by_user_id: number;
  created_at: string;
  updated_at: string;
}

export interface CredentialList {
  items: CredentialResponse[];
}

export interface EffectiveCredentialResponse {
  source: "user" | "department" | "platform" | "none";
  provider: string | null;
  model: string | null;
  bypass_token_cap: boolean;
}

/* The daily token allowance. A cap can be set for one person, for a department or for the
   platform, and the narrowest one that applies is the one a call is measured against. */

export type BudgetScope = "user" | "department" | "platform";
export type BudgetSource = "user" | "department" | "platform" | "platform_default";

export interface BudgetResponse {
  id: number;
  scope: string;
  owner_user_id: number | null;
  dept_id: number | null;
  daily_token_cap: number;
  created_by_user_id: number;
  created_at: string;
  updated_at: string;
}

export interface BudgetList {
  items: BudgetResponse[];
}

export interface EffectiveBudgetResponse {
  daily_token_cap: number;
  source: BudgetSource;
  // What the cap would fall back to if the row at `source` were removed.
  inherited_cap: number;
  inherited_source: BudgetSource;
  tokens_used_today: number;
  /* False for anyone drawing on the platform key or their department's: you may only raise
     a limit on spend you are paying for yourself. */
  may_raise: boolean;
  /* Whether the token figures mean anything to this person, which is the same rule the
     API's own refusal messages follow. A user under a department key gets this without
     `may_raise`: the money is being spent on them, but it is not theirs to spend more of. */
  show_figures: boolean;
}

export interface ApprovalResponse {
  id: number;
  report_id: number;
  actor_user_id: number;
  actor: UserRef | null;
  action: string;
  note: string | null;
  created_at: string;
}

export interface CommentResponse {
  id: number;
  report_id: number;
  author_user_id: number;
  author: UserRef | null;
  body: string;
  created_at: string;
  edited_at: string | null;
}

export interface JournalResponse {
  id: number;
  repo_id: number;
  author_user_id: number;
  author: UserRef | null;
  body: string;
  created_at: string;
  edited_at: string | null;
}

export interface RollupResponse {
  id: number;
  repo_id: number;
  summary: string;
  entry_count: number;
  covers_from: string | null;
  covers_to: string | null;
  generated_by_user_id: number;
  generated_by: UserRef | null;
  model: string | null;
  prompt_version: string | null;
  created_at: string;
}

/* A wrapper, not a nullable body: a repository with no rollup yet is a normal state and
   the API answers 200 with `rollup: null` for it. A 404 from this endpoint now means one
   thing only — the repository is not visible to you. */
export interface LatestRollupResponse {
  rollup: RollupResponse | null;
}

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

export interface ApproverCandidate {
  user_id: number;
  person: UserRef | null;
  has_activity: boolean;
  is_lead: boolean;
  is_deputy: boolean;
}

export interface ApproverCandidateList {
  items: ApproverCandidate[];
}

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

export interface GitHubAccountResponse {
  user_id: number;
  github_user_id: number;
  github_login: string;
  scopes: string | null;
  connected_at: string;
}

// Same shape of answer as LatestRollupResponse, for the same reason: not having connected
// GitHub is where every account starts, so it is a 200 with `account: null`.
export interface ConnectedAccountResponse {
  account: GitHubAccountResponse | null;
}

export interface SyncRunResponse {
  id: number;
  repo_id: number | null;
  repo_full_name: string | null;
  status: string;
  detail: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface DepartmentResponse {
  id: number;
  name: string;
  slug: string;
  head_user_id: number | null;
  head_name: string | null;
}

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

/* The assistant. Mirrors services/pulse/app/schemas/chat.py — an indexed repository is a
   snapshot of one commit, chunked and embedded, that questions are answered from. */

/* `paused` is stopped, not broken: the daily AI allowance ran out or the embedding
   provider asked for a wait, and everything already embedded is kept. Indexing the same
   repository again carries on from there. Only `ready` is ever searched. */
export type IndexStatus = "pending" | "running" | "ready" | "error" | "rate_limited" | "paused";

export interface IndexedRepo {
  id: number;
  repo_id: number | null;
  full_name: string;
  is_public: boolean;
  owner_user_id: number;
  commit_sha: string | null;
  status: IndexStatus;
  detail: string | null;
  file_count: number;
  chunk_count: number;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

export interface GitHubIndexStatus {
  connected: boolean;
  has_repo_scope: boolean;
  // The server's own verdict and its own wording. Branch on the boolean and render the
  // string; matching the prose would break the moment somebody fixes a typo in it.
  reconnect_required: boolean;
  detail: string | null;
}

export interface Citation {
  // Null once the index it came from is deleted: chat history keeps the citation,
  // the FK is SET NULL. Nothing may key or link off this without a null check.
  indexed_repo_id: number | null;
  full_name: string;
  path: string;
  start_line: number;
  end_line: number;
  snippet: string;
}

export interface ChatMessage {
  id: number;
  conversation_id: number;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  model: string | null;
  tokens: number | null;
  created_at: string;
}

export interface Conversation {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail extends Conversation {
  messages: ChatMessage[];
}
