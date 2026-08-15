// Mirrors identity's validate_password so people see the rules before they submit
// rather than guessing at a 400. The server is still the authority.
// bcrypt reads at most 72 bytes: an accented letter or emoji costs 2–4 of them.
export const MAX_PASSWORD_BYTES = 72;

const encoder = new TextEncoder();

export function passwordBytes(value: string): number {
  return encoder.encode(value).length;
}

// The five things a password has to have, in identity's own order. The 72-byte ceiling is
// deliberately not among them: a checklist is a list of things to reach, and a maximum
// starts out satisfied — an empty field would sit there ticking off a rule nobody has
// done anything about yet. It is an error instead, raised only once it is crossed.
const RULES = [
  { label: "At least 8 characters", test: (v: string) => v.length >= 8 },
  { label: "One uppercase letter", test: (v: string) => /[A-Z]/.test(v) },
  { label: "One lowercase letter", test: (v: string) => /[a-z]/.test(v) },
  { label: "One number", test: (v: string) => /[0-9]/.test(v) },
  { label: "One special character, like ! or ?", test: (v: string) => /[^A-Za-z0-9]/.test(v) },
];

/* The upper bound, in the only place it is worth mentioning. Identity counts bytes
   because bcrypt does, but nobody composing a password counts bytes — so an all-ASCII
   password, where the two numbers agree, is told about characters and nothing else. The
   accent/emoji caveat only appears when it is what pushed the password over. */
export function passwordLengthError(value: string): string | null {
  const bytes = passwordBytes(value);
  if (bytes <= MAX_PASSWORD_BYTES) return null;
  if (bytes === value.length) {
    return `That password is too long — ${value.length} characters, and the limit is ${MAX_PASSWORD_BYTES}.`;
  }
  return `That password is too long. The limit is ${MAX_PASSWORD_BYTES} characters, but accented letters and emoji count as two to four each, and this one comes to ${bytes}.`;
}

// Takes the ref structurally: this layer has no node_modules of its own, so it
// can't import Vue's Ref type (see the note in nuxt.config.ts).
export function usePasswordRules(password: { value: string }) {
  const rules = computed(() =>
    RULES.map((rule) => ({ label: rule.label, met: rule.test(password.value) })),
  );
  const lengthError = computed(() => passwordLengthError(password.value));
  const valid = computed(() => !lengthError.value && rules.value.every((rule) => rule.met));
  return { rules, valid, lengthError };
}
