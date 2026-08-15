import { passwordLengthError } from "@crescent/ui/composables/usePasswordRules";
import { apiMessage, httpStatus } from "~/utils/format";

// The account screen's validation, computed rather than stored so a message tracks the
// field as it is typed. The server is still the authority; these exist so nobody meets a
// 400 they could have been told about while typing.

export function currentPasswordError(value: string): string | null {
  return value.length === 0 ? "Enter the password you use now." : null;
}

export function newPasswordError(next: string, current: string, meetsRules: boolean): string | null {
  if (next.length === 0) return "Choose a new password.";
  // The ceiling is worded once, in the shared rules, so this screen and the recovery
  // screens cannot end up describing the same limit two different ways.
  const tooLong = passwordLengthError(next);
  if (tooLong) return tooLong;
  if (next === current) return "The new password is the one you already have.";
  return meetsRules ? null : "That password does not meet the rules below yet.";
}

export function confirmPasswordError(confirm: string, next: string): string | null {
  if (confirm.length === 0) return "Type the new one a second time.";
  return confirm === next ? null : "The two passwords do not match.";
}

export function changePasswordMessage(err: unknown): string {
  const status = httpStatus(err);
  if (status === 401) return "That is not your current password.";
  if (status === 429) return "Too many attempts. Wait a minute and try again.";
  return apiMessage(err, "Could not change your password.");
}

export function profileMessage(err: unknown): string {
  const status = httpStatus(err);
  if (status === 422) return "A first and last name are both required.";
  return apiMessage(err, "Could not save your profile.");
}

/** Idle for three days or more. The same threshold the sessions console uses. */
export const IDLE_MS = 3 * 24 * 60 * 60 * 1000;

export type SessionState = "revoked" | "expired" | "idle" | "refreshing";

export function sessionState(session: { is_revoked: boolean; expires_at: string; last_used_at: string }, now = Date.now()): SessionState {
  if (session.is_revoked) return "revoked";
  if (new Date(session.expires_at).getTime() <= now) return "expired";
  if (now - new Date(session.last_used_at).getTime() >= IDLE_MS) return "idle";
  return "refreshing";
}
