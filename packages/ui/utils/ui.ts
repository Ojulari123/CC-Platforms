import type { IconName, NavItem, ProductKey, Tone } from "../types/ui";

/* Shared chrome constants. A meridian is a reference line, so the platform is built
   out of rules: a ruler of ticks under the header, a vertical rule things hang off,
   crosses where rules meet. Colour is reserved for status. */

export const ICON_PATHS: Record<IconName, string[]> = {
  meridian: ["M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z", "M12 1.5v21"],
  arrow: ["M5 12h14M13 5l7 7-7 7"],
  arrowLeft: ["M19 12H5M11 19l-7-7 7-7"],
  check: ["M20 6 9 17l-5-5"],
  pulse: ["M22 12h-4l-3 9L9 3l-3 9H2"],
  layers: ["M12 2 2 7l10 5 10-5-10-5z", "M2 17l10 5 10-5M2 12l10 5 10-5"],
  shield: ["M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"],
  x: ["M18 6 6 18M6 6l12 12"],
  users: ["M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2", "M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z", "M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"],
  key: ["M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3"],
  git: ["M6 3v12", "M18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6z", "M6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6z", "M18 9a9 9 0 0 1-9 9"],
  doc: ["M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z", "M14 2v6h6", "M9 13h6M9 17h4"],
  chevron: ["M9 18l6-6-6-6"],
  chevronDown: ["M6 9l6 6 6-6"],
  search: ["M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16z", "M21 21l-4.35-4.35"],
  alert: ["M12 9v4", "M12 17h.01", "M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"],
  clock: ["M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z", "M12 6v6l4 2"],
  plus: ["M12 5v14M5 12h14"],
  eye: ["M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z", "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z"],
  eyeOff: [
    "M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19",
    "M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94",
    "M14.12 14.12a3 3 0 1 1-4.24-4.24",
    "M1 1l22 22",
  ],
};

// The focus indicator. `--accent` at 70% — what the prototype's dead `.focus-ring`
// utility used — measures 2.69:1 against the page, under the 3:1 WCAG 1.4.11 asks of a
// non-text indicator. `--accent-ink` at full opacity measures 9.61:1.
export const FOCUS = "outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-ink)] focus-visible:ring-offset-2 focus-visible:ring-offset-app";

// 44px minimum box on coarse pointers only; see `.tap` in assets/css/motion.css.
export const TAP = "tap";

/* A navigation that has to read as the primary action. <Btn> renders a <button>, and a
   navigation wearing a button loses middle-click, open-in-new-tab and the link role — so
   these are the Btn `primary` and `secondary` surfaces on a NuxtLink instead. Kept here
   because the recovery screens all need both. */
export const CTA_LINK = "inline-flex w-full items-center justify-center gap-2 rounded-md bg-ink px-4 py-2.5 text-[13.5px] font-medium text-app transition-[transform,filter] duration-100 ease-out hover:brightness-90 active:scale-[0.98]";
export const CTA_LINK_SECONDARY = "inline-flex w-full items-center justify-center gap-2 rounded-md px-4 py-2.5 text-[13.5px] font-medium text-ink ring-1 ring-inset ring-line-strong transition-[transform,background-color,box-shadow] duration-100 ease-out hover:bg-surface-hover hover:ring-ink-faint active:scale-[0.98]";

// The standard mono label: 11px minimum, tracking capped at 0.08em below 12px.
export const MONO_LABEL = "mono text-[11px] uppercase tracking-[0.08em]";

// Content cap. A max-width, never a fixed width — the shell stays responsive.
export const CONTENT = "mx-auto w-full max-w-[1200px] px-5 sm:px-8";

export const ORIGIN = "04.81° N   07.05° E";

export const PRODUCT_LABEL: Record<ProductKey, string> = {
  pulse: "Pulse",
  forge: "Forge",
  identity: "Identity",
};

// Sub-nav per product, as in-app paths. Cross-product links are absolute URLs from
// runtimeConfig — the three apps hold their tokens under separate localStorage keys.
export const PRODUCT_NAV: Record<ProductKey, NavItem[]> = {
  pulse: [
    { label: "Overview", to: "/" },
    { label: "Activity", to: "/activity" },
    { label: "Reports", to: "/reports" },
    { label: "Repositories", to: "/repositories" },
    { label: "Sync", to: "/sync" },
  ],
  forge: [{ label: "Overview", to: "/" }],
  identity: [
    // /users, not /people: the page ships at /users and other screens already link to
    // it. Renaming a live route to match a constant is how links rot.
    { label: "People", to: "/users" },
    { label: "Organisation", to: "/departments" },
    { label: "Access", to: "/access" },
    { label: "Sessions", to: "/sessions" },
  ],
};

// Routes that are not in the sub-nav but belong under one of its entries, so the right
// item stays lit on /reports/new and /reports/42.
export const NAV_ALIAS: Record<string, string> = {
  "/reports/new": "/reports",
  "/review": "/reports",
};

// Which nav entry a path belongs to. Longest matching prefix wins, so /repositories
// does not light up under /.
export function navMatch(path: string, items: NavItem[]): string | null {
  const aliased = NAV_ALIAS[path] ?? path;
  let best: string | null = null;
  for (const item of items) {
    if (item.to === "/" ? aliased === "/" : aliased === item.to || aliased.startsWith(`${item.to}/`)) {
      if (!best || item.to.length > best.length) best = item.to;
    }
  }
  return best;
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase();
}

export const DOT_BG: Record<Tone, string> = {
  ok: "bg-ok",
  warn: "bg-warn",
  bad: "bg-bad",
  info: "bg-info",
  muted: "bg-ink-faint",
};

export const DOT_TEXT: Record<Tone, string> = {
  ok: "text-ok",
  warn: "text-warn",
  bad: "text-bad",
  info: "text-info",
  muted: "text-ink-faint",
};

// What a dialog's focus trap will move through.
export const FOCUSABLE = 'a[href],button:not([disabled]),textarea:not([disabled]),input:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])';

// What someone opening a dialog actually wants to touch first.
export const FIELD = 'input:not([disabled]),textarea:not([disabled]),select:not([disabled]),[role="combobox"]:not([disabled])';
