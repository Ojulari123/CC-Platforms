// Mirrors identity's validate_password so people see the rules before they submit
// rather than guessing at a 400. The server is still the authority.
// bcrypt reads at most 72 bytes: an accented letter or emoji costs 2–4 of them.
export const MAX_PASSWORD_BYTES = 72;

const encoder = new TextEncoder();

export function passwordBytes(value: string): number {
  return encoder.encode(value).length;
}

const RULES = [
  { label: "At least 8 characters", test: (v: string) => v.length >= 8 },
  {
    label: "No more than 72 bytes (accents and emoji count extra)",
    test: (v: string) => passwordBytes(v) <= MAX_PASSWORD_BYTES,
  },
  { label: "One uppercase letter", test: (v: string) => /[A-Z]/.test(v) },
  { label: "One lowercase letter", test: (v: string) => /[a-z]/.test(v) },
  { label: "One number", test: (v: string) => /[0-9]/.test(v) },
  { label: "One special character", test: (v: string) => /[^A-Za-z0-9]/.test(v) },
];

// Takes the ref structurally: this layer has no node_modules of its own, so it
// can't import Vue's Ref type (see the note in nuxt.config.ts).
export function usePasswordRules(password: { value: string }) {
  const rules = computed(() =>
    RULES.map((rule) => ({ label: rule.label, met: rule.test(password.value) })),
  );
  const valid = computed(() => rules.value.every((rule) => rule.met));
  return { rules, valid };
}
