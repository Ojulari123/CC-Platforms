import { describe, expect, it } from "vitest";
import { passwordLengthError } from "@crescent/ui/composables/usePasswordRules";
import { changePasswordMessage, confirmPasswordError, currentPasswordError, newPasswordError, sessionState } from "~/utils/account-form";

const DAY = 24 * 60 * 60 * 1000;
const NOW = Date.UTC(2026, 7, 13, 12, 0, 0);

describe("changing your password", () => {
  it("asks for the current one, because the stored hash cannot be read back", () => {
    expect(currentPasswordError("")).toBe("Enter the password you use now.");
    expect(currentPasswordError("whatever")).toBeNull();
  });

  it("refuses a new password that does not meet the rules", () => {
    expect(newPasswordError("short", "old-one", false)).toBe("That password does not meet the rules below yet.");
  });

  it("refuses the password they already have", () => {
    expect(newPasswordError("Sameone!1", "Sameone!1", true)).toBe("The new password is the one you already have.");
  });

  /* The ceiling is bcrypt's 72 bytes, but the sentence is the shared one, which counts in
     characters — nobody composing a password counts bytes. Asserted against
     passwordLengthError itself so the two cannot drift back apart. */
  it("refuses a password past the length ceiling in the shared wording", () => {
    const accented = "é".repeat(37); // 74 bytes in UTF-8, 37 characters
    expect(newPasswordError(accented, "old", true)).toBe(passwordLengthError(accented));
    expect(newPasswordError(accented, "old", true)).not.toContain("bytes");

    const ascii = "A".repeat(73);
    expect(newPasswordError(ascii, "old", true)).toBe(passwordLengthError(ascii));
    expect(newPasswordError(ascii, "old", true)).toBe("That password is too long — 73 characters, and the limit is 72.");
  });

  it("passes a password that meets the rules", () => {
    expect(newPasswordError("Meridian!2026", "old-one", true)).toBeNull();
  });

  it("asks for the confirmation and checks it matches", () => {
    expect(confirmPasswordError("", "Meridian!2026")).toBe("Type the new one a second time.");
    expect(confirmPasswordError("Meridian!2025", "Meridian!2026")).toBe("The two passwords do not match.");
    expect(confirmPasswordError("Meridian!2026", "Meridian!2026")).toBeNull();
  });

  it("names the wrong current password rather than blaming the new one", () => {
    expect(changePasswordMessage({ statusCode: 401 })).toBe("That is not your current password.");
  });
});

describe("session state", () => {
  const base = { is_revoked: false, expires_at: new Date(NOW + 7 * DAY).toISOString(), last_used_at: new Date(NOW - 60_000).toISOString() };

  it("reads a rotating session as refreshing", () => {
    expect(sessionState(base, NOW)).toBe("refreshing");
  });

  it("reads three days without a refresh as idle", () => {
    expect(sessionState({ ...base, last_used_at: new Date(NOW - 4 * DAY).toISOString() }, NOW)).toBe("idle");
  });

  it("reads a past expiry as expired", () => {
    expect(sessionState({ ...base, expires_at: new Date(NOW - DAY).toISOString() }, NOW)).toBe("expired");
  });

  it("puts revoked ahead of everything else", () => {
    expect(sessionState({ ...base, is_revoked: true, expires_at: new Date(NOW - DAY).toISOString() }, NOW)).toBe("revoked");
  });
});
