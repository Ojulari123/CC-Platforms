import type { UserRef } from "~/types/api";

// Pulse sends the resolved person alongside the raw id, and the person is null
// whenever identity couldn't be reached. Never render the id on its own as if it
// were a name, and never render "null".
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

const STATUS_CLASSES: Record<string, string> = {
  draft: "bg-gray-100 text-gray-700",
  submitted: "bg-amber-100 text-amber-800",
  changes_requested: "bg-orange-100 text-orange-800",
  approved: "bg-green-100 text-green-800",
  rejected: "bg-red-100 text-red-700",
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

export function statusClass(status: string): string {
  return STATUS_CLASSES[status] ?? "bg-gray-100 text-gray-700";
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

// A date-only value (week_start) has no timezone: `new Date("2026-08-03")` is UTC
// midnight, which renders as Aug 2 anywhere west of UTC. Build it in local time so the
// day shown is always the day stored. Timestamps still parse normally.
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

// The Monday of the given date's week — the same canonical week key the API uses.
export function mondayOf(d: Date): string {
  const copy = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const weekday = (copy.getUTCDay() + 6) % 7;
  copy.setUTCDate(copy.getUTCDate() - weekday);
  return copy.toISOString().slice(0, 10);
}

// Same date-only rule as formatDate, in reverse: toISOString() would answer in UTC, so
// after 20:00 west of UTC the ?since= window started a day too late. Read off the local
// calendar day instead.
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

// FastAPI puts the human-readable reason in `detail`; surface that rather than
// "Request failed with status 409".
export function apiMessage(err: unknown, fallback: string): string {
  const detail = (err as { data?: { detail?: unknown } })?.data?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  return fallback;
}
