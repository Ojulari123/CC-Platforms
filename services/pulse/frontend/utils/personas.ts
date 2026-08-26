import type { SelectOption } from "@crescent/ui/types/ui";
import type { BudgetSource, EffectiveBudgetResponse, EffectiveCredentialResponse, PersonaResponse } from "~/types/api";

/* The four dials a persona is, and what each setting actually does to the writing.

   The values are the API's own literals (services/pulse/app/schemas/personas.py), so a
   dial is a select over these rather than free text. The plain-language half exists
   because "technical_depth: medium" tells nobody what they are about to get. */

export interface DialSetting {
  value: string;
  label: string;
  /** Reads as a clause in the preview sentence, so it starts lower-case. */
  means: string;
}

export interface Dial {
  key: "length" | "audience" | "technical_depth" | "formality";
  label: string;
  settings: DialSetting[];
}

export const PERSONA_DIALS: Dial[] = [
  {
    key: "length",
    label: "Length",
    settings: [
      { value: "brief", label: "Brief", means: "a few sentences" },
      { value: "standard", label: "Standard", means: "a short page" },
      { value: "detailed", label: "Detailed", means: "a long, thorough write-up" },
    ],
  },
  {
    key: "audience",
    label: "Audience",
    settings: [
      { value: "executive", label: "Executive", means: "written for someone outside the team" },
      { value: "manager", label: "Manager", means: "written for a lead who follows the project" },
      { value: "engineer", label: "Engineer", means: "written for other engineers" },
    ],
  },
  {
    key: "technical_depth",
    label: "Technical depth",
    settings: [
      { value: "low", label: "Low", means: "naming the work rather than the code" },
      { value: "medium", label: "Medium", means: "naming pull requests and files where they matter" },
      { value: "high", label: "High", means: "going down to specific changes" },
    ],
  },
  {
    key: "formality",
    label: "Tone",
    settings: [
      { value: "casual", label: "Casual", means: "in plain, conversational wording" },
      { value: "neutral", label: "Neutral", means: "in an even, businesslike tone" },
      { value: "formal", label: "Formal", means: "in formal report language" },
    ],
  },
];

export function dialOptions(dial: Dial): SelectOption[] {
  return dial.settings.map((s) => ({ value: s.value, label: s.label }));
}

/** What a dial's current value means, or the raw value if the API grows a setting this
    build has never heard of. Never a fabricated description. */
export function dialMeaning(key: Dial["key"], value: string): string {
  const dial = PERSONA_DIALS.find((d) => d.key === key);
  return dial?.settings.find((s) => s.value === value)?.means ?? value;
}

export function dialLabel(key: Dial["key"], value: string): string {
  const dial = PERSONA_DIALS.find((d) => d.key === key);
  return dial?.settings.find((s) => s.value === value)?.label ?? value;
}

export type PersonaDials = Pick<
  PersonaResponse,
  "length" | "audience" | "technical_depth" | "formality"
>;

/** One sentence describing what these four settings produce. */
export function personaPreview(dials: PersonaDials): string {
  const length = dialMeaning("length", dials.length);
  const audience = dialMeaning("audience", dials.audience);
  const depth = dialMeaning("technical_depth", dials.technical_depth);
  const tone = dialMeaning("formality", dials.formality);
  return `${length.charAt(0).toUpperCase()}${length.slice(1)}, ${audience}, ${depth}, ${tone}.`;
}

/** The short line a picker shows under a persona's name. */
export function personaLine(persona: PersonaResponse): string {
  return [
    dialLabel("length", persona.length),
    dialLabel("audience", persona.audience),
    `depth ${dialLabel("technical_depth", persona.technical_depth).toLowerCase()}`,
    dialLabel("formality", persona.formality).toLowerCase(),
  ].join(" · ");
}

// owner_user_id null is the API's definition of a preset; is_system is the same fact
// spelled out. Either would do — this reads off the ownership, which is what the 403 in
// personas._writable is actually checking.
export function isSystemPersona(persona: PersonaResponse): boolean {
  return persona.owner_user_id === null;
}

/* Which key a report will actually be billed to. `source` is decided server-side by
   credentials.resolve_credential: your own key, then your department's, then the
   platform's. */

export const CREDENTIAL_SOURCE_COPY: Record<EffectiveCredentialResponse["source"], string> = {
  user: "your personal key",
  department: "your department's key",
  platform: "the platform key",
  none: "no key at all",
};

export function effectiveSentence(effective: EffectiveCredentialResponse | null | undefined): string {
  if (!effective) return "Which key your reports use has not been read yet.";
  if (effective.source === "none") {
    return "Reports cannot be generated right now: no key is set for you, for your department, or for the platform.";
  }
  return `Reports currently use ${CREDENTIAL_SOURCE_COPY[effective.source]}.`;
}

export const PROVIDER_LABELS: Record<string, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
};

export function providerLabel(provider: string | null | undefined): string {
  if (!provider) return "—";
  return PROVIDER_LABELS[provider] ?? provider;
}

/* The daily AI allowance, in the same terms the API refuses in. A cap of 0 is no limit,
   which is what credentials.is_more_permissive treats it as, so it is never printed as
   "0 tokens". */

export const BUDGET_SOURCE_COPY: Record<BudgetSource, string> = {
  user: "a limit set for you",
  department: "your department's limit",
  platform: "the platform's limit",
  platform_default: "the platform default",
};

export function tokenCount(tokens: number): string {
  return tokens.toLocaleString();
}

export function capLabel(cap: number): string {
  return cap <= 0 ? "no daily limit" : `${tokenCount(cap)} tokens a day`;
}

export function budgetSentence(budget: EffectiveBudgetResponse | null | undefined): string {
  if (!budget) return "Your daily AI allowance has not been read yet.";
  if (budget.daily_token_cap <= 0) return "You have no daily AI limit.";
  return `You can spend ${tokenCount(budget.daily_token_cap)} AI tokens a day.`;
}

/* Where the number came from, and what it would fall back to. Both, because "200,000 a
   day" with no story does not tell anyone whether it is theirs to change. */
export function budgetSourceLine(budget: EffectiveBudgetResponse): string {
  const from = `From ${BUDGET_SOURCE_COPY[budget.source]}.`;
  if (budget.source !== "user") return from;
  return `${from} Without it you would fall back to ${BUDGET_SOURCE_COPY[budget.inherited_source]}, ${capLabel(budget.inherited_cap)}.`;
}

/* Why the raise control is missing. The reason is whose key pays, and that is not always
   the level that set the number: a department can set a limit without installing a key,
   in which case the platform is still the one paying. `show_figures` is the same test the
   API uses for that question, so it picks the payer here and `source` only names who set
   the number. */
export function capLockedLine(budget: EffectiveBudgetResponse): string {
  const payer = budget.show_figures
    ? "Your department's key is what pays for your reports, so the limit on it is your department's to set."
    : "It protects the shared platform key, which is what pays for your reports at the moment.";
  const own = budget.source === "user"
    ? ` The number itself is a limit set on your account; without it you would be on ${BUDGET_SOURCE_COPY[budget.inherited_source]}, ${capLabel(budget.inherited_cap)}.`
    : "";
  return `This limit is not yours to raise. ${payer}${own} Add a key of your own above and the limit on it becomes yours to set.`;
}
