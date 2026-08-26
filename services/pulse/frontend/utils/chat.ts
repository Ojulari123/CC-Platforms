import type { Tone } from "@crescent/ui/types/ui";
import type { Citation, IndexStatus, IndexedRepo } from "~/types/api";

// Indexing is a background job, so the list polls while anything is still moving. Long
// enough not to hammer the API, short enough that a small repository looks instant.
export const REPO_POLL_MS = 2000;

/* GitHub's own rules: an owner is letters, digits and single hyphens; a repository name
   also allows dots and underscores. Checked here because "owner/name" is the whole of
   what POST /chat/repos accepts, and a typo is worth catching before a 422 does. */
const OWNER = "[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})";
const NAME = "[A-Za-z0-9_.-]{1,100}";
const FULL_NAME = new RegExp(`^${OWNER}/${NAME}$`);

/* People paste the address bar, not the two words. A github.com URL, a trailing .git and
   a trailing slash all mean the repository they are looking at, so they are accepted and
   reduced rather than rejected. Anything else is left alone for isFullName to refuse. */
export function normalizeRepoInput(raw: string): string {
  let value = raw.trim();
  value = value.replace(/^(?:https?:\/\/)?(?:www\.)?github\.com\//i, "");
  value = value.replace(/^git@github\.com:/i, "");
  value = value.replace(/\.git$/i, "").replace(/\/+$/, "");
  // A deep link (owner/name/tree/main/src) still names a repository in its first two parts.
  const parts = value.split("/").filter(Boolean);
  return parts.length > 2 ? `${parts[0]}/${parts[1]}` : parts.join("/");
}

export function isFullName(value: string): boolean {
  return FULL_NAME.test(value) && !value.endsWith(".");
}

/* `paused` is warn, not bad. A failure needs somebody to look at it; a pause is waiting
   for the allowance to reset or for the provider to stop asking for a wait, and the work
   already done is kept. Colouring the two the same would tell people to investigate
   something that only needs asking again. */
const INDEX_TONES: Record<IndexStatus, Tone> = {
  pending: "muted",
  running: "info",
  ready: "ok",
  error: "bad",
  rate_limited: "warn",
  paused: "warn",
};

const INDEX_LABELS: Record<IndexStatus, string> = {
  pending: "Queued",
  running: "Indexing",
  ready: "Ready",
  error: "Failed",
  rate_limited: "Rate limited",
  paused: "Paused",
};

export function indexTone(status: string): Tone {
  return INDEX_TONES[status as IndexStatus] ?? "muted";
}

export function indexLabel(status: string): string {
  return INDEX_LABELS[status as IndexStatus] ?? status.replace(/_/g, " ");
}

// Still moving, so the list has to ask again.
export function isSettling(repo: Pick<IndexedRepo, "status">): boolean {
  return repo.status === "pending" || repo.status === "running";
}

export function isRetryable(repo: Pick<IndexedRepo, "status">): boolean {
  return repo.status === "error" || repo.status === "rate_limited" || repo.status === "paused";
}

// Stopped with its work intact, so the same POST carries on from where it left off rather
// than starting again. Worth saying differently from a failure, and worth offering first.
export function isResumable(repo: Pick<IndexedRepo, "status">): boolean {
  return repo.status === "paused";
}

// The citation as it is written on screen, and as somebody would paste it into an editor.
export function citationRef(citation: Pick<Citation, "full_name" | "path" | "start_line" | "end_line">): string {
  return `${citation.full_name} ${citation.path}:${citation.start_line}-${citation.end_line}`;
}
