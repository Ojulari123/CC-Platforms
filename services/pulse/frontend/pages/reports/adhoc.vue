<script setup lang="ts">
import { useMutation, useQuery } from "@tanstack/vue-query";
import type { SelectOption } from "@crescent/ui/types/ui";
import type { Page, PersonaResponse, ReportResponse } from "~/types/api";
import type { AdhocFailure, SubjectRow } from "~/utils/adhoc";

definePageMeta({ middleware: "auth" });

/* A report about anyone, over any range, on any repository — including one Pulse has
   never synced. The weekly report answers "what did this repository do last week"; this
   answers "what did these people do between these dates", which is the question a
   promotion case or a handover actually asks.

   Everything typed here is expensive to retype and the generation can fail after a long
   wait, so nothing on this form is ever cleared by a failure. */

const api = useApi();
const router = useRouter();
const announce = useAnnounce();
const { me } = useMe();
const { repositories, isPending: reposPending, isError: reposFailed } = useRepositories();
const { data: teammates } = useTeammates();

/* ── the repository ────────────────────────────────────────────────────────── */

// Two ways to name a repository, and only ever one of them: a tracked repository is read
// out of Pulse's own synced tables, a typed one is fetched from GitHub during the
// request. The API enforces the exclusivity too (AdhocRequest._one_repository_and_a_sane_range).
const mode = ref<"tracked" | "live">("tracked");
const repoId = ref<number | null>(null);
const repoInput = ref("");

watch(repositories, (list) => {
  if (repoId.value === null && list.length) repoId.value = list[0]!.id;
}, { immediate: true });

const repoOptions = computed<SelectOption[]>(() =>
  repositories.value.map((r) => ({ value: String(r.id), label: r.full_name })),
);

// People paste the address bar; normalizeRepoInput reduces a github.com URL to the two
// words before it is judged.
const typedName = computed(() => normalizeRepoInput(repoInput.value));
const typedValid = computed(() => isFullName(typedName.value));
const repoReady = computed(() => (mode.value === "tracked" ? repoId.value !== null : typedValid.value));

/* ── the contributors ──────────────────────────────────────────────────────── */

let nextKey = 1;

function blankRow(): SubjectRow {
  nextKey += 1;
  return { key: nextKey, kind: "user", userId: null, login: "" };
}

const rows = ref<SubjectRow[]>([blankRow()]);

const peopleOptions = computed<SelectOption[]>(() => {
  const options: SelectOption[] = [];
  const seen = new Set<number>();
  const user = me.value;
  if (user) {
    seen.add(user.id);
    options.push({ value: String(user.id), label: `${user.first_name} ${user.last_name} (you)`.trim() });
  }
  for (const member of teammates.value ?? []) {
    if (seen.has(member.user_id)) continue;
    seen.add(member.user_id);
    options.push({ value: String(member.user_id), label: `${member.first_name} ${member.last_name}`.trim() || member.email });
  }
  return options;
});

const readyRows = computed(() => rows.value.filter(subjectReady));
const atSubjectCap = computed(() => rows.value.length >= MAX_SUBJECTS);

function addRow() {
  if (atSubjectCap.value) return;
  rows.value = [...rows.value, blankRow()];
}

function removeRow(key: number) {
  // Never below one row: an empty form with no rows at all offers nothing to fill in.
  if (rows.value.length <= 1) return;
  rows.value = rows.value.filter((row) => row.key !== key);
}

/* ── the range ─────────────────────────────────────────────────────────────── */

const rangeStart = ref(isoDaysAgo(30));
const rangeEnd = ref(isoDaysAgo(0));

const rangeError = computed(() => rangeProblem(rangeStart.value, rangeEnd.value));
const span = computed(() => spanDays(rangeStart.value, rangeEnd.value));
const atRangeCap = computed(() => span.value !== null && span.value === MAX_RANGE_DAYS);

/* ── the persona ───────────────────────────────────────────────────────────── */

const { data: personaPage, isError: personasFailed } = useQuery({
  queryKey: ["personas"],
  retry: false,
  queryFn: () => api.request<Page<PersonaResponse>>("/personas", { query: { limit: 100, offset: 0 } }),
});

const personas = computed(() => personaPage.value?.items ?? []);
// What the API would pick on its own: personas.resolve() takes the caller's default and
// falls back to the built-in Concise preset.
const defaultPersona = computed(
  () => personas.value.find((p) => p.is_default) ?? personas.value.find((p) => p.name === "Concise") ?? null,
);

// Null until touched, so the picker follows the default arriving rather than freezing an
// empty value in front of it.
const chosenPersonaId = ref<number | null>(null);
const persona = computed(
  () => personas.value.find((p) => p.id === chosenPersonaId.value) ?? defaultPersona.value,
);
const overridden = computed(
  () => persona.value !== null && defaultPersona.value !== null && persona.value.id !== defaultPersona.value.id,
);

const personaOptions = computed<SelectOption[]>(() =>
  personas.value.map((p) => ({
    value: String(p.id),
    label: p.is_default ? `${p.name} · your default` : isSystemPersona(p) ? `${p.name} · built in` : p.name,
  })),
);

/* ── generating ────────────────────────────────────────────────────────────── */

const failure = ref<AdhocFailure | null>(null);

// A failure names one of the two modes, so it stops being true the moment the mode changes.
watch(mode, () => { failure.value = null; });

// What is still missing, in the words of the section it is missing from. The range is
// deliberately absent: it states its own problem beside the two date fields, and saying
// it twice on one screen reads as two faults rather than one.
const problems = computed<string[]>(() => {
  const list: string[] = [];
  if (!repoReady.value) {
    list.push(mode.value === "tracked" ? "Choose a repository." : "Type a repository as owner/name.");
  }
  if (!readyRows.value.length) list.push("Add at least one contributor.");
  if (rangeError.value) list.push("Fix the dates above.");
  return list;
});

const generate = useMutation({
  mutationFn: () =>
    api.request<ReportResponse>("/reports/adhoc", {
      method: "POST",
      body: {
        ...(mode.value === "tracked" ? { repo_id: repoId.value } : { repo_full_name: typedName.value }),
        subjects: readyRows.value.map(subjectPayload),
        range_start: rangeStart.value,
        range_end: rangeEnd.value,
        ...(persona.value ? { persona_id: persona.value.id } : {}),
      },
    }),
  onSuccess: (created) => {
    failure.value = null;
    announce("Report generated");
    router.push(`/reports/${created.id}`);
  },
  onError: (err) => {
    // The form is untouched, deliberately. A failure after a minute of waiting must not
    // also cost the person everything they typed.
    failure.value = adhocFailure(err);
    announce("Report generation failed");
  },
});
</script>

<template>
  <PulseShell readout="custom report">
    <header class="sec">
      <NuxtLink
        to="/reports"
        :class="[FOCUS, TAP, '-ml-1 inline-flex items-center gap-1.5 rounded px-1 py-1 text-[12px] text-ink-muted transition-colors hover:text-ink']"
      >
        <Icon name="arrowLeft" class="h-3.5 w-3.5" />
        All reports
      </NuxtLink>
      <Eyebrow class="mt-4 block">Pulse · custom report</Eyebrow>
      <h1 class="mt-3 text-balance text-[clamp(1.5rem,2.2vw,1.9rem)] font-semibold leading-[1.05] tracking-[-0.035em]">
        New custom report
      </h1>
      <p class="mt-2.5 max-w-[68ch] text-[13px] leading-relaxed text-ink-muted">
        A weekly report covers your own work on one repository for one week. A custom report
        covers anyone you name, on any repository, over any dates you choose.
      </p>
      <p class="mt-2 max-w-[68ch] text-[13px] leading-relaxed text-ink-muted">
        Pick a repository, up to {{ MAX_SUBJECTS }} contributors and a window of at most
        {{ MAX_RANGE_DAYS }} days. Each contributor gets their own section, written from their
        own activity. The sections are never merged.
      </p>
    </header>

    <!-- ── repository ──────────────────────────────────────────────────────── -->
    <section class="sec mt-8" style="animation-delay: 40ms" aria-labelledby="repo-heading">
      <h2 id="repo-heading" class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">Repository</h2>

      <div class="mt-3 grid gap-3 sm:grid-cols-2">
        <label
          :class="[
            'flex cursor-pointer gap-3 rounded-md px-4 py-3.5 ring-1 ring-inset transition-colors',
            mode === 'tracked' ? 'bg-surface-active ring-line' : 'bg-surface/40 ring-line-subtle hover:ring-line',
          ]"
        >
          <input
            v-model="mode"
            type="radio"
            value="tracked"
            data-test="mode-tracked"
            name="adhoc-mode"
            :class="[FOCUS, 'mt-0.5 h-4 w-4 shrink-0']"
          >
          <span class="min-w-0">
            <span class="block text-[13px] font-medium text-ink">A repository Pulse tracks</span>
            <span class="mt-1 block text-[12px] leading-relaxed text-ink-muted">
              Read from data Pulse has already synced. Fast, and it covers only what the last sync
              picked up.
            </span>
          </span>
        </label>

        <label
          :class="[
            'flex cursor-pointer gap-3 rounded-md px-4 py-3.5 ring-1 ring-inset transition-colors',
            mode === 'live' ? 'bg-surface-active ring-line' : 'bg-surface/40 ring-line-subtle hover:ring-line',
          ]"
        >
          <input
            v-model="mode"
            type="radio"
            value="live"
            data-test="mode-live"
            name="adhoc-mode"
            :class="[FOCUS, 'mt-0.5 h-4 w-4 shrink-0']"
          >
          <span class="min-w-0">
            <span class="block text-[13px] font-medium text-ink">Any repository, by name</span>
            <span class="mt-1 block text-[12px] leading-relaxed text-ink-muted">
              Fetched from GitHub during the request, using your own connection. Slower, and a
              private repository needs your GitHub account connected.
            </span>
          </span>
        </label>
      </div>

      <div v-if="mode === 'tracked'" class="mt-4">
        <Select
          class="w-[320px]"
          label="Repository this report is about"
          placeholder="Choose a repository"
          data-test="repo-select"
          :disabled="!repositories.length"
          :model-value="repoId === null ? '' : String(repoId)"
          :options="repoOptions"
          @update:model-value="repoId = Number($event)"
        />
        <p v-if="reposPending" class="mt-2 text-[12px] text-ink-muted">Reading your repositories…</p>
        <p v-else-if="reposFailed" class="mt-2 text-[12px] text-ink-muted">
          The repository list did not come back. Naming a repository by hand still works.
        </p>
        <p v-else-if="!repositories.length" class="mt-2 max-w-[60ch] text-[12px] leading-relaxed text-ink-muted">
          Pulse tracks no repositories you can see. Name one by hand instead.
        </p>
      </div>

      <div v-else class="mt-4">
        <label for="repo-name" class="block text-[12px] text-ink-muted">Repository, as owner/name</label>
        <input
          id="repo-name"
          v-model="repoInput"
          type="text"
          data-test="repo-input"
          spellcheck="false"
          placeholder="cyphercrescent/pulse"
          :class="[FOCUS, 'mt-1.5 w-full max-w-[360px] rounded-md bg-sunken px-3 py-2 text-[12.5px] text-ink ring-1 ring-inset ring-line transition-colors placeholder:text-ink-faint hover:ring-line-strong']"
        >
        <p
          v-if="repoInput.trim() !== '' && !typedValid"
          data-test="repo-invalid"
          class="mt-1.5 max-w-[60ch] text-[12px] leading-relaxed text-warn"
        >
          That is not a repository name. It has to be the owner and the repository separated by one
          slash, like cyphercrescent/pulse.
        </p>
        <p v-else-if="typedValid && typedName !== repoInput.trim()" class="mono mt-1.5 text-[12px] text-ink-muted">
          reading that as {{ typedName }}
        </p>
      </div>
    </section>

    <!-- ── contributors ────────────────────────────────────────────────────── -->
    <section class="sec mt-8" style="animation-delay: 60ms" aria-labelledby="people-heading">
      <div class="flex flex-wrap items-baseline justify-between gap-3 border-b border-line-subtle pb-2">
        <h2 id="people-heading" class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">Contributors</h2>
        <p class="mono text-[12px] text-ink-muted" data-test="subject-count">
          {{ readyRows.length }} of {{ MAX_SUBJECTS }}
        </p>
      </div>

      <p class="mt-3 max-w-[74ch] text-[12.5px] leading-relaxed text-ink-muted">
        Someone with a Pulse account is picked from the list. Someone without one — an outside
        collaborator, a contractor — is named by their GitHub login instead.
      </p>

      <ul data-test="subjects" class="mt-3 divide-y divide-line-subtle">
        <li v-for="row in rows" :key="row.key" data-test="subject-row" class="flex flex-wrap items-end gap-3 py-3">
          <div>
            <p :class="[MONO_LABEL, 'mb-1.5 text-ink-faint']">Kind</p>
            <Select
              class="w-[190px]"
              label="Whether this contributor has a Pulse account"
              :model-value="row.kind"
              :options="[
                { value: 'user', label: 'A Pulse user' },
                { value: 'github', label: 'A GitHub login' },
              ]"
              @update:model-value="row.kind = $event as 'user' | 'github'"
            />
          </div>

          <div v-if="row.kind === 'user'">
            <p :class="[MONO_LABEL, 'mb-1.5 text-ink-faint']">Person</p>
            <Select
              class="w-[260px]"
              label="Which person this section is about"
              placeholder="Choose a person"
              data-test="subject-user"
              :disabled="!peopleOptions.length"
              :model-value="row.userId === null ? '' : String(row.userId)"
              :options="peopleOptions"
              @update:model-value="row.userId = Number($event)"
            />
          </div>

          <div v-else>
            <!-- A real <label for>, not a paragraph above an aria-label. The two used to
                 say different things, and only the invisible one reached a screen reader. -->
            <label :for="`subject-login-${row.key}`" :class="[MONO_LABEL, 'mb-1.5 block text-ink-faint']">
              GitHub login
            </label>
            <input
              :id="`subject-login-${row.key}`"
              v-model="row.login"
              type="text"
              data-test="subject-login"
              spellcheck="false"
              autocomplete="off"
              placeholder="octocat"
              :class="[FOCUS, 'w-[260px] rounded-md bg-sunken px-3 py-2 text-[12.5px] text-ink ring-1 ring-inset ring-line transition-colors placeholder:text-ink-faint hover:ring-line-strong']"
            >
          </div>

          <p v-if="row.kind === 'github' && row.login.trim() !== '' && !isGithubLogin(row.login)" class="pb-2 text-[12px] text-warn">
            That is not a GitHub login.
          </p>

          <button
            type="button"
            data-test="subject-remove"
            :disabled="rows.length <= 1"
            :class="[FOCUS, DISABLED, 'ml-auto rounded px-2 py-1.5 text-[12px] text-ink-muted ring-1 ring-inset ring-line-subtle transition-colors enabled:hover:bg-surface-hover enabled:hover:text-ink']"
            @click="removeRow(row.key)"
          >Remove</button>
        </li>
      </ul>

      <div class="mt-3 flex flex-wrap items-center gap-3">
        <Btn size="sm" variant="secondary" data-test="subject-add" :disabled="atSubjectCap" @click="addRow">
          Add a contributor
        </Btn>
        <p v-if="atSubjectCap" data-test="subject-cap" class="max-w-[52ch] text-[12px] leading-relaxed text-ink-muted">
          {{ MAX_SUBJECTS }} is the most one report covers. One request is one model call per
          person, so the cap is what keeps a single report from costing a day's allowance.
        </p>
      </div>
    </section>

    <!-- ── range ───────────────────────────────────────────────────────────── -->
    <section class="sec mt-8" style="animation-delay: 80ms" aria-labelledby="range-heading">
      <h2 id="range-heading" class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">Dates</h2>

      <div class="mt-3 flex flex-wrap items-end gap-3">
        <div>
          <label for="range-start" :class="[MONO_LABEL, 'mb-1.5 block text-ink-faint']">From</label>
          <input
            id="range-start"
            v-model="rangeStart"
            type="date"
            data-test="range-start"
            :class="[FOCUS, 'w-[180px] rounded-md bg-sunken px-3 py-2 text-[12.5px] text-ink ring-1 ring-inset ring-line transition-colors hover:ring-line-strong']"
          >
        </div>
        <div>
          <label for="range-end" :class="[MONO_LABEL, 'mb-1.5 block text-ink-faint']">To</label>
          <input
            id="range-end"
            v-model="rangeEnd"
            type="date"
            data-test="range-end"
            :class="[FOCUS, 'w-[180px] rounded-md bg-sunken px-3 py-2 text-[12.5px] text-ink ring-1 ring-inset ring-line transition-colors hover:ring-line-strong']"
          >
        </div>
        <p v-if="span !== null && !rangeError" class="mono pb-2 text-[12px] text-ink-muted" data-test="range-span">
          {{ span }} days
          <span v-if="atRangeCap"> · the longest a report covers</span>
        </p>
      </div>

      <p
        v-if="rangeError"
        data-test="range-error"
        class="mt-2 max-w-[70ch] rounded-md bg-warn-surface px-3.5 py-2.5 text-[12.5px] leading-relaxed text-ink"
      >
        {{ rangeError }}
      </p>
    </section>

    <!-- ── persona ─────────────────────────────────────────────────────────── -->
    <section class="sec mt-8" style="animation-delay: 100ms" aria-labelledby="persona-heading">
      <h2 id="persona-heading" class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">Wording</h2>

      <div class="mt-3 flex flex-wrap items-end gap-3">
        <div>
          <p :class="[MONO_LABEL, 'mb-1.5 text-ink-faint']">Persona</p>
          <Select
            class="w-[300px]"
            label="Which persona writes this report"
            placeholder="Choose a persona"
            data-test="persona-select"
            :disabled="!personas.length"
            :model-value="persona === null ? '' : String(persona.id)"
            :options="personaOptions"
            @update:model-value="chosenPersonaId = Number($event)"
          />
        </div>
        <p v-if="persona" class="max-w-[52ch] pb-1 text-[12.5px] leading-relaxed text-ink-muted" data-test="persona-preview">
          {{ personaPreview(persona) }}
        </p>
      </div>

      <p
        data-test="persona-scope-note"
        class="mt-3 max-w-[74ch] rounded-md bg-sunken px-3.5 py-2.5 text-[12.5px] leading-relaxed text-ink-muted ring-1 ring-inset ring-line-subtle"
      >
        <template v-if="overridden">
          This choice applies to this report only. Your default is still
          <span class="text-ink">{{ defaultPersona?.name }}</span>, and it stays that way until you
          change it in <NuxtLink to="/settings" :class="[FOCUS, 'rounded text-ink underline underline-offset-2']">Settings</NuxtLink>.
        </template>
        <template v-else-if="defaultPersona">
          Pre-filled with your default, <span class="text-ink">{{ defaultPersona.name }}</span>.
          Changing it here only affects this report — your default is set in
          <NuxtLink to="/settings" :class="[FOCUS, 'rounded text-ink underline underline-offset-2']">Settings</NuxtLink>.
        </template>
        <template v-else-if="personasFailed">
          Your personas could not be read, so this report will be written with whatever the API
          resolves on its own.
        </template>
      </p>
    </section>

    <!-- ── generate ────────────────────────────────────────────────────────── -->
    <section class="sec mt-8 border-t border-line-subtle pt-6" style="animation-delay: 120ms">
      <div class="flex flex-wrap items-center gap-3">
        <Btn
          data-test="generate"
          :disabled="problems.length > 0"
          :busy="generate.isPending.value"
          @click="generate.mutate()"
        >Generate report</Btn>
        <p class="mono text-[12px] text-ink-faint">up to {{ MAX_ADHOC_PER_HOUR }} an hour</p>
      </div>

      <ul v-if="problems.length" data-test="problems" class="mt-3 space-y-1">
        <li v-for="problem in problems" :key="problem" class="text-[12px] leading-relaxed text-ink-muted">
          {{ problem }}
        </li>
      </ul>

      <p
        v-if="generate.isPending.value"
        data-test="waiting"
        aria-live="polite"
        class="mt-4 max-w-[70ch] rounded-md bg-info-surface px-3.5 py-2.5 text-[12.5px] leading-relaxed text-ink"
      >
        Working. Pulse is reading
        <template v-if="mode === 'live'">GitHub</template><template v-else>its synced copy of the repository</template>
        and then writing one section per contributor, so this takes a while — often a minute or
        more. Leaving this page cancels nothing, but you will lose the form.
      </p>

      <div
        v-else-if="failure"
        role="alert"
        data-test="failure"
        class="mt-4 max-w-[74ch] rounded-md bg-bad-surface px-4 py-3"
      >
        <p class="text-[12.5px] leading-relaxed text-ink">{{ failure.message }}</p>
        <p class="mt-2 text-[12px] leading-relaxed text-ink-muted">
          Nothing was saved and nothing above was cleared — the form is exactly as you left it.
        </p>
        <NuxtLink v-if="failure.connectGitHub" to="/sync" class="mt-3 inline-flex" data-test="connect-github">
          <Btn size="sm" variant="secondary">Connect your GitHub account</Btn>
        </NuxtLink>
      </div>
    </section>
  </PulseShell>
</template>
