// The upload contract, in one place. The server enforces all of this again
// (services/forge/app/services/datasets.py); the browser copy exists so a bad file is
// named and refused before it costs a round trip, never as the only check.

export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;

// services/forge/app/config.py DATASET_PREVIEW_ROWS, mirrored so the header line and
// the ?rows= query can never drift apart.
export const PREVIEW_ROW_CAP = 10;

export interface Rejection {
  key: string;
  chip: string;
  message: string;
}

// The five refusals the upload path really returns, each naming its cause.
export const REJECTIONS: Rejection[] = [
  {
    key: "size",
    chip: "Over 5 MB",
    message:
      "File is larger than the 5 MB limit. The upload is refused while streaming, so an oversized file is never fully buffered.",
  },
  {
    key: "utf8",
    chip: "Not valid UTF-8",
    message: "File could not be decoded as UTF-8. Re-save it as UTF-8 CSV and upload again.",
  },
  {
    key: "empty",
    chip: "Empty file",
    message: "File contains no bytes. Nothing to read, nothing stored.",
  },
  {
    key: "header",
    chip: "No header row",
    message:
      "First row has to be the column names. Without it there is nothing to label the columns with.",
  },
  {
    key: "malformed",
    chip: "Malformed CSV",
    message:
      "Rows could not be parsed as CSV — usually an unclosed quote or an inconsistent column count.",
  },
];

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

export interface FileCheck {
  ok: boolean;
  /** Matches a REJECTIONS key when the refusal has a standing explanation. */
  key?: string;
  message?: string;
}

/* One gate for both the drop and the picker, so a file cannot get in by the other door
   without being checked. Only the three things a browser can know for free — the
   extension, the byte count, and whether there are any bytes at all. Encoding and CSV
   structure are the server's call. */
export function checkFile(file: File): FileCheck {
  if (!/\.csv$/i.test(file.name)) {
    return {
      ok: false,
      message: `${file.name} is not a .csv file. Forge reads CSV only — one header row, then data.`,
    };
  }
  if (file.size === 0) {
    return {
      ok: false,
      key: "empty",
      message: `${file.name} is 0 B. Nothing to read, so nothing is stored.`,
    };
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return {
      ok: false,
      key: "size",
      message: `${file.name} is ${formatBytes(file.size)}, over the 5.00 MB cap. The upload is refused while streaming rather than buffered and then thrown away.`,
    };
  }
  return { ok: true };
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}/;

function numeric(value: string): boolean {
  return value.trim() !== "" && Number.isFinite(Number(value));
}

/* Which column holds words rather than measurements. The preview arrives as strings
   either way, so the marker is derived from the rows on screen — the first column that
   is neither a number nor a date. Dates are excluded on purpose: they are the axis of a
   time series, not a category. -1 when every column is numeric or dated. */
export function detectTextColumn(columns: string[], rows: string[][]): number {
  for (let c = 0; c < columns.length; c += 1) {
    let seen = false;
    let categorical = true;
    for (const row of rows) {
      const cell = row[c] ?? "";
      if (cell.trim() === "") continue;
      seen = true;
      if (numeric(cell) || ISO_DATE.test(cell.trim())) {
        categorical = false;
        break;
      }
    }
    if (seen && categorical) return c;
  }
  return -1;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// `10 Aug 11:20`. Hand-built rather than Intl: the row is mono and tabular, and the
// locale-formatted string changes width between browsers.
export function formatStamp(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  const hh = String(at.getHours()).padStart(2, "0");
  const mm = String(at.getMinutes()).padStart(2, "0");
  return `${at.getDate()} ${MONTHS[at.getMonth()]} ${hh}:${mm}`;
}

// Reads the status off whatever $fetch threw. Nuxt puts it on `statusCode`, the raw
// FetchError on `status`.
export function statusOf(err: unknown): number | undefined {
  return (
    (err as { statusCode?: number })?.statusCode ?? (err as { status?: number })?.status
  );
}
