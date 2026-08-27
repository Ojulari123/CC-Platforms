import type {
  ApproverCandidate,
  BudgetResponse,
  ChatMessage,
  Citation,
  Conversation,
  CredentialResponse,
  EffectiveBudgetResponse,
  GitHubAccountResponse,
  EffectiveCredentialResponse,
  IndexedRepo,
  JournalResponse,
  MemberResponse,
  PersonaResponse,
  ReportResponse,
  ReportSubjectResponse,
  RepositoryResponse,
  RollupResponse,
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
    subject_user_id: null,
    subject: null,
    subject_github_login: null,
    repo_id: 4,
    repo_full_name: null,
    dept_id: 1,
    kind: "weekly",
    week_start: "2026-08-03",
    range_start: null,
    range_end: null,
    subjects: [],
    persona_id: null,
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

export function makeJournal(over: Partial<JournalResponse> = {}): JournalResponse {
  return {
    id: 7,
    repo_id: 4,
    author_user_id: 1042,
    author: {
      user_id: 1042,
      first_name: "Ada",
      last_name: "Nwosu",
      avatar_url: null,
      is_active: true,
    },
    body: "Splitting the sync worker off the request path.",
    created_at: "2026-08-20T09:00:00Z",
    edited_at: null,
    ...over,
  };
}

export function makeRollup(over: Partial<RollupResponse> = {}): RollupResponse {
  return {
    id: 3,
    repo_id: 4,
    summary: "The week went on the sync worker and the approval emails.",
    entry_count: 6,
    covers_from: "2026-08-14T09:00:00Z",
    covers_to: "2026-08-20T09:00:00Z",
    generated_by_user_id: 1042,
    generated_by: {
      user_id: 1042,
      first_name: "Ada",
      last_name: "Nwosu",
      avatar_url: null,
      is_active: true,
    },
    model: "claude-sonnet-4-5",
    prompt_version: "journal-rollup-v1",
    created_at: "2026-08-20T10:00:00Z",
    ...over,
  };
}

export function makeIndexedRepo(over: Partial<IndexedRepo> = {}): IndexedRepo {
  return {
    id: 71,
    repo_id: 4,
    full_name: "acme/pulse-api",
    is_public: false,
    owner_user_id: 1042,
    commit_sha: "9f2c1ab4d5e6f708192a3b4c5d6e7f8091a2b3c4",
    status: "ready",
    detail: null,
    file_count: 214,
    chunk_count: 1830,
    started_at: "2026-08-24T09:00:00Z",
    finished_at: "2026-08-24T09:02:11Z",
    created_at: "2026-08-24T08:59:58Z",
    ...over,
  };
}

export function makeConversation(over: Partial<Conversation> = {}): Conversation {
  return {
    id: 12,
    title: "Where is the refresh token rotated?",
    created_at: "2026-08-24T10:00:00Z",
    updated_at: "2026-08-24T10:00:04Z",
    ...over,
  };
}

export function makeCitation(over: Partial<Citation> = {}): Citation {
  return {
    indexed_repo_id: 71,
    full_name: "acme/pulse-api",
    path: "app/services/tokens.py",
    start_line: 40,
    end_line: 58,
    snippet: "def rotate(refresh: str) -> TokenPair:\n    old = _lookup(refresh)\n    _revoke(old)\n    return _issue(old.user_id)",
    ...over,
  };
}

export function makeChatMessage(over: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: 300,
    conversation_id: 12,
    role: "assistant",
    content: "The refresh token is rotated in rotate(), which revokes the presented token before issuing the new pair.",
    citations: [makeCitation()],
    model: "claude-sonnet-4-5",
    tokens: 812,
    created_at: "2026-08-24T10:00:04Z",
    ...over,
  };
}

export function makeSubject(over: Partial<ReportSubjectResponse> = {}): ReportSubjectResponse {
  return {
    id: 900,
    report_id: 341,
    subject_user_id: 1042,
    subject: {
      user_id: 1042,
      first_name: "Ada",
      last_name: "Nwosu",
      avatar_url: null,
      is_active: true,
    },
    subject_github_login: null,
    section: "Landed the sync worker split.",
    position: 0,
    created_at: "2026-08-24T09:00:00Z",
    ...over,
  };
}

export function makePersona(over: Partial<PersonaResponse> = {}): PersonaResponse {
  return {
    id: 21,
    owner_user_id: 1042,
    name: "Weekly note",
    length: "standard",
    audience: "manager",
    technical_depth: "medium",
    formality: "neutral",
    instructions: null,
    is_default: false,
    is_system: false,
    created_at: "2026-08-01T09:00:00Z",
    updated_at: "2026-08-01T09:00:00Z",
    ...over,
  };
}

// owner_user_id null is what makes a persona a preset, so this is not just makePersona
// with a flag flipped: both fields have to agree or a test proves nothing.
export function makePreset(over: Partial<PersonaResponse> = {}): PersonaResponse {
  return makePersona({
    id: 1,
    owner_user_id: null,
    name: "Concise",
    length: "brief",
    is_system: true,
    is_default: false,
    ...over,
  });
}

export function makeCredential(over: Partial<CredentialResponse> = {}): CredentialResponse {
  return {
    id: 5,
    scope: "user",
    owner_user_id: 1042,
    dept_id: null,
    provider: "anthropic",
    model: null,
    last_four: "9f2c",
    bypass_token_cap: false,
    created_by_user_id: 1042,
    created_at: "2026-08-20T09:00:00Z",
    updated_at: "2026-08-20T09:00:00Z",
    ...over,
  };
}

export function makeEffective(over: Partial<EffectiveCredentialResponse> = {}): EffectiveCredentialResponse {
  return {
    source: "user",
    provider: "anthropic",
    model: "claude-sonnet-4-5",
    bypass_token_cap: false,
    ...over,
  };
}

export function makeAccount(over: Partial<GitHubAccountResponse> = {}): GitHubAccountResponse {
  return {
    user_id: 1042,
    github_user_id: 55123,
    github_login: "ada",
    scopes: "repo,read:user",
    connected_at: "2026-08-01T00:00:00Z",
    ...over,
  };
}

export function makeBudget(over: Partial<BudgetResponse> = {}): BudgetResponse {
  return {
    id: 11,
    scope: "user",
    owner_user_id: 1042,
    dept_id: null,
    daily_token_cap: 500000,
    created_by_user_id: 1042,
    created_at: "2026-08-20T09:00:00Z",
    updated_at: "2026-08-20T09:00:00Z",
    ...over,
  };
}

export function makeEffectiveBudget(over: Partial<EffectiveBudgetResponse> = {}): EffectiveBudgetResponse {
  return {
    daily_token_cap: 200000,
    source: "platform_default",
    inherited_cap: 200000,
    inherited_source: "platform_default",
    tokens_used_today: 12500,
    may_raise: true,
    show_figures: true,
    dept_admins_see_platform_figures: false,
    ...over,
  };
}

export function makeMember(over: Partial<MemberResponse> = {}): MemberResponse {
  return {
    user_id: 1043,
    email: "tunde@example.com",
    first_name: "Tunde",
    last_name: "Balogun",
    role: "member",
    team_id: null,
    ...over,
  };
}
