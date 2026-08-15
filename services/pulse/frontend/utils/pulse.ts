import type { SelectOption, Tone } from "@crescent/ui/types/ui";
import { personName } from "~/utils/format";
import type {
  ApproverCandidate,
  ReportResponse,
  ReportStatus,
  RepositoryResponse,
  SyncRunResponse,
  UserMeResponse,
} from "~/types/api";

export const REPORT_STATUSES: ReportStatus[] = [
  "draft",
  "submitted",
  "changes_requested",
  "approved",
  "rejected",
];

const STATUS_TONES: Record<string, Tone> = {
  draft: "muted",
  submitted: "info",
  changes_requested: "warn",
  approved: "ok",
  rejected: "bad",
};

export function statusTone(status: string): Tone {
  return STATUS_TONES[status] ?? "muted";
}

// The three fields a report is, in the order they are written and read.
export const REPORT_FIELDS = [
  { key: "summary_manager", label: "For the lead", api: "summary_manager" },
  { key: "summary_exec", label: "Executive summary", api: "summary_exec" },
  { key: "next_week_goals", label: "Next week", api: "next_week_goals" },
] as const;

export type ReportField = (typeof REPORT_FIELDS)[number]["key"];

/* ── sync runs ─────────────────────────────────────────────────────────────── */

export interface SyncCounts {
  commits: number;
  branches: number;
  pull_requests: number;
  issues: number;
}

// The worker prefixes `detail` with the repository's full name, which the row already
// shows. A head that carries an `=` or a space is part of the reason, not a name.
function stripName(detail: string): string {
  const cut = detail.indexOf(": ");
  if (cut < 0) return detail;
  const head = detail.slice(0, cut);
  return head.includes("=") || head.includes(" ") ? detail : detail.slice(cut + 2);
}

// `detail` is one string: "full_name: commits=3, branches=0, pull_requests=1, issues=0".
// A failure, a rate limit or a skip writes a sentence there instead, and that does not
// parse — the caller renders em dashes and offers the raw string. Reviews are ingested
// with their pull request and are not counted separately in this string.
export function parseSyncCounts(detail: string | null): SyncCounts | null {
  if (!detail) return null;
  const out: Record<string, number> = {};
  for (const part of stripName(detail).split(",")) {
    const [key, value] = part.split("=").map((s) => s.trim());
    if (!key || value === undefined || !/^\d+$/.test(value)) return null;
    out[key] = Number(value);
  }
  if (!("commits" in out)) return null;
  return {
    commits: out.commits ?? 0,
    branches: out.branches ?? 0,
    pull_requests: out.pull_requests ?? 0,
    issues: out.issues ?? 0,
  };
}

export function runDuration(run: Pick<SyncRunResponse, "started_at" | "finished_at">): string {
  if (!run.finished_at) return "—";
  const ms = Date.parse(run.finished_at) - Date.parse(run.started_at);
  if (Number.isNaN(ms) || ms < 0) return "—";
  if (ms < 1000) return `${ms}ms`;
  const s = Math.round(ms / 1000);
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}

// sync_runs records no trigger column. 02:00 UTC is the scheduled beat, so anything
// else was somebody pressing the button — an inference, and the column says so.
export function inferTrigger(run: Pick<SyncRunResponse, "started_at">): "scheduled" | "manual" {
  const hour = new Date(run.started_at).getUTCHours();
  return hour === 2 ? "scheduled" : "manual";
}

const RUN_TONES: Record<string, Tone> = {
  success: "ok",
  error: "bad",
  rate_limited: "warn",
  skipped: "muted",
  running: "info",
};

const RUN_LABELS: Record<string, string> = {
  success: "Success",
  error: "Failed",
  rate_limited: "Rate limited",
  skipped: "Skipped",
  running: "Running",
};

export function runTone(status: string): Tone {
  return RUN_TONES[status] ?? "muted";
}

export function runLabel(status: string): string {
  return RUN_LABELS[status] ?? status.replace(/_/g, " ");
}

export function failedRuns(runs: SyncRunResponse[]): SyncRunResponse[] {
  return runs.filter((run) => run.status === "error" || run.status === "rate_limited");
}

// The next 02:00 UTC, and how far off it is.
export function nextScheduledRun(now: Date = new Date()): { iso: string; away: string } {
  const next = Date.UTC(
    now.getUTCFullYear(),
    now.getUTCMonth(),
    now.getUTCDate() + (now.getUTCHours() >= 2 ? 1 : 0),
    2,
    0,
    0,
  );
  const mins = Math.max(0, Math.round((next - now.getTime()) / 60000));
  return {
    iso: new Date(next).toISOString().replace(/\.\d{3}/, ""),
    away: `${Math.floor(mins / 60)}h ${String(mins % 60).padStart(2, "0")}m`,
  };
}

/* ── reports ───────────────────────────────────────────────────────────────── */

// uq_report_author_repo_week is (author_user_id, repo_id, week_start): one report per
// person per repo per week. Somebody else's report on the same week is not in the way.
export function duplicateReport(
  reports: ReportResponse[],
  repoId: number | null,
  weekStart: string,
  authorId: number | null,
): ReportResponse | null {
  if (repoId === null || authorId === null) return null;
  return (
    reports.find(
      (r) => r.repo_id === repoId && r.week_start === weekStart && r.author_user_id === authorId,
    ) ?? null
  );
}

export function firstFreeWeek(
  weeks: string[],
  reports: ReportResponse[],
  repoId: number | null,
  authorId: number | null,
): string | null {
  if (repoId === null || authorId === null) return null;
  return (
    weeks.find(
      (week) =>
        !reports.some(
          (r) => r.repo_id === repoId && r.week_start === week && r.author_user_id === authorId,
        ),
    ) ?? null
  );
}

export interface RepoWarnings {
  unfiled: boolean;
  untracked: boolean;
  unnamed: boolean;
}

// The API gates report creation on your activity, not on filing, so none of these
// blocks the write. They change who — if anyone — can decide the result.
export function repoWarnings(repo: RepositoryResponse | null | undefined): RepoWarnings {
  if (!repo) return { unfiled: false, untracked: false, unnamed: false };
  return {
    unfiled: repo.dept_id === null,
    untracked: !repo.is_tracked,
    unnamed: repo.lead_user_id === null && repo.deputy_user_id === null,
  };
}

export interface DecideVerdict {
  allowed: boolean;
  reason: string | null;
}

// Mirrors _can_approve in app/services/reports.py. Authorship is checked before any
// admin power, so a platform admin is refused on their own report like anyone else.
// Getting this wrong only shows or hides a button; the API is what decides.
export function canDecide(
  report: ReportResponse | null,
  repo: RepositoryResponse | null,
  user: UserMeResponse | null,
): DecideVerdict {
  if (!report || !user) return { allowed: false, reason: null };
  if (report.author_user_id === user.id) {
    return { allowed: false, reason: "You wrote this report, so you cannot decide it. The API answers 403 whatever your role is." };
  }
  if (report.status !== "submitted") {
    return { allowed: false, reason: "A decision only exists while one is being asked for." };
  }
  if (user.is_platform_admin) return { allowed: true, reason: null };
  if (repo && (repo.lead_user_id === user.id || repo.deputy_user_id === user.id)) {
    return { allowed: true, reason: null };
  }
  const deptAdmin =
    report.dept_id !== null &&
    (user.memberships ?? []).some((m) => m.dept_id === report.dept_id && m.role === "admin");
  return deptAdmin
    ? { allowed: true, reason: null }
    : { allowed: false, reason: "You are not this repository's lead or deputy, and not an admin of its department." };
}

export function statusCounts(rows: ReportResponse[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const status of REPORT_STATUSES) out[status] = 0;
  for (const row of rows) out[row.status] = (out[row.status] ?? 0) + 1;
  return out;
}

export function sortByWeek(rows: ReportResponse[], dir: "asc" | "desc"): ReportResponse[] {
  return [...rows].sort((a, b) => {
    const week = dir === "desc"
      ? b.week_start.localeCompare(a.week_start)
      : a.week_start.localeCompare(b.week_start);
    return week !== 0 ? week : b.id - a.id;
  });
}

export function pageCount(total: number, perPage: number): number {
  return Math.max(1, Math.ceil(total / perPage));
}

/* ── repositories ──────────────────────────────────────────────────────────── */

// /approver-candidates returns whoever has commits, pull requests or issues in the
// repository, plus whoever holds a post today, and marks which is which. A post-holder
// with no activity is kept and labelled rather than quietly dropped.
export function candidateOptions(
  candidates: ApproverCandidate[],
  noneLabel = "Nobody",
): SelectOption[] {
  const options: SelectOption[] = [{ value: "none", label: noneLabel }];
  for (const candidate of candidates) {
    const name = personName(candidate.person, candidate.user_id);
    options.push({
      value: String(candidate.user_id),
      label: candidate.has_activity ? name : `${name} · no activity here`,
    });
  }
  return options;
}

export function approverLabel(repo: RepositoryResponse): string {
  const names: string[] = [];
  if (repo.lead_user_id !== null) names.push(`${personName(repo.lead, repo.lead_user_id)} (lead)`);
  if (repo.deputy_user_id !== null) {
    names.push(`${personName(repo.deputy, repo.deputy_user_id)} (deputy)`);
  }
  return names.length ? names.join(", ") : "Nobody named";
}

// Mirrors _require_can_admin_repo. Shows or hides controls; the API decides.
export function canAdminRepo(
  repo: RepositoryResponse,
  user: UserMeResponse | null,
): boolean {
  if (!user) return false;
  if (user.is_platform_admin) return true;
  return (
    repo.dept_id !== null &&
    (user.memberships ?? []).some((m) => m.dept_id === repo.dept_id && m.role === "admin")
  );
}
