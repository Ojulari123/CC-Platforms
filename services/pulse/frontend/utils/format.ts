import type { UserRef } from "~/types/api";

// `person` is null whenever identity couldn't be reached, so never render the id on
// its own as if it were a name.
export function personName(person: UserRef | null | undefined, userId: number): string {
  if (!person) return `Unknown user (#${userId})`;
  const full = `${person.first_name ?? ""} ${person.last_name ?? ""}`.trim();
  return full || `Unknown user (#${userId})`;
}

const STATUS_LABELS: Record<string, string> = {
  draft: "Draft",
  submitted: "Awaiting review",
  changes_requested: "Changes requested",
  approved: "Approved",
  rejected: "Rejected",
};

// A status chip is one of the few places colour carries meaning, so it gets a tinted
// surface rather than a fill. Inside a repeated column use <StatusDot quiet> instead:
// --ok and --warn are brighter than --ink-muted, so a coloured word in every row
// outranks the data it annotates.
const STATUS_CLASSES: Record<string, string> = {
  draft: "bg-surface text-ink-muted",
  submitted: "bg-info-surface text-ink",
  changes_requested: "bg-warn-surface text-ink",
  approved: "bg-ok-surface text-ink",
  rejected: "bg-bad-surface text-ink",
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

export function statusClass(status: string): string {
  return STATUS_CLASSES[status] ?? "bg-surface text-ink-muted";
}

const ACTION_LABELS: Record<string, string> = {
  submitted: "submitted for review",
  approved: "approved",
  rejected: "rejected",
  changes_requested: "requested changes",
};

export function actionLabel(action: string): string {
  return ACTION_LABELS[action] ?? action.replace(/_/g, " ");
}

const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;

// A date-only value has no timezone: `new Date("2026-08-03")` is UTC midnight, which
// renders as Aug 2 anywhere west of UTC. Build it in local time instead.
export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const parts = DATE_ONLY.exec(value);
  const d = parts
    ? new Date(Number(parts[1]), Number(parts[2]) - 1, Number(parts[3]))
    : new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// Short machine stamp for a ledger column: "11 Aug 09:44".
export function formatStamp(value: string | null | undefined): string {
  if (!value) return "never";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "never";
  return d.toLocaleString(undefined, {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function relativeTime(value: string | null | undefined): string {
  if (!value) return "—";
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return "—";
  const mins = Math.round((Date.now() - then) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export function mondayOf(d: Date): string {
  const copy = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const weekday = (copy.getUTCDay() + 6) % 7;
  copy.setUTCDate(copy.getUTCDate() - weekday);
  return copy.toISOString().slice(0, 10);
}

// The last `count` Mondays, newest first. The week picker offers these; the API snaps
// whatever it is given to the Monday anyway (_monday() in services/reports.py).
export function recentWeeks(count: number, from: Date = new Date()): string[] {
  const first = mondayOf(from);
  const weeks: string[] = [];
  for (let i = 0; i < count; i += 1) {
    const d = new Date(`${first}T00:00:00Z`);
    d.setUTCDate(d.getUTCDate() - i * 7);
    weeks.push(d.toISOString().slice(0, 10));
  }
  return weeks;
}

// Same date-only rule in reverse: toISOString() answers in UTC, so after 20:00 west of
// UTC the ?since= window started a day too late.
function isoLocalDate(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return isoLocalDate(d);
}

export function httpStatus(err: unknown): number | undefined {
  return (err as { statusCode?: number; status?: number })?.statusCode
    ?? (err as { status?: number })?.status;
}

/* Which failures the API is allowed to describe in its own words.

   A 4xx is the API answering the caller about the request they sent — "week_start must be
   a Monday", "that repository already has a report for this week", "you do not lead this
   repository". That text names the thing the person has to change, so it is the most
   useful sentence the screen can carry. A 401 is the exception: the token is stale, and
   the auth layer deals with that, not a panel.

   A 5xx is the server having failed. `detail` there is whatever the exception happened to
   say — Pulse's 503 spells out GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET, and an unhandled
   500 is the exception message verbatim. Neither is copy, and one of them is a leak. */
function speaksToUser(status: number | undefined): boolean {
  return status !== undefined && status >= 400 && status < 500 && status !== 401;
}

// So a 5xx is logged once, not once per re-render: apiMessage is called from templates.
const noted = new WeakSet<object>();

export function apiMessage(err: unknown, fallback: string): string {
  const detail = (err as { data?: { detail?: unknown } })?.data?.detail;
  const text = typeof detail === "string" && detail.trim() ? detail.trim() : "";
  if (!text) return fallback;
  if (speaksToUser(httpStatus(err))) return text;
  // Not shown, not lost: whoever is debugging gets it from the console.
  if (typeof err === "object" && err !== null && !noted.has(err)) {
    noted.add(err);
    console.error(`[pulse] API ${httpStatus(err) ?? "request failed"}: ${text}`);
  }
  return fallback;
}
