import { describe, expect, it } from "vitest";
import { computed, ref } from "vue";
import { passwordLengthError, usePasswordRules } from "../composables/usePasswordRules";

// The composable reaches for Nuxt's auto-imported `computed`, as the pages do.
(globalThis as Record<string, unknown>).computed = computed;

describe("the password checklist", () => {
  it("lists only things there are to do — no byte ceiling among them", () => {
    const { rules } = usePasswordRules(ref(""));
    const labels = rules.value.map((rule) => rule.label);

    expect(labels).toEqual([
      "At least 8 characters",
      "One uppercase letter",
      "One lowercase letter",
      "One number",
      "One special character, like ! or ?",
    ]);
    expect(labels.join(" ")).not.toMatch(/byte/i);
  });

  it("claims nothing is met on an empty field", () => {
    const { rules, valid } = usePasswordRules(ref(""));
    expect(rules.value.filter((rule) => rule.met)).toHaveLength(0);
    expect(valid.value).toBe(false);
  });

  it("mirrors identity's five checks", () => {
    const password = ref("short");
    const { rules, valid } = usePasswordRules(password);
    expect(rules.value.filter((rule) => rule.met).map((rule) => rule.label)).toEqual(["One lowercase letter"]);

    password.value = "Meridian!2026";
    expect(rules.value.every((rule) => rule.met)).toBe(true);
    expect(valid.value).toBe(true);
  });
});

describe("the length ceiling", () => {
  it("says nothing until a password actually crosses it", () => {
    expect(passwordLengthError("")).toBeNull();
    expect(passwordLengthError("Meridian!2026")).toBeNull();
    expect(passwordLengthError("A1!".repeat(24))).toBeNull(); // exactly 72
  });

  it("talks in characters when characters are what the person typed", () => {
    expect(passwordLengthError(`${"A1!".repeat(24)}x`)).toBe(
      "That password is too long — 73 characters, and the limit is 72.",
    );
  });

  it("explains the accent and emoji caveat only where it is what pushed it over", () => {
    // 37 accented letters: 37 characters, 74 bytes.
    expect(passwordLengthError("é".repeat(37))).toBe(
      "That password is too long. The limit is 72 characters, but accented letters and emoji count as two to four each, and this one comes to 74.",
    );
  });

  it("blocks a too-long password even with every rule ticked", () => {
    const password = ref(`Meridian!2026${"a".repeat(70)}`);
    const { rules, valid, lengthError } = usePasswordRules(password);

    expect(rules.value.every((rule) => rule.met)).toBe(true);
    expect(lengthError.value).toMatch(/too long/);
    expect(valid.value).toBe(false);
  });
});
