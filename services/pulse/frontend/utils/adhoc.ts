import { apiMessage, httpStatus } from "~/utils/format";

/* The client half of the custom report's validation. Every rule here is also enforced by
   services/pulse/app/schemas/reports.py — this exists so a person finds out before they
   wait on a generation, not instead of the server checking. */

// AdhocRequest.MAX_ADHOC_RANGE_DAYS / MAX_ADHOC_SUBJECTS.
export const MAX_RANGE_DAYS = 180;
export const MAX_SUBJECTS = 10;
// The route's own @limiter.limit("10/hour").
export const MAX_ADHOC_PER_HOUR = 10;

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

/** Whole days between two ISO dates, or null if either is not a date. The server
    compares the same two dates, so this is a difference and not a count of days covered. */
export function spanDays(start: string, end: string): number | null {
  if (!DATE_ONLY.test(start) || !DATE_ONLY.test(end)) return null;
  const from = Date.parse(`${start}T00:00:00Z`);
  const to = Date.parse(`${end}T00:00:00Z`);
  if (Number.isNaN(from) || Number.isNaN(to)) return null;
  return Math.round((to - from) / 86_400_000);
}

/** What is wrong with the range, in the words the person needs, or null when it is fine. */
export function rangeProblem(start: string, end: string): string | null {
  if (!start || !end) return "A report needs a start date and an end date.";
  const span = spanDays(start, end);
  if (span === null) return "Both dates have to be real dates.";
  if (span < 0) return "The end date is before the start date.";
  if (span > MAX_RANGE_DAYS) {
    const over = span - MAX_RANGE_DAYS;
    return `That range is ${span} days. A report covers at most ${MAX_RANGE_DAYS} days, so it is ${over} day${over === 1 ? "" : "s"} too long — move one of the dates.`;
  }
  return null;
}

/* A contributor to report on. Exactly one of the two is used: a Pulse user is sent as a
   user_id, an outside collaborator as a bare GitHub login. The row keeps both so
   switching kind does not throw away what was already typed. */
export interface SubjectRow {
  /** Stable across re-orders; never sent. */
  key: number;
  kind: "user" | "github";
  userId: number | null;
  login: string;
}

// GitHub's own rule: alphanumerics and single hyphens, 39 characters, no leading or
// trailing hyphen.
const LOGIN = /^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$/;

export function isGithubLogin(value: string): boolean {
  return LOGIN.test(value.trim());
}

export function subjectReady(row: SubjectRow): boolean {
  return row.kind === "user" ? row.userId !== null : isGithubLogin(row.login);
}

export interface SubjectPayload {
  user_id?: number;
  github_login?: string;
}

export function subjectPayload(row: SubjectRow): SubjectPayload {
  return row.kind === "user" ? { user_id: row.userId! } : { github_login: row.login.trim() };
}

export interface AdhocFailure {
  message: string;
  /** Set when the fix is on GitHub's side, so the screen can offer the connect flow. */
  connectGitHub: boolean;
}

/* The failures POST /reports/adhoc can answer with, told apart.

   The two 429s are different problems with the same status. The daily token budget is
   raised by BudgetExceededError and reaches the client as a FastAPI `detail`; the
   ten-an-hour limit is raised by slowapi, whose handler writes `{"error": "Rate limit
   exceeded: …"}` and no `detail` at all. So a 429 carrying a detail is the budget, and a
   429 without one is the hourly limit. */
export function adhocFailure(err: unknown): AdhocFailure {
  const code = httpStatus(err);
  const detail = (err as { data?: { detail?: unknown } })?.data?.detail;
  const hasDetail = typeof detail === "string" && detail.trim() !== "";

  if (code === 403) {
    return {
      message: apiMessage(
        err,
        "Pulse could not read that repository with your GitHub connection. A private repository is only read with your own token, never a wider one.",
      ),
      connectGitHub: true,
    };
  }
  if (code === 404) {
    return {
      message: "That repository is not available to you. The picker only offers repositories you can see.",
      connectGitHub: false,
    };
  }
  if (code === 422) {
    return {
      message: apiMessage(err, "The API refused this request. Check the repository, the contributors and the dates."),
      connectGitHub: false,
    };
  }
  if (code === 429) {
    return {
      message: hasDetail
        ? apiMessage(err, "You have used your daily AI token allowance.")
        : `That is ${MAX_ADHOC_PER_HOUR} custom reports in an hour, which is the limit. Nothing was generated and nothing was charged, and the next one can be asked for once the hour is up.`,
      connectGitHub: false,
    };
  }
  if (code === 502) {
    return {
      message: "The AI provider did not answer, so no report was written. Nothing was saved and the form below is untouched.",
      connectGitHub: false,
    };
  }
  if (code === 503) {
    return {
      message: "GitHub's own rate limit was reached while reading the repository. Nothing was generated; try again in a few minutes.",
      connectGitHub: false,
    };
  }
  return { message: apiMessage(err, "Could not generate that report."), connectGitHub: false };
}
