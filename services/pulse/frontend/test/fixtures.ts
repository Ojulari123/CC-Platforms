import type {
  ApproverCandidate,
  ReportResponse,
  RepositoryResponse,
  SyncRunResponse,
  UserMeResponse,
} from "~/types/api";

// Shapes only, so a test states the one field it is about and inherits the rest. These
// never reach the app: nothing here is fixture data the UI renders.

export function makeUser(over: Partial<UserMeResponse> = {}): UserMeResponse {
  return {
    id: 1042,
    email: "ada@example.com",
    first_name: "Ada",
    last_name: "Nwosu",
    avatar_url: null,
    email_verified: true,
    is_active: true,
    is_platform_admin: false,
    created_at: "2026-01-01T00:00:00Z",
    memberships: [],
    ...over,
  };
}

export function makeRepo(over: Partial<RepositoryResponse> = {}): RepositoryResponse {
  return {
    id: 4,
    github_repo_id: 900,
    full_name: "acme/pulse-api",
    owner: "acme",
    name: "pulse-api",
    private: true,
    is_tracked: true,
    default_branch: "main",
    dept_id: 1,
    lead_user_id: null,
    lead: null,
    deputy_user_id: null,
    deputy: null,
    last_synced_at: "2026-08-11T02:00:00Z",
    ...over,
  };
}

export function makeReport(over: Partial<ReportResponse> = {}): ReportResponse {
  return {
    id: 341,
    author_user_id: 1042,
    author: {
      user_id: 1042,
      first_name: "Ada",
      last_name: "Nwosu",
      avatar_url: null,
      is_active: true,
    },
    repo_id: 4,
    dept_id: 1,
    week_start: "2026-08-03",
    status: "submitted",
    summary_manager: "Split the report generator off the request path.",
    summary_exec: "Report generation no longer blocks the API.",
    next_week_goals: "Wire the approval emails to the same queue.",
    generated_at: null,
    prompt_version: null,
    created_at: "2026-08-03T09:00:00Z",
    updated_at: "2026-08-04T09:00:00Z",
    ...over,
  };
}

export function makeCandidate(over: Partial<ApproverCandidate> = {}): ApproverCandidate {
  return {
    user_id: 1043,
    person: {
      user_id: 1043,
      first_name: "Tunde",
      last_name: "Balogun",
      avatar_url: null,
      is_active: true,
    },
    has_activity: true,
    is_lead: false,
    is_deputy: false,
    ...over,
  };
}

export function makeRun(over: Partial<SyncRunResponse> = {}): SyncRunResponse {
  return {
    id: 812,
    repo_id: 4,
    repo_full_name: "acme/pulse-api",
    status: "success",
    detail: "acme/pulse-api: commits=3, branches=0, pull_requests=1, issues=0",
    started_at: "2026-08-11T02:00:04Z",
    finished_at: "2026-08-11T02:00:31Z",
    ...over,
  };
}
