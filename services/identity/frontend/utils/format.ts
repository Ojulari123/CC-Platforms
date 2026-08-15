export function fullName(first: string, last: string, fallback: string): string {
  return `${first ?? ""} ${last ?? ""}`.trim() || fallback;
}

export function initials(first: string, last: string, email: string): string {
  const a = (first ?? "").trim()[0] ?? "";
  const b = (last ?? "").trim()[0] ?? "";
  return (a + b).toUpperCase() || (email ?? "?").trim()[0]?.toUpperCase() || "?";
}

const ROLE_CLASSES: Record<string, string> = {
  admin: "bg-indigo-50 text-indigo-700 ring-indigo-200",
  manager: "bg-sky-50 text-sky-700 ring-sky-200",
  engineer: "bg-slate-50 text-slate-600 ring-slate-200",
};

export function roleClass(role: string): string {
  return ROLE_CLASSES[role] ?? "bg-slate-50 text-slate-600 ring-slate-200";
}

const ROLE_BLURBS: Record<string, string> = {
  admin: "Can administer this department: place people, invite, and file repositories.",
  manager: "Department-wide read of reports in Pulse. Carries no approval power on its own.",
  engineer: "Writes their own weekly reports. No administrative reach.",
};

export function roleBlurb(role: string): string {
  return ROLE_BLURBS[role] ?? "";
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

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

// How long until an invite lapses, which is the only thing anyone reads that date for.
export function expiresIn(value: string): string {
  const ms = new Date(value).getTime() - Date.now();
  if (Number.isNaN(ms)) return "—";
  if (ms <= 0) return "expired";
  const days = Math.floor(ms / 86_400_000);
  if (days >= 1) return `${days} day${days === 1 ? "" : "s"} left`;
  const hours = Math.max(1, Math.floor(ms / 3_600_000));
  return `${hours} hour${hours === 1 ? "" : "s"} left`;
}

export function httpStatus(err: unknown): number | undefined {
  return (err as { statusCode?: number; status?: number })?.statusCode
    ?? (err as { status?: number })?.status;
}

export function apiMessage(err: unknown, fallback: string): string {
  const detail = (err as { data?: { detail?: unknown } })?.data?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  return fallback;
}
