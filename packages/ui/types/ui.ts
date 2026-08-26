// Types the shared components take. Nuxt auto-imports values, not types, so screens
// import these explicitly: `import type { Tone } from "@crescent/ui/types/ui"`.

export type Tone = "ok" | "warn" | "bad" | "info" | "muted";

export type BtnSize = "sm" | "md" | "lg";
export type BtnVariant = "primary" | "secondary" | "ghost" | "destructive";

export interface SelectOption {
  value: string;
  label: string;
}

export interface TabItem {
  id: string;
  label: string;
  hint?: string;
  // Set when this tab's <TabPanel> is in the document whether or not it is selected.
  hasPanel?: boolean;
}

export interface NavItem {
  label: string;
  to: string;
  // Left unset, TopBar marks the item current when `to` matches the open route.
  active?: boolean;
}

export type ProductKey = "pulse" | "forge" | "identity";

export type IconName =
  | "meridian"
  | "arrow"
  | "arrowLeft"
  | "check"
  | "pulse"
  | "layers"
  | "shield"
  | "x"
  | "users"
  | "key"
  | "git"
  | "doc"
  | "chevron"
  | "chevronDown"
  | "search"
  | "alert"
  | "clock"
  | "plus"
  | "eye"
  | "eyeOff"
  | "sun"
  | "moon"
  | "monitor";

export interface ToastMessage {
  message: string;
  tone: Tone;
}
