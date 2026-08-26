<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import type { SelectOption, TabItem } from "@crescent/ui/types/ui";
import type {
  BudgetList,
  BudgetResponse,
  CredentialList,
  CredentialResponse,
  EffectiveBudgetResponse,
  EffectiveCredentialResponse,
  Page,
  PersonaResponse,
} from "~/types/api";

definePageMeta({ middleware: "auth" });

/* Two things a person owns rather than a team does: how their reports are written, and
   which API key pays for writing them. Both are per-user settings the products read on
   every generation, so they live on one screen rather than behind two.

   Neither half can be derived from the other, so they are tabs, not sections stacked
   into one long scroll. */

const PERSONA_LIMIT = 100;

const api = useApi();
const route = useRoute();
const router = useRouter();
const queryClient = useQueryClient();
const announce = useAnnounce();
const { show: showToast } = useToast();
const { me } = useMe();

const tab = computed({
  get: () => (route.query.tab === "keys" ? "keys" : "personas") as "personas" | "keys",
  set: (value) => router.replace({ query: { ...route.query, tab: value === "personas" ? undefined : value } }),
});

/* No `hint` on either tab. A label and a hint render at the same weight in <Tabs>, so
   "Personas · How reports are written" and "API keys · Which key pays for them" read as
   four headings on a two-tab rail. Each hint is now the opening line of its own
   <TabPanel>, which is where a settings screen normally puts it. */
const tabs = computed<TabItem[]>(() => [
  { id: "personas", label: "Personas", hasPanel: true },
  { id: "keys", label: "API keys", hasPanel: true },
]);

/* ── personas ──────────────────────────────────────────────────────────────── */

const {
  data: personaPage,
  isPending: personasPending,
  isError: personasFailed,
  error: personasError,
} = useQuery({
  queryKey: ["personas"],
  retry: false,
  queryFn: () => api.request<Page<PersonaResponse>>("/personas", { query: { limit: PERSONA_LIMIT, offset: 0 } }),
});

const personas = computed(() => personaPage.value?.items ?? []);
// The API sorts presets first; splitting them keeps that visible even if it ever stops.
const presets = computed(() => personas.value.filter(isSystemPersona));
const mine = computed(() => personas.value.filter((p) => !isSystemPersona(p)));
const myDefault = computed(() => mine.value.find((p) => p.is_default) ?? null);

/* The answer this tab exists to give. personas.resolve falls back to the preset named
   `DEFAULT_SYSTEM_PERSONA` when you have no default of your own, so the fallback is named
   rather than described as "a built-in". */
const SYSTEM_FALLBACK = "Concise";

const activePersona = computed(
  () => myDefault.value ?? presets.value.find((p) => p.name === SYSTEM_FALLBACK) ?? null,
);

const personaSentence = computed(() => {
  if (myDefault.value) return `Reports are written as ${myDefault.value.name}.`;
  return `Reports are written with the built-in ${SYSTEM_FALLBACK} preset.`;
});

const composing = ref(false);
const editing = ref<PersonaResponse | null>(null);
const personaError = ref<string | null>(null);

const form = reactive({
  name: "",
  length: "standard",
  audience: "manager",
  technical_depth: "medium",
  formality: "neutral",
  instructions: "",
});

function resetForm() {
  form.name = "";
  form.length = "standard";
  form.audience = "manager";
  form.technical_depth = "medium";
  form.formality = "neutral";
  form.instructions = "";
}

function startCreate() {
  resetForm();
  editing.value = null;
  personaError.value = null;
  composing.value = true;
}

function startEdit(persona: PersonaResponse) {
  form.name = persona.name;
  form.length = persona.length;
  form.audience = persona.audience;
  form.technical_depth = persona.technical_depth;
  form.formality = persona.formality;
  form.instructions = persona.instructions ?? "";
  editing.value = persona;
  personaError.value = null;
  composing.value = true;
}

// A preset cannot be edited — the API answers 403 — so the offer is a copy of it, which
// is what personas._writable's own message tells people to do.
function startCopy(persona: PersonaResponse) {
  startEdit(persona);
  editing.value = null;
  form.name = `${persona.name} (mine)`;
}

function closeForm() {
  composing.value = false;
  editing.value = null;
  personaError.value = null;
}

const namedAlready = computed(() =>
  mine.value.some((p) => p.name.trim().toLowerCase() === form.name.trim().toLowerCase() && p.id !== editing.value?.id),
);

const savePersona = useMutation({
  mutationFn: () => {
    const body = {
      name: form.name.trim(),
      length: form.length,
      audience: form.audience,
      technical_depth: form.technical_depth,
      formality: form.formality,
      instructions: form.instructions.trim() === "" ? null : form.instructions.trim(),
    };
    return editing.value
      ? api.request<PersonaResponse>(`/personas/${editing.value.id}`, { method: "PATCH", body })
      : api.request<PersonaResponse>("/personas", { method: "POST", body });
  },
  onSuccess: (saved) => {
    closeForm();
    queryClient.invalidateQueries({ queryKey: ["personas"] });
    announce(`Persona ${saved.name} saved`);
  },
  onError: (err) => {
    // The form is deliberately left standing: everything typed into it is still needed.
    personaError.value =
      httpStatus(err) === 403
        ? "Built-in personas cannot be edited. Copy one into your own and change the copy."
        : apiMessage(err, "Could not save that persona.");
  },
});

const setDefault = useMutation({
  mutationFn: (persona: PersonaResponse) =>
    api.request<PersonaResponse>(`/personas/${persona.id}/default`, { method: "PUT" }),
  onSuccess: (updated) => {
    // Exactly one default, reflected before the refetch lands: the API clears the old one
    // in the same transaction, so showing two for a moment would be showing a lie.
    const current = personaPage.value;
    if (current) {
      queryClient.setQueryData(["personas"], {
        ...current,
        items: current.items.map((p) => ({ ...p, is_default: p.id === updated.id })),
      });
    }
    queryClient.invalidateQueries({ queryKey: ["personas"] });
    personaError.value = null;
    announce(`${updated.name} is now your default persona`);
  },
  onError: (err) => {
    personaError.value = apiMessage(err, "Could not set that default.");
  },
});

const confirmPersonaDelete = ref<PersonaResponse | null>(null);

const deletePersona = useMutation({
  mutationFn: (persona: PersonaResponse) =>
    api.request<void>(`/personas/${persona.id}`, { method: "DELETE" }),
  onSuccess: () => {
    confirmPersonaDelete.value = null;
    queryClient.invalidateQueries({ queryKey: ["personas"] });
    showToast("Persona deleted.", "muted");
  },
  onError: (err) => {
    confirmPersonaDelete.value = null;
    personaError.value = apiMessage(err, "Could not delete that persona.");
  },
});

/* ── api keys ──────────────────────────────────────────────────────────────── */

const {
  data: credentialList,
  isPending: credsPending,
  isError: credsFailed,
  error: credsError,
} = useQuery({
  queryKey: ["credentials"],
  retry: false,
  queryFn: () => api.request<CredentialList>("/settings/credentials"),
});

const credentials = computed(() => credentialList.value?.items ?? []);

const { data: effective, isError: effectiveFailed } = useQuery({
  queryKey: ["credentials", "effective"],
  retry: false,
  queryFn: () => api.request<EffectiveCredentialResponse>("/settings/credentials/effective"),
});

/* ── the daily allowance ───────────────────────────────────────────────────── */

/* What a call right now is measured against, where that number came from, and whether it
   is this person's to raise. The API decides the last one: you may only lift a limit on
   spend you are paying for, so somebody drawing on the platform key gets the figure and
   the reason rather than a control that would answer 403.

   Whether the figures are shown is a separate answer from the API, `show_figures`, and
   the two part company for a user under a department key: the department's money is being
   spent on them, so the numbers are theirs to see, but the cap is not theirs to raise. */

const {
  data: budget,
  isPending: budgetPending,
  isError: budgetFailed,
} = useQuery({
  queryKey: ["budgets", "effective"],
  retry: false,
  queryFn: () => api.request<EffectiveBudgetResponse>("/settings/credentials/budgets/effective"),
});

const { data: budgetList } = useQuery({
  queryKey: ["budgets"],
  retry: false,
  queryFn: () => api.request<BudgetList>("/settings/credentials/budgets"),
});

// The row that would have to be deleted to give the inherited limit back. Only a row of
// your own: a department's is not yours to remove from here.
const myBudget = computed<BudgetResponse | null>(
  () => budgetList.value?.items.find((row) => row.scope === "user" && row.owner_user_id === me.value?.id) ?? null,
);

const mayRaise = computed(() => budget.value?.may_raise === true);
const showsFigures = computed(() => budget.value?.show_figures === true);

// `v-model` on <input type="number"> hands back a number, and an empty box hands back
// the empty string, so the draft is whichever of the two the input last produced.
const capDraft = ref<string | number>("");
const capError = ref<string | null>(null);
const editingCap = ref(false);

function startCapEdit() {
  capDraft.value = String(budget.value?.daily_token_cap ?? 0);
  capError.value = null;
  editingCap.value = true;
}

function cancelCapEdit() {
  editingCap.value = false;
  capError.value = null;
}

// services/pulse/app/schemas/credentials.py: ge=0, le=1_000_000_000. Checked here so a
// typo is caught before a 422 is.
const MAX_TOKEN_CAP = 1_000_000_000;

const capReady = computed(() => {
  const raw = String(capDraft.value).trim();
  const value = Number(raw);
  return raw !== "" && Number.isInteger(value) && value >= 0 && value <= MAX_TOKEN_CAP;
});

const saveCap = useMutation({
  mutationFn: () =>
    api.request<BudgetResponse>("/settings/credentials/budgets", {
      method: "PUT",
      body: { scope: "user", daily_token_cap: Number(capDraft.value), owner_user_id: me.value?.id },
    }),
  onSuccess: (saved) => {
    editingCap.value = false;
    capError.value = null;
    queryClient.invalidateQueries({ queryKey: ["budgets"] });
    announce(`Daily AI allowance set to ${capLabel(saved.daily_token_cap)}`);
    showToast("Daily AI allowance saved.", "ok");
  },
  onError: (err) => {
    capError.value = apiMessage(err, "Could not change your daily AI allowance.");
  },
});

const clearCap = useMutation({
  mutationFn: (row: BudgetResponse) =>
    api.request<void>(`/settings/credentials/budgets/${row.id}`, { method: "DELETE" }),
  onSuccess: () => {
    editingCap.value = false;
    capError.value = null;
    queryClient.invalidateQueries({ queryKey: ["budgets"] });
    showToast("Your own limit is removed. The inherited one applies again.", "muted");
  },
  onError: (err) => {
    capError.value = apiMessage(err, "Could not remove your own limit.");
  },
});

/* Who may write a department key: credentials._require_may_write wants a platform admin
   or an admin of that department. Both facts are in the identity claims this page
   already holds, so the option is offered or it is not — never offered and then 403'd. */
const adminDepts = computed(() => {
  const user = me.value;
  if (!user) return [];
  return user.memberships.filter((m) => user.is_platform_admin || m.role === "admin");
});
const canSetDept = computed(() => adminDepts.value.length > 0);

const deptOptions = computed<SelectOption[]>(() =>
  adminDepts.value.map((m) => ({ value: String(m.dept_id), label: m.dept_name })),
);

const scopeOptions = computed<SelectOption[]>(() => [
  { value: "user", label: "Just me" },
  ...(canSetDept.value ? [{ value: "department", label: "My department" }] : []),
]);

const PROVIDER_OPTIONS: SelectOption[] = [
  { value: "anthropic", label: "Anthropic" },
  { value: "openai", label: "OpenAI" },
];

const key = reactive({
  scope: "user",
  provider: "anthropic",
  dept_id: "",
  model: "",
  bypass_token_cap: false,
});
// Held apart from the rest of the form so that clearing it is one statement, and so that
// nothing that logs or serialises the form can pick it up by accident.
const secret = ref("");
const keyError = ref<string | null>(null);

const keyReady = computed(() => {
  if (secret.value.trim().length < 8) return false;
  return key.scope !== "department" || key.dept_id !== "";
});

const saveKey = useMutation({
  mutationFn: () =>
    api.request<CredentialResponse>("/settings/credentials", {
      method: "PUT",
      // A key goes in a request body and nowhere else — never a query string, which is
      // logged by every proxy between here and the service.
      body: {
        scope: key.scope,
        provider: key.provider,
        key: secret.value.trim(),
        model: key.model.trim() === "" ? null : key.model.trim(),
        bypass_token_cap: key.bypass_token_cap,
        ...(key.scope === "department" ? { dept_id: Number(key.dept_id) } : {}),
      },
    }),
  onSuccess: (saved) => {
    // The one place the key is dropped. It is never written anywhere else.
    secret.value = "";
    keyError.value = null;
    queryClient.invalidateQueries({ queryKey: ["credentials"] });
    announce(`${providerLabel(saved.provider)} key saved, ending ${saved.last_four}`);
    showToast("API key saved.", "ok");
  },
  onError: (err) => {
    const code = httpStatus(err);
    // Everything the person typed stays where it is, including the key: a rejected key is
    // usually a key with a character missing, not a key they can fetch again easily.
    keyError.value =
      code === 422
        ? apiMessage(err, "That key was refused. Pulse checks a key against the provider before saving it, so this one did not answer.")
        : code === 403
          ? "You cannot set a key at that scope. A department key needs you to be an admin of that department."
          : apiMessage(err, "Could not save that key.");
  },
});

const confirmKeyDelete = ref<CredentialResponse | null>(null);

const deleteKey = useMutation({
  mutationFn: (credential: CredentialResponse) =>
    api.request<void>(`/settings/credentials/${credential.id}`, { method: "DELETE" }),
  onSuccess: () => {
    confirmKeyDelete.value = null;
    queryClient.invalidateQueries({ queryKey: ["credentials"] });
    showToast("API key removed.", "muted");
  },
  onError: (err) => {
    confirmKeyDelete.value = null;
    keyError.value = apiMessage(err, "Could not remove that key.");
  },
});

// The cap flag is a setting, not a secret, so it is a toggle on the row rather than a
// reason to make someone paste their key again. The endpoint leaves the stored key alone
// when the body carries no `key`.
const capPending = ref<number | null>(null);

const toggleCap = useMutation({
  mutationFn: (credential: CredentialResponse) =>
    api.request<CredentialResponse>("/settings/credentials", {
      method: "PUT",
      body: {
        scope: credential.scope,
        provider: credential.provider,
        model: credential.model,
        bypass_token_cap: !credential.bypass_token_cap,
        ...(credential.scope === "department"
          ? { dept_id: credential.dept_id }
          : { owner_user_id: credential.owner_user_id }),
      },
    }),
  onMutate: (credential: CredentialResponse) => {
    capPending.value = credential.id;
    keyError.value = null;
  },
  onSuccess: (saved) => {
    queryClient.invalidateQueries({ queryKey: ["credentials"] });
    const state = saved.bypass_token_cap ? "no longer capped" : "capped again";
    announce(`${providerLabel(saved.provider)} key ending ${saved.last_four} is ${state}`);
    showToast(saved.bypass_token_cap ? "Daily token cap skipped for this key." : "Daily token cap applies to this key.", "ok");
  },
  onError: (err) => {
    keyError.value =
      httpStatus(err) === 403
        ? "You cannot change the cap on that key. A department key needs you to be an admin of that department."
        : apiMessage(err, "Could not change the token cap for that key.");
  },
  onSettled: () => {
    capPending.value = null;
  },
});

// Replace still exists for the key itself, which genuinely cannot be edited in place.
const keyField = ref<HTMLInputElement | null>(null);

function startReplace(credential: CredentialResponse) {
  key.scope = credential.scope;
  key.provider = credential.provider;
  key.dept_id = credential.dept_id === null ? "" : String(credential.dept_id);
  key.model = credential.model ?? "";
  key.bypass_token_cap = credential.bypass_token_cap;
  secret.value = "";
  keyError.value = null;
  nextTick(() => keyField.value?.focus());
}

function scopeLabel(credential: CredentialResponse): string {
  if (credential.scope !== "department") return "Just you";
  const dept = me.value?.memberships.find((m) => m.dept_id === credential.dept_id);
  return dept ? dept.dept_name : `dept_id ${credential.dept_id}`;
}
</script>

<template>
  <PulseShell readout="settings">
    <header class="sec">
      <Eyebrow>Pulse · settings</Eyebrow>
      <h1 class="mt-3 text-[clamp(1.5rem,2.2vw,1.9rem)] font-semibold leading-[1.05] tracking-[-0.035em]">
        Your settings
      </h1>
      <p class="mt-2 max-w-[68ch] text-pretty text-[13.5px] leading-relaxed text-ink-muted">
        How your reports are written, and which API key writes them. Both apply to every
        report you generate, whether weekly, custom or the journal rollup.
      </p>
    </header>

    <div class="sec" style="animation-delay: 40ms">
      <Tabs
        id="settings"
        :model-value="tab"
        label="Settings section"
        class="mt-6"
        has-panel
        :items="tabs"
        @update:model-value="tab = $event as 'personas' | 'keys'"
      />
    </div>

    <!-- ── personas ────────────────────────────────────────────────────────── -->
    <TabPanel v-if="tab === 'personas'" id="settings" tab="personas" class="mt-7">
      <div class="flex flex-wrap items-start justify-between gap-4">
        <p class="max-w-[70ch] text-pretty text-[13.5px] leading-relaxed text-ink-muted">
          A persona is how a report is written: four dials and an optional note. It changes
          the wording, not the facts. The same GitHub activity produces the same claims
          whichever persona you pick.
        </p>
        <Btn size="sm" data-test="persona-new" @click="startCreate">New persona</Btn>
      </div>

      <!-- What is in effect, before anything you can change. -->
      <section
        class="mt-5 rounded-md bg-surface/40 px-5 py-5 ring-1 ring-inset ring-line-subtle"
        aria-labelledby="persona-effective-heading"
        aria-live="polite"
      >
        <p :class="[MONO_LABEL, 'text-ink-faint']">In effect now</p>
        <h2 id="persona-effective-heading" data-test="persona-effective" class="mt-2.5 max-w-[40ch] text-balance text-[22px] font-semibold leading-[1.2] tracking-[-0.025em] text-ink">
          <template v-if="personasPending">Reading your personas…</template>
          <template v-else-if="personasFailed">Which persona writes your reports could not be read.</template>
          <template v-else>{{ personaSentence }}</template>
        </h2>
        <p v-if="activePersona" class="mono mt-3 text-[12px] text-ink-muted">
          {{ personaLine(activePersona) }}
        </p>
        <p class="mt-3 max-w-[70ch] text-[13px] leading-relaxed text-ink-muted">
          Pulse uses your default persona unless you pick another one while generating a
          report. With no default of your own it falls back to the built-in {{ SYSTEM_FALLBACK }} preset.
        </p>
      </section>

      <p
        v-if="personaError"
        role="alert"
        data-test="persona-error"
        class="mt-5 max-w-[74ch] rounded-md bg-bad-surface px-4 py-3.5 text-[13.5px] leading-relaxed text-ink"
      >
        {{ personaError }}
      </p>

      <!-- Create or edit. Inline rather than in a dialog: the preview underneath is the
           point of the form, and a dialog would cover the list it is being compared to. -->
      <section
        v-if="composing"
        data-test="persona-form"
        class="mt-5 rounded-md bg-surface/40 px-5 py-6 ring-1 ring-inset ring-line-subtle"
        aria-labelledby="persona-form-heading"
      >
        <h2 id="persona-form-heading" class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">
          {{ editing ? `Edit ${editing.name}` : "New persona" }}
        </h2>
        <p class="mt-1.5 max-w-[70ch] text-[13px] leading-relaxed text-ink-muted">
          Nothing here changes a report you have already written. It applies from the next
          one you generate with this persona.
        </p>

        <label for="persona-name" class="mt-6 block text-[13px] font-medium text-ink">Name</label>
        <input
          id="persona-name"
          v-model="form.name"
          type="text"
          data-test="persona-name"
          maxlength="120"
          autocomplete="off"
          :class="[FOCUS, 'mt-2 w-full max-w-[360px] rounded-md bg-sunken px-3 py-2.5 text-[13.5px] text-ink ring-1 ring-inset ring-line transition-colors placeholder:text-ink-faint hover:ring-line-strong']"
          placeholder="Weekly note to my lead"
        >
        <p v-if="namedAlready" class="mt-2 text-[12.5px] text-warn">
          You already have a persona with that name; the API refuses a duplicate.
        </p>

        <p class="mt-6 text-[13px] font-medium text-ink">The four dials</p>
        <div class="mt-3 flex flex-wrap gap-4">
          <div v-for="dial in PERSONA_DIALS" :key="dial.key">
            <p class="mb-2 text-[12.5px] text-ink-muted">{{ dial.label }}</p>
            <Select
              class="w-[190px]"
              :label="dial.label"
              :data-test="`dial-${dial.key}`"
              :model-value="form[dial.key]"
              :options="dialOptions(dial)"
              @update:model-value="form[dial.key] = $event"
            />
          </div>
        </div>

        <p
          data-test="persona-preview"
          class="mt-5 max-w-[74ch] rounded-md bg-sunken px-4 py-3 text-[13px] leading-relaxed text-ink ring-1 ring-inset ring-line-subtle"
        >
          <span :class="[MONO_LABEL, 'mr-2 text-ink-faint']">reads as</span>
          {{ personaPreview(form) }}
        </p>

        <label for="persona-instructions" class="mt-6 block text-[13px] font-medium text-ink">
          Anything else the writer should know
        </label>
        <p class="mt-1 max-w-[70ch] text-[12.5px] leading-relaxed text-ink-muted">
          Optional. One or two sentences in your own words, passed to the writer with every report.
        </p>
        <textarea
          id="persona-instructions"
          v-model="form.instructions"
          rows="3"
          maxlength="2000"
          data-test="persona-instructions"
          placeholder="Always mention anything that slipped, and name the pull request that fixed it."
          :class="[FOCUS, 'mt-2 w-full max-w-[74ch] resize-y rounded-md bg-sunken px-3 py-2.5 text-[13.5px] leading-relaxed text-ink ring-1 ring-inset ring-line transition-colors placeholder:text-ink-faint hover:ring-line-strong']"
        />

        <div class="mt-6 flex flex-wrap items-center gap-2">
          <Btn
            size="sm"
            data-test="persona-save"
            :disabled="form.name.trim() === ''"
            :busy="savePersona.isPending.value"
            @click="savePersona.mutate()"
          >{{ editing ? "Save changes" : "Create persona" }}</Btn>
          <Btn size="sm" variant="ghost" data-test="persona-cancel" @click="closeForm">Cancel</Btn>
        </div>
      </section>

      <p v-if="personasPending" class="mt-7 text-[13.5px] text-ink-muted">Reading your personas…</p>

      <p
        v-else-if="personasFailed"
        role="alert"
        class="mt-7 max-w-[74ch] rounded-md bg-bad-surface px-4 py-3.5 text-[13.5px] leading-relaxed text-ink"
      >
        {{ apiMessage(personasError, "Could not read your personas. Check that the Pulse API is running.") }}
      </p>

      <template v-else>
        <!-- Yours. -->
        <section class="mt-10" aria-labelledby="mine-heading">
          <h2 id="mine-heading" class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">Your personas</h2>
          <p class="mt-1.5 max-w-[74ch] text-[13px] leading-relaxed text-ink-muted">
            Personas you wrote. Only one can be the default, and that is the one used when you
            do not pick another while generating.
          </p>

          <div
            v-if="!mine.length"
            data-test="personas-empty"
            class="mt-4 rounded-md bg-surface/40 px-5 py-5 ring-1 ring-inset ring-line-subtle"
          >
            <p class="max-w-[70ch] text-[13.5px] leading-relaxed text-ink">
              You have not written a persona yet.
            </p>
            <!-- No button here. "New persona" already sits at the top of this tab, and an
                 empty list used to put a second one on screen with the same label: two
                 controls that read as a choice and are not. The route this state actually
                 recommends is copying a preset, which every preset row already offers. -->
            <p class="mt-2 max-w-[70ch] text-[13px] leading-relaxed text-ink-muted">
              Until you do, every report is written with the built-in {{ SYSTEM_FALLBACK }} preset.
              Write your own to get reports in your own wording. The quickest start is
              <span class="text-ink">Copy to mine</span> on one of the built-in presets below,
              then change the wording. <span class="text-ink">New persona</span> at the top of
              this tab starts from nothing.
            </p>
          </div>

          <ul v-else data-test="my-personas" class="mt-3 divide-y divide-line-subtle border-t border-line-subtle">
            <li v-for="persona in mine" :key="persona.id" class="py-5" data-test="persona-row">
              <div class="flex flex-wrap items-start justify-between gap-4">
                <div class="min-w-0">
                  <p class="flex flex-wrap items-center gap-2">
                    <span class="text-[14px] font-medium text-ink">{{ persona.name }}</span>
                    <StatusDot v-if="persona.is_default" tone="ok" data-test="persona-default-badge">Default</StatusDot>
                  </p>
                  <p class="mono mt-1.5 text-[12px] text-ink-muted">{{ personaLine(persona) }}</p>
                  <p class="mt-2 max-w-[74ch] text-[13px] leading-relaxed text-ink-muted">
                    {{ personaPreview(persona) }}
                  </p>
                  <p v-if="persona.instructions" class="mt-2 max-w-[74ch] whitespace-pre-wrap text-[13px] leading-relaxed text-ink">
                    “{{ persona.instructions }}”
                  </p>
                </div>
                <!-- Delete sits behind its own rule rather than shoulder to shoulder with
                     the two actions that are safe to mis-click. -->
                <div class="flex shrink-0 flex-wrap items-center gap-2">
                  <Btn
                    v-if="!persona.is_default"
                    size="sm"
                    variant="secondary"
                    data-test="persona-make-default"
                    :busy="setDefault.isPending.value && setDefault.variables.value?.id === persona.id"
                    @click="setDefault.mutate(persona)"
                  >Make default</Btn>
                  <button
                    type="button"
                    data-test="persona-edit"
                    :class="[FOCUS, 'rounded px-1.5 py-1 text-[13px] text-ink-muted transition-colors hover:text-ink']"
                    @click="startEdit(persona)"
                  >Edit</button>
                  <span aria-hidden="true" class="h-4 w-px bg-line-subtle" />
                  <button
                    type="button"
                    data-test="persona-delete"
                    :class="[FOCUS, 'rounded px-1.5 py-1 text-[13px] text-bad transition-colors hover:brightness-110']"
                    @click="confirmPersonaDelete = persona"
                  >Delete</button>
                </div>
              </div>
            </li>
          </ul>
        </section>

        <!-- The presets. Read-only, and nothing here offers an action the API would refuse. -->
        <section class="mt-10" aria-labelledby="presets-heading">
          <h2 id="presets-heading" class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">Built in</h2>
          <p class="mt-1.5 max-w-[74ch] text-[13px] leading-relaxed text-ink-muted">
            These ship with Pulse and cannot be changed or deleted, by you or by anyone else.
            Copy one to get an editable version of your own.
          </p>

          <ul data-test="preset-personas" class="mt-3 divide-y divide-line-subtle border-t border-line-subtle">
            <li v-for="persona in presets" :key="persona.id" class="py-5" data-test="preset-row">
              <div class="flex flex-wrap items-start justify-between gap-4">
                <div class="min-w-0">
                  <p class="flex flex-wrap items-center gap-2">
                    <span class="text-[14px] font-medium text-ink">{{ persona.name }}</span>
                    <span :class="[MONO_LABEL, 'rounded bg-sunken px-2 py-1 text-ink-muted ring-1 ring-inset ring-line-subtle']" data-test="preset-badge">
                      Built in
                    </span>
                  </p>
                  <p class="mono mt-1.5 text-[12px] text-ink-muted">{{ personaLine(persona) }}</p>
                  <p class="mt-2 max-w-[74ch] text-[13px] leading-relaxed text-ink-muted">
                    {{ personaPreview(persona) }}
                  </p>
                </div>
                <Btn size="sm" variant="secondary" data-test="persona-copy" @click="startCopy(persona)">
                  Copy to mine
                </Btn>
              </div>
            </li>
          </ul>
        </section>
      </template>
    </TabPanel>

    <!-- ── api keys ────────────────────────────────────────────────────────── -->
    <TabPanel v-if="tab === 'keys'" id="settings" tab="keys" class="mt-7">
      <p class="max-w-[70ch] text-pretty text-[13.5px] leading-relaxed text-ink-muted">
        An API key is what pays the model provider for writing a report. Pulse can use one you
        supply, one your department supplies, or the shared platform key.
      </p>

      <!-- The answer somebody opens this tab to get, before anything they can change. -->
      <section
        data-test="effective"
        class="mt-5 rounded-md bg-surface/40 px-5 py-5 ring-1 ring-inset ring-line-subtle"
        aria-labelledby="effective-heading"
        aria-live="polite"
      >
        <p :class="[MONO_LABEL, 'text-ink-faint']">In effect now</p>
        <h2 id="effective-heading" class="mt-2.5 max-w-[40ch] text-balance text-[22px] font-semibold leading-[1.2] tracking-[-0.025em] text-ink">
          <template v-if="effectiveFailed">
            Which key your reports use could not be read.
          </template>
          <template v-else>{{ effectiveSentence(effective) }}</template>
        </h2>
        <p v-if="effectiveFailed" class="mt-3 max-w-[70ch] text-[13px] leading-relaxed text-ink-muted">
          The list below is a separate request and may still be right.
        </p>
        <p v-else-if="effective && effective.source !== 'none'" class="mono mt-3 text-[12px] text-ink-muted">
          {{ providerLabel(effective.provider) }}
          <template v-if="effective.model"> · {{ effective.model }}</template>
          · token cap {{ effective.bypass_token_cap ? "bypassed" : "applies" }}
        </p>
        <p class="mt-3 max-w-[70ch] text-[13px] leading-relaxed text-ink-muted">
          Pulse looks for your own key first, then your department's, then the platform's. The
          first one it finds is the one that pays.
        </p>
      </section>

      <!-- What a call is measured against. Sits next to "in effect now" because the two
           answer the same question from opposite ends: which key pays, and how much of it. -->
      <section
        data-test="budget"
        class="mt-4 rounded-md bg-surface/40 px-5 py-5 ring-1 ring-inset ring-line-subtle"
        aria-labelledby="budget-heading"
        aria-live="polite"
      >
        <p :class="[MONO_LABEL, 'text-ink-faint']">Daily AI allowance</p>
        <h2 id="budget-heading" class="mt-2.5 max-w-[40ch] text-balance text-[22px] font-semibold leading-[1.2] tracking-[-0.025em] text-ink">
          <template v-if="budgetFailed">Your daily AI allowance could not be read.</template>
          <template v-else-if="budgetPending">Reading your daily AI allowance…</template>
          <template v-else>{{ budgetSentence(budget) }}</template>
        </h2>

        <template v-if="budget && !budgetFailed">
          <p class="mt-3 max-w-[70ch] text-[13px] leading-relaxed text-ink-muted" data-test="budget-source">
            {{ budgetSourceLine(budget) }}
          </p>

          <!-- Figures follow the same rule the API's refusals do: they go to whoever is
               paying. On the platform key a token count is somebody else's accounting. -->
          <p v-if="showsFigures" class="mono mt-2 text-[12px] tabular-nums text-ink-muted" data-test="budget-used">
            {{ tokenCount(budget.tokens_used_today) }} used today
          </p>

          <template v-if="mayRaise">
            <div v-if="editingCap" class="mt-4">
              <label for="token-cap" class="block text-[13px] font-medium text-ink">Tokens a day</label>
              <p class="mt-1 max-w-[70ch] text-[12.5px] leading-relaxed text-ink-muted">
                0 means no limit. The count resets at 00:00 UTC.
              </p>
              <div class="mt-2 flex flex-wrap items-center gap-3">
                <input
                  id="token-cap"
                  v-model="capDraft"
                  type="number"
                  inputmode="numeric"
                  min="0"
                  :max="MAX_TOKEN_CAP"
                  step="1000"
                  data-test="cap-input"
                  autocomplete="off"
                  spellcheck="false"
                  placeholder="200000"
                  :class="[FOCUS, 'w-[200px] rounded-md bg-sunken px-3 py-2.5 text-[13.5px] tabular-nums text-ink ring-1 ring-inset ring-line transition-colors placeholder:text-ink-faint hover:ring-line-strong']"
                >
                <Btn size="sm" data-test="cap-save" :disabled="!capReady" :busy="saveCap.isPending.value" @click="saveCap.mutate()">
                  Save limit
                </Btn>
                <Btn size="sm" variant="ghost" data-test="cap-cancel" @click="cancelCapEdit">Cancel</Btn>
              </div>
            </div>

            <div v-else class="mt-4 flex flex-wrap items-center gap-3">
              <Btn size="sm" variant="secondary" data-test="cap-edit" @click="startCapEdit">
                {{ myBudget ? "Change your limit" : "Set your own limit" }}
              </Btn>
              <button
                v-if="myBudget"
                type="button"
                data-test="cap-clear"
                :disabled="clearCap.isPending.value"
                :class="[FOCUS, DISABLED, 'rounded px-1.5 py-1 text-[13px] text-ink-muted transition-colors enabled:hover:text-ink']"
                @click="myBudget && clearCap.mutate(myBudget)"
              >Use the inherited limit instead</button>
            </div>
          </template>

          <p v-else class="mt-4 max-w-[70ch] text-[13px] leading-relaxed text-ink-muted" data-test="cap-locked">
            {{ capLockedLine(budget) }}
          </p>

          <p
            v-if="capError"
            role="alert"
            data-test="cap-error"
            class="mt-3 max-w-[74ch] rounded-md bg-bad-surface px-4 py-3 text-[13px] leading-relaxed text-ink"
          >{{ capError }}</p>
        </template>
      </section>

      <p
        v-if="keyError"
        role="alert"
        data-test="key-error"
        class="mt-5 max-w-[74ch] rounded-md bg-bad-surface px-4 py-3.5 text-[13.5px] leading-relaxed text-ink"
      >
        {{ keyError }}
      </p>

      <section class="mt-10" aria-labelledby="keys-heading">
        <h2 id="keys-heading" class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">Keys you can see</h2>
        <p class="mt-1.5 max-w-[74ch] text-[13px] leading-relaxed text-ink-muted">
          Your own key, plus any department key you administer. The key itself is never shown.
          Pulse stores it encrypted and cannot read it back, so a saved key appears as its last
          four digits.
        </p>

        <p v-if="credsPending" class="mt-4 text-[13.5px] text-ink-muted">Reading your keys…</p>

        <p
          v-else-if="credsFailed"
          role="alert"
          class="mt-4 max-w-[74ch] rounded-md bg-bad-surface px-4 py-3.5 text-[13.5px] leading-relaxed text-ink"
        >
          {{ apiMessage(credsError, "Could not read your API keys.") }}
        </p>

        <div
          v-else-if="!credentials.length"
          data-test="credentials-empty"
          class="mt-4 rounded-md bg-surface/40 px-5 py-5 ring-1 ring-inset ring-line-subtle"
        >
          <p class="max-w-[70ch] text-[13.5px] leading-relaxed text-ink">
            You have not set a key of your own.
          </p>
          <p class="mt-2 max-w-[70ch] text-[13px] leading-relaxed text-ink-muted">
            Reports still work. They fall through to whatever the order above lands on, and they
            count against the shared daily token budget that everyone else draws on. Setting your
            own key takes your reports off that budget.
          </p>
        </div>

        <ul v-else data-test="credentials" class="mt-3 divide-y divide-line-subtle border-t border-line-subtle">
          <li v-for="credential in credentials" :key="credential.id" class="flex flex-wrap items-start justify-between gap-4 py-5" data-test="credential-row">
            <div class="min-w-0">
              <p class="flex flex-wrap items-center gap-2">
                <span class="text-[14px] font-medium text-ink">{{ providerLabel(credential.provider) }}</span>
                <span class="mono text-[13px] text-ink-muted" data-test="last-four">•••• {{ credential.last_four }}</span>
              </p>
              <p class="mono mt-1.5 text-[12px] text-ink-muted">
                {{ scopeLabel(credential) }} ·
                {{ credential.model || "provider default model" }}
              </p>
              <label class="mt-3 flex max-w-[62ch] items-start gap-2.5">
                <input
                  type="checkbox"
                  data-test="credential-cap-toggle"
                  :checked="credential.bypass_token_cap"
                  :disabled="capPending !== null"
                  :class="[FOCUS, 'mt-0.5 h-4 w-4 shrink-0 rounded ring-1 ring-inset ring-line']"
                  @change="toggleCap.mutate(credential)"
                >
                <span class="text-[13px] leading-relaxed text-ink" data-test="credential-cap-label">
                  <template v-if="credential.bypass_token_cap">
                    Daily token cap bypassed for this key. Reports billed to it run past the shared limit.
                  </template>
                  <template v-else>
                    Daily token cap applies to this key. Tick to let reports billed to it run past the shared limit.
                  </template>
                </span>
              </label>
            </div>
            <div class="flex shrink-0 items-center gap-2">
              <Btn size="sm" variant="secondary" data-test="credential-replace" @click="startReplace(credential)">
                Replace
              </Btn>
              <span aria-hidden="true" class="h-4 w-px bg-line-subtle" />
              <button
                type="button"
                data-test="credential-delete"
                :class="[FOCUS, 'rounded px-1.5 py-1 text-[13px] text-bad transition-colors hover:brightness-110']"
                @click="confirmKeyDelete = credential"
              >Remove</button>
            </div>
          </li>
        </ul>
      </section>

      <section class="mt-10" aria-labelledby="add-key-heading">
        <h2 id="add-key-heading" class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">Add or replace a key</h2>
        <p class="mt-1.5 max-w-[74ch] text-[13px] leading-relaxed text-ink-muted">
          Pulse tries the key against the provider before saving it, so a key with a character
          missing is refused here rather than failing on your next report. Saving replaces any
          key already set at the same scope and provider.
        </p>

        <div class="mt-6 flex flex-wrap gap-5">
          <div>
            <p class="mb-2 text-[13px] font-medium text-ink">Who it is for</p>
            <Select
              class="w-[200px]"
              label="Who this key is for"
              :model-value="key.scope"
              :options="scopeOptions"
              @update:model-value="key.scope = $event"
            />
          </div>
          <div v-if="key.scope === 'department'">
            <p class="mb-2 text-[13px] font-medium text-ink">Department</p>
            <Select
              class="w-[200px]"
              label="Which department this key is for"
              placeholder="Choose a department"
              :model-value="key.dept_id"
              :options="deptOptions"
              @update:model-value="key.dept_id = $event"
            />
          </div>
          <div>
            <p class="mb-2 text-[13px] font-medium text-ink">Provider</p>
            <Select
              class="w-[180px]"
              label="Which provider this key is for"
              :model-value="key.provider"
              :options="PROVIDER_OPTIONS"
              @update:model-value="key.provider = $event"
            />
          </div>
          <div>
            <label for="key-model" class="mb-2 block text-[13px] font-medium text-ink">Model</label>
            <input
              id="key-model"
              v-model="key.model"
              type="text"
              data-test="key-model"
              maxlength="100"
              autocomplete="off"
              spellcheck="false"
              placeholder="Leave blank for the default…"
              :class="[FOCUS, 'w-[240px] rounded-md bg-sunken px-3 py-2.5 text-[13.5px] text-ink ring-1 ring-inset ring-line transition-colors placeholder:text-ink-faint hover:ring-line-strong']"
            >
          </div>
        </div>

        <label for="api-key" class="mt-6 block text-[13px] font-medium text-ink">API key</label>
        <p class="mt-1 max-w-[74ch] text-[12.5px] leading-relaxed text-ink-muted">
          Stored encrypted and never sent back to this page. Replacing it is the only way to change
          the key itself. The model and the token cap can be changed on the row above without
          re-entering it.
        </p>
        <input
          id="api-key"
          ref="keyField"
          v-model="secret"
          type="password"
          data-test="key-input"
          autocomplete="off"
          spellcheck="false"
          maxlength="500"
          placeholder="sk-…"
          :class="[FOCUS, 'mt-2 w-full max-w-[520px] rounded-md bg-sunken px-3 py-2.5 text-[13.5px] text-ink ring-1 ring-inset ring-line transition-colors placeholder:text-ink-faint hover:ring-line-strong']"
        >

        <label class="mt-6 flex max-w-[74ch] items-start gap-2.5">
          <input
            v-model="key.bypass_token_cap"
            type="checkbox"
            data-test="bypass-toggle"
            :class="[FOCUS, 'mt-0.5 h-4 w-4 shrink-0 rounded ring-1 ring-inset ring-line']"
          >
          <span class="text-[13.5px] leading-relaxed text-ink">
            Skip the daily token cap for this key. It never applies to the platform key.
            <span class="mt-1 block text-[13px] text-ink-muted">
              The cap exists so the shared platform key cannot be run dry by one person. Skipping it
              only ever applies to a key you or your department supplied and paid for. Reports that
              fall through to the platform key are capped whatever this says.
            </span>
          </span>
        </label>

        <div class="mt-6 flex flex-wrap items-center gap-3">
          <Btn
            size="sm"
            data-test="key-save"
            :disabled="!keyReady"
            :busy="saveKey.isPending.value"
            @click="saveKey.mutate()"
          >Save API key</Btn>
          <p v-if="key.scope === 'department' && key.dept_id === ''" class="text-[13px] text-ink-muted">
            Choose which department this key is for.
          </p>
          <p v-else-if="!canSetDept" class="max-w-[52ch] text-[13px] leading-relaxed text-ink-muted">
            Setting a key for a whole department needs you to be an admin of it, so only your own
            is offered.
          </p>
        </div>
      </section>
    </TabPanel>

    <Modal
      :open="confirmPersonaDelete !== null"
      title="Delete this persona?"
      :description="confirmPersonaDelete ? `${confirmPersonaDelete.name} will stop being available when you generate a report. Reports already written with it are untouched.` : undefined"
      :close-on-backdrop="false"
      @close="confirmPersonaDelete = null"
    >
      <p class="max-w-[46ch] text-[13px] leading-relaxed text-ink-muted">
        {{ confirmPersonaDelete ? personaPreview(confirmPersonaDelete) : "" }}
      </p>
      <template #footer>
        <Btn size="sm" variant="ghost" @click="confirmPersonaDelete = null">Keep it</Btn>
        <Btn
          size="sm"
          variant="destructive"
          data-test="persona-delete-confirm"
          :busy="deletePersona.isPending.value"
          @click="confirmPersonaDelete && deletePersona.mutate(confirmPersonaDelete)"
        >Delete persona</Btn>
      </template>
    </Modal>

    <Modal
      :open="confirmKeyDelete !== null"
      title="Remove this key?"
      :description="confirmKeyDelete ? `The ${providerLabel(confirmKeyDelete.provider)} key ending ${confirmKeyDelete.last_four} will be deleted. Pulse cannot show it to you first, so make sure you still have it.` : undefined"
      :close-on-backdrop="false"
      @close="confirmKeyDelete = null"
    >
      <p class="max-w-[46ch] text-[13px] leading-relaxed text-ink-muted">
        Reports will fall through to the next key in the order: your department's, then the
        platform's. They go back under the shared daily token cap.
      </p>
      <template #footer>
        <Btn size="sm" variant="ghost" @click="confirmKeyDelete = null">Keep it</Btn>
        <Btn
          size="sm"
          variant="destructive"
          data-test="credential-delete-confirm"
          :busy="deleteKey.isPending.value"
          @click="confirmKeyDelete && deleteKey.mutate(confirmKeyDelete)"
        >Remove key</Btn>
      </template>
    </Modal>
  </PulseShell>
</template>
