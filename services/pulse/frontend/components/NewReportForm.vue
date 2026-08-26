<script setup lang="ts">
import { computed } from "vue";
import Btn from "@crescent/ui/components/Btn.vue";
import Icon from "@crescent/ui/components/Icon.vue";
import Select from "@crescent/ui/components/Select.vue";
import { FOCUS, MONO_LABEL } from "@crescent/ui/utils/ui";
import type { SelectOption } from "@crescent/ui/types/ui";
import type { ActivityCounts, ReportResponse, RepositoryResponse } from "~/types/api";
import { formatDate, statusLabel } from "~/utils/format";
import { repoWarnings } from "~/utils/pulse";

/* Choosing the subject of a report, and the two buttons that create it.

   Every repository is offered. `_may_report_on` gates on your synced activity, not on
   filing or tracking, so an unfiled or untracked repository is a warning next to an
   enabled option — never an exclusion. Blocking the write would turn an admin's filing
   backlog into an engineer's blocked week. */
const props = withDefaults(
  defineProps<{
    repositories: RepositoryResponse[];
    repoId: number | null;
    week: string;
    weeks: string[];
    /** Your own report for this repo and week, if one exists. */
    duplicate?: ReportResponse | null;
    /** The first week with no report of yours for this repo, when there is one. */
    freeWeek?: string | null;
    counts?: ActivityCounts | null;
    countsPending?: boolean;
    countsFailed?: boolean;
    working?: "generate" | "blank" | null;
    errorMessage?: string | null;
  }>(),
  {
    duplicate: null,
    freeWeek: null,
    counts: null,
    countsPending: false,
    countsFailed: false,
    working: null,
    errorMessage: null,
  },
);

const emit = defineEmits<{
  "update:repoId": [value: number | null];
  "update:week": [value: string];
  create: [mode: "generate" | "blank"];
}>();

const repo = computed(() => props.repositories.find((r) => r.id === props.repoId) ?? null);
const warnings = computed(() => repoWarnings(repo.value));
const repoName = computed(() => repo.value?.full_name ?? `repo_id ${props.repoId} · unresolved`);

const repoOptions = computed<SelectOption[]>(() =>
  props.repositories.map((r) => ({ value: String(r.id), label: r.full_name })),
);

const weekOptions = computed<SelectOption[]>(() =>
  props.weeks.map((w, i) => ({ value: w, label: `${formatDate(w)}${i === 0 ? " · this week" : ""}` })),
);

const COUNT_META = [
  { key: "commits", label: "Commits" },
  { key: "pull_requests", label: "Pull requests" },
  { key: "reviews", label: "Reviews" },
  { key: "issues", label: "Issues" },
] as const;

const total = computed(() => {
  const c = props.counts;
  return c ? c.commits + c.pull_requests + c.reviews + c.issues : 0;
});

// Generation answers 422 rather than writing a week that did not happen, so the button
// that would ask for it is the only one this disables. Blank stays open.
const nothingSynced = computed(() => !props.countsPending && !props.countsFailed && total.value === 0);
const blocked = computed(() => props.duplicate !== null || props.working !== null);
</script>

<template>
  <div>
    <section aria-labelledby="subject-heading" class="sec border-t border-line-subtle pt-6">
      <h2 id="subject-heading" class="text-[13px] font-medium tracking-tight text-ink">Subject</h2>

      <div class="mt-3 flex flex-wrap items-end gap-3">
        <div>
          <p :class="[MONO_LABEL, 'mb-1.5 text-ink-faint']">Repository</p>
          <Select
            label="Repository this report is about"
            class="w-[280px]"
            :model-value="repoId === null ? '' : String(repoId)"
            :options="repoOptions"
            placeholder="Choose a repository"
            @update:model-value="emit('update:repoId', Number($event))"
          />
        </div>
        <div>
          <p :class="[MONO_LABEL, 'mb-1.5 text-ink-faint']">Week beginning</p>
          <Select
            label="Week this report covers"
            class="w-[220px]"
            :model-value="week"
            :options="weekOptions"
            @update:model-value="emit('update:week', $event)"
          />
        </div>
        <p class="mono pb-2 text-[12px] text-ink-muted">
          repo_id {{ repoId ?? "—" }} · week_start {{ week }} · dept_id
          {{ repo?.dept_id ?? "null (unfiled)" }}
        </p>
      </div>

      <!-- Filed to nothing: allowed, and what it costs is the review queue. -->
      <div
        v-if="warnings.unfiled"
        data-test="unfiled-warning"
        class="mt-4 flex flex-wrap items-start gap-3 rounded-md bg-warn-surface px-4 py-3"
      >
        <span class="mt-0.5 shrink-0 text-warn"><Icon name="alert" /></span>
        <p class="min-w-0 flex-1 text-[12.5px] leading-relaxed text-ink">
          <span class="font-medium">
            {{ repoName }} is filed under no department, so a report about it reaches no review queue.
          </span>
          <span class="text-ink-muted">
            You can still write it — nothing here refuses you. It is stamped
            <span class="mono text-[12px] text-ink">dept_id null</span>, and a department admin
            only inherits the right to decide a report through the department it carries, so none
            of them inherits this one.
            <template v-if="warnings.unnamed">
              Nobody is named lead or deputy on the repository either, which leaves a platform
              admin as the only person who could decide it.
            </template>
            File it under a department on
            <NuxtLink to="/repositories" :class="[FOCUS, 'rounded underline underline-offset-2 hover:text-ink']">
              Repositories
            </NuxtLink>
            first if you would rather it were reviewable.
          </span>
        </p>
      </div>

      <p
        v-if="warnings.untracked"
        data-test="untracked-warning"
        class="mt-4 max-w-[86ch] text-[12.5px] leading-relaxed text-ink-muted"
      >
        The sync no longer visits {{ repoName }}, so the week you would be summarising is not
        being filled in. Reporting on it is still allowed; what is there is whatever was synced
        before tracking was turned off.
      </p>
    </section>

    <!-- The duplicate the API would refuse. Per person, per repo, per week. -->
    <div v-if="duplicate" role="alert" data-test="duplicate-warning" class="sec mt-6 rounded-md bg-warn-surface px-4 py-4">
      <div class="flex flex-wrap items-start gap-3">
        <span class="mt-0.5 shrink-0 text-warn"><Icon name="alert" /></span>
        <div class="min-w-0 flex-1">
          <p class="text-[13px] font-medium text-ink">
            You already have a report for {{ repoName }}, week of {{ formatDate(week) }}
          </p>
          <p class="mt-1.5 max-w-[76ch] text-[12.5px] leading-relaxed text-ink-muted">
            It is <span class="mono text-[12px] text-ink">#{{ duplicate.id }}</span
            >, and it is <span class="lowercase">{{ statusLabel(duplicate.status) }}</span
            >. The constraint
            <span class="mono text-[12px] text-ink">uq_report_author_repo_week</span> is on the
            three of them together — author, repository, week — so somebody else can still write
            their own about this week. Both endpoints would answer
            <span class="mono text-[12px] text-ink">409</span> here. Edit the one that exists
            instead of starting a second.
          </p>
          <div class="mt-3 flex flex-wrap items-center gap-2">
            <NuxtLink :to="`/reports/${duplicate.id}`">
              <Btn size="sm">Open report #{{ duplicate.id }}</Btn>
            </NuxtLink>
            <Btn
              v-if="freeWeek"
              size="sm"
              variant="ghost"
              @click="emit('update:week', freeWeek)"
            >
              Jump to the week of {{ formatDate(freeWeek) }}
            </Btn>
            <p v-else class="text-[12px] leading-relaxed text-ink-muted">
              Every week on offer already has one of yours for this repository, so there is no
              free week to move to. Choose another repository.
            </p>
          </div>
        </div>
      </div>
    </div>

    <!-- What a draft would be written from. -->
    <section v-if="!duplicate" aria-labelledby="material-heading" class="sec mt-6">
      <div class="flex flex-wrap items-end justify-between gap-3">
        <h2 id="material-heading" class="text-[13px] font-medium tracking-tight text-ink">
          What a draft would be written from
        </h2>
        <p class="mono text-[12px] text-ink-muted">your work only · week of {{ week }}</p>
      </div>

      <div class="mt-3 grid grid-cols-2 gap-3 md:grid-cols-4">
        <div
          v-for="meta in COUNT_META"
          :key="meta.key"
          class="rounded-md bg-surface/40 px-4 py-3.5 ring-1 ring-inset ring-line-subtle"
        >
          <p :class="[MONO_LABEL, 'text-ink-faint']">{{ meta.label }}</p>
          <p class="mono mt-2 text-[22px] leading-none tracking-tight text-ink">
            <template v-if="countsPending">
              <span class="inline-block h-[18px] w-8 animate-pulse rounded bg-surface" />
            </template>
            <template v-else-if="countsFailed || !counts">—</template>
            <template v-else>{{ counts[meta.key] }}</template>
          </p>
        </div>
      </div>

      <p v-if="countsFailed" role="alert" class="mt-3 max-w-[86ch] text-[12.5px] leading-relaxed text-bad">
        The week's activity is a separate request and it did not come back, so the figures above
        are missing rather than zero. Drafting from synced activity is still allowed — the server
        reads the week again for itself.
      </p>

      <div
        v-else-if="nothingSynced"
        class="mt-4 flex flex-wrap items-start gap-3 rounded-md bg-warn-surface px-4 py-3"
      >
        <span class="mt-0.5 shrink-0 text-warn"><Icon name="alert" /></span>
        <p class="min-w-0 flex-1 text-[12.5px] leading-relaxed text-ink">
          <span class="font-medium">
            Nothing of yours is synced for this week, so there is nothing to draft from.
          </span>
          <span class="text-ink-muted">
            Generation answers <span class="mono text-[12px] text-ink">422</span> rather than
            writing a week that did not happen. Either the week really was quiet, or the sync has
            not reached it — the
            <NuxtLink to="/sync" :class="[FOCUS, 'rounded underline underline-offset-2 hover:text-ink']">
              run history
            </NuxtLink>
            will say which. A blank draft is still yours to write.
          </span>
        </p>
      </div>

      <p v-else-if="!countsPending" class="mt-3 max-w-[86ch] text-[12.5px] leading-relaxed text-ink-muted">
        {{ total }} items, all of them yours — generation filters on
        <span class="mono text-[12px]">author_user_id</span>, so a busy week for the rest of the
        repository counts for nothing here. The model is handed the items themselves, capped at
        fifty of each kind, and the counts stay exact even when the list sent is trimmed.
      </p>

      <div class="mt-5 flex flex-wrap items-center gap-2">
        <Btn
          data-test="create-generate"
          :disabled="blocked || repoId === null || nothingSynced"
          :busy="working === 'generate'"
          @click="emit('create', 'generate')"
        >
          {{ working === "generate" ? "Reading the week" : "Draft from synced activity" }}
        </Btn>
        <Btn
          data-test="create-blank"
          variant="secondary"
          :disabled="blocked || repoId === null"
          :busy="working === 'blank'"
          @click="emit('create', 'blank')"
        >
          {{ working === "blank" ? "Creating" : "Start blank" }}
        </Btn>
        <p class="mono ml-auto text-[12px] text-ink-muted">post /reports/generate · post /reports</p>
      </div>

      <p v-if="errorMessage" role="alert" class="mt-3 max-w-[86ch] text-[12.5px] leading-relaxed text-bad">
        {{ errorMessage }}
      </p>

      <p class="mt-3 max-w-[86ch] text-[12.5px] leading-relaxed text-ink-muted">
        Generation is limited to ten an hour and it is not free — each run is a model call,
        recorded against your account. It creates the report as a draft, so pressing it is
        already the write.
      </p>
    </section>
  </div>
</template>
