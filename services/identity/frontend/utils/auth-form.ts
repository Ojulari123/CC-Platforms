import { isSafeNextPath } from "@crescent/ui/composables/useSSO";
import { apiMessage, httpStatus } from "~/utils/format";

// Validation the sign-in screen computes rather than stores, so a message tracks the
// field as it is typed instead of lagging a keystroke behind.

export const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export function emailError(value: string): string | null {
  if (value.length === 0) return "Enter your work email.";
  return EMAIL_RE.test(value) ? null : "That is not a valid email address.";
}

// Sign-in only checks the length: the server decides, and a stricter client rule here
// would lock out anyone whose password predates the current rules. Creating an account
// uses usePasswordRules(), which mirrors validate_password() exactly.
export function signInPasswordError(value: string): string | null {
  return value.length < 8 ? "Password must be at least 8 characters." : null;
}

export function nameError(value: string, label: string): string | null {
  return value.trim().length === 0 ? `A ${label} is required.` : null;
}

const DESTINATIONS: Record<string, string> = {
  "/": "the front page",
  "/products": "the product picker",
  "/account": "your account",
  "/people": "Identity · People",
  "/users": "Identity · People",
  "/departments": "Identity · Organisation",
  "/access": "Identity · Access",
  "/sessions": "Identity · Sessions",
};

/** Names the place someone was refused, in words, on the sign-in screen. */
export function destinationLabel(next: string): string {
  const path = next.split("?")[0] ?? next;
  if (DESTINATIONS[path]) return DESTINATIONS[path];
  if (path.startsWith("/departments/")) return "Identity · Organisation";
  return "where you were headed";
}

/** Where /login sends someone after it works. A `next` that leaves the app, or points back
    at the sign-in screen, is dropped rather than followed. */
export function afterSignInPath(next: unknown, fallback = "/products"): string {
  if (typeof next !== "string" || !next) return fallback;
  if (!isSafeNextPath(next) || next.startsWith("/login")) return fallback;
  return next;
}

/** Where an unauthenticated request to a guarded route goes, carrying the intent. */
export function signInPath(intended: string): string {
  if (!isSafeNextPath(intended) || intended === "/" || intended.startsWith("/login")) return "/login";
  return `/login?next=${encodeURIComponent(intended)}`;
}

// One message for a wrong address and a wrong password: telling them apart is an
// account-enumeration oracle.
export function signInMessage(err: unknown): string {
  const status = httpStatus(err);
  if (status === 401) return "That email and password do not match an account.";
  if (status === 403) return "That account has been deactivated. A platform admin can turn it back on.";
  if (status === 429) return "Too many attempts from here. Wait a minute and try again.";
  return apiMessage(err, "Could not sign you in.");
}

export function signUpMessage(err: unknown): string {
  const status = httpStatus(err);
  if (status === 409) return "There is already an account with that address. Sign in instead, or ask for a reset link.";
  if (status === 429) return "Too many attempts from here. Wait a minute and try again.";
  if (status === 400 || status === 422) return apiMessage(err, "That password does not meet the rules.");
  return apiMessage(err, "Could not create the account.");
}
