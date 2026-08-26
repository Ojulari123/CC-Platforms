<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import type { ActivityResponse, Page, ReportResponse } from "~/types/api";

definePageMeta({ middleware: "auth" });

/* Both buttons create the report immediately: the fields are editable from the moment
   you choose because the draft already exists. Pressing the button is the write. */

const WEEKS_OFFERED = 8;

const api = useApi();
const route = useRoute();
const router = useRouter();
const queryClient = useQueryClient();
const announce = useAnnounce();
const { show: showToast } = useToast();
const { repositories, repoName } = useRepositories();

const { me, unavailable: meUnavailable, retry: retryMe } = useMe();
const weeks = computed(() => recentWeeks(WEEKS_OFFERED));

const repoId = computed({
  get: () => (route.query.repo ? Number(route.query.repo) : null),
  set: (value) => patchQuery({ repo: value === null ? undefined : String(value) }),
});

// The API snaps week_start to the Monday itself; showing the canonical week means the
// picker and the record never disagree.
const week = computed({
  get: () => {
    const raw = typeof route.query.week === "string" ? route.query.week : null;
    return raw ? mondayOf(new Date(`${raw}T00:00:00`)) : (weeks.value[0] ?? mondayOf(new Date()));
  },
  set: (value) => patchQuery({ week: value }),
});

function patchQuery(patch: Record<string, string | undefined>) {
  router.replace({ query: { ...route.query, ...patch } });
}

// Your own reports for this repository, which is the only set the unique constraint
// cares about: uq_report_author_repo_week is (author, repo, week).
const { data: myReports } = useQuery({
  queryKey: computed(() => ["reports", "for-repo", me.value?.id ?? "anon", repoId.value ?? "none"]),
  enabled: computed(() => me.value !== null && repoId.value !== null),
  queryFn: () =>
    api.request<Page<ReportResponse>>("/reports", {
      query: { author_user_id: me.value?.id, repo_id: repoId.value, limit: 100, offset: 0 },
    }),
});

const duplicate = computed(() =>
  duplicateReport(myReports.value?.items ?? [], repoId.value, week.value, me.value?.id ?? null),
);
const freeWeek = computed(() =>
  firstFreeWeek(weeks.value, myReports.value?.items ?? [], repoId.value, me.value?.id ?? null),
);

const {
  data: activity,
  isPending: countsPending,
  isError: countsFailed,
} = useQuery({
  queryKey: computed(() => ["activity", "new-report", repoId.value ?? "none", week.value]),
  enabled: computed(() => repoId.value !== null),
  retry: false,
  queryFn: () =>
    api.request<ActivityResponse>("/activity/me", {
      query: { since: week.value, repo_id: repoId.value },
    }),
});

const working = ref<"generate" | "blank" | null>(null);
const errorMessage = ref<string | null>(null);
const report = ref<ReportResponse | null>(null);
const fields = reactive({ summary_manager: "", summary_exec: "", next_week_goals: "" });

const create = useMutation({
  mutationFn: (mode: "generate" | "blank") =>
    api.request<ReportResponse>(mode === "generate" ? "/reports/generate" : "/reports", {
      method: "POST",
      body: { repo_id: repoId.value, week_start: week.value },
    }),
  onSuccess: (created) => {
    working.value = null;
    report.value = created;
    fields.summary_manager = created.summary_manager ?? "";
    fields.summary_exec = created.summary_exec ?? "";
    fields.next_week_goals = created.next_week_goals ?? "";
    queryClient.invalidateQueries({ queryKey: ["reports"] });
    announce(
      created.generated_at
        ? `Draft ${created.id} written from your synced activity`
        : `Blank draft ${created.id} created`,
    );
  },
  onError: (err, mode) => {
    working.value = null;
    const code = httpStatus(err);
    errorMessage.value =
      code === 409
        ? "409 · you already have a report for this repository and week. The constraint is per person, per repository, per week."
        : code === 422
          ? "422 · nothing of yours is synced for that week, so there is nothing to draft from. A blank draft is still allowed."
          : code === 403
            ? "403 · you have no synced activity in this repository, so you cannot report on it."
            : code === 429
              /* The daily AI allowance arrives as a FastAPI `detail` and is the server's
                 own wording, which says who is paying and when it resets. The ten-an-hour
                 limit is slowapi's and carries no `detail`, so it lands on the fallback. */
              ? apiMessage(err, "429 · that is ten generated drafts in an hour, which is the limit. A blank draft still works.")
              : code === 502
                ? "502 · the model is unavailable right now. A blank draft still works."
                : apiMessage(err, `Could not ${mode === "generate" ? "draft" : "create"} the report.`);
  },
});

function start(mode: "generate" | "blank") {
  errorMessage.value = null;
  if (repoId.value === null) {
    errorMessage.value = "Pick a repository first.";
    return;
  }
  working.value = mode;
  create.mutate(mode);
}

const save = useMutation({
  mutationFn: () =>
    api.request<ReportResponse>(`/reports/${report.value!.id}`, {
      method: "PATCH",
      body: {
        summary_manager: fields.summary_manager.trim() || null,
        summary_exec: fields.summary_exec.trim() || null,
        next_week_goals: fields.next_week_goals.trim() || null,
      },
    }),
  onSuccess: (updated) => {
    report.value = updated;
    queryClient.invalidateQueries({ queryKey: ["reports"] });
    showToast(`Draft #${updated.id} saved.`, "muted");
  },
  onError: (err) => {
    errorMessage.value = apiMessage(err, "Could not save that draft.");
  },
});

const submit = useMutation({
  mutationFn: async () => {
    await save.mutateAsync();
    return api.request<ReportResponse>(`/reports/${report.value!.id}/submit`, { method: "POST" });
  },
  onSuccess: (updated) => {
    queryClient.invalidateQueries({ queryKey: ["reports"] });
    showToast(`Report #${updated.id} submitted for review.`, "ok");
    navigateTo(`/reports/${updated.id}`);
  },
  onError: (err) => {
    errorMessage.value =
      httpStatus(err) === 422
        ? "422 · all three fields are empty, so there is nothing to submit."
        : apiMessage(err, "Could not submit this report.");
  },
});

const allEmpty = computed(() =>
  [fields.summary_manager, fields.summary_exec, fields.next_week_goals].every(
    (value) => value.trim() === "",
  ),
);

const repo = computed(() => repositories.value.find((r) => r.id === repoId.value) ?? null);

// Named rather than described: who a submitted report actually lands on. You are
// dropped even when you hold the post — a lead cannot decide their own report.
const approverPhrase = computed(() => {
  const r = repo.value;
  if (!r) return "whoever is named on the repository";
  const names = [
    r.lead_user_id !== null && r.lead_user_id !== me.value?.id
      ? personName(r.lead, r.lead_user_id)
      : null,
    r.deputy_user_id !== null && r.deputy_user_id !== me.value?.id
      ? personName(r.deputy, r.deputy_user_id)
      : null,
  ].filter((n): n is string => n !== null);
  return names.length
    ? names.join(" or ")
    : "whoever else can decide it — nobody but you is named on this repository yet";
});

function reset() {
  report.value = null;
  errorMessage.value = null;
  fields.summary_manager = "";
  fields.summary_exec = "";
  fields.next_week_goals = "";
}
</script>

<template>
  <PulseShell :readout="report ? `draft ${report.id}` : 'new report'">
    <header class="sec">
      <NuxtLink
        to="/reports"
        :class="[FOCUS, TAP, '-ml-1 inline-flex items-center gap-1.5 rounded px-1 py-1 text-[12px] text-ink-muted transition-colors hover:text-ink']"
      >
        <Icon name="arrowLeft" class="h-3.5 w-3.5" />
        All reports
      </NuxtLink>
      <div class="mt-3 flex flex-wrap items-end justify-between gap-4">
        <div class="min-w-0">
          <Eyebrow>Pulse · new report</Eyebrow>
          <h1 class="mt-3 text-[clamp(1.5rem,2.2vw,1.9rem)] font-semibold leading-[1.05] tracking-[-0.035em]">
            Write a weekly report
          </h1>
          <p class="mt-1.5 max-w-[72ch] text-[12.5px] leading-relaxed text-ink-muted">
            One per person, per repository, per week. Pulse can draft it from the work it already
            synced for you, or hand you three empty fields — either way the report exists from the
            moment you choose, and everything after that is an edit.
          </p>
        </div>
        <p class="mono flex shrink-0 items-center gap-2 rounded-md bg-sunken px-2.5 py-2 text-[12px] ring-1 ring-inset ring-line-subtle">
          <span :class="[MONO_LABEL, 'text-ink-faint']">post</span>
          <span class="text-ink">/reports/generate</span>
        </p>
      </div>
    </header>

    <!-- Without an id from identity the duplicate check cannot be made, and offering the
         two write buttons anyway means finding out with a 409. -->
    <div v-if="meUnavailable" role="alert" class="sec mt-8 rounded-md bg-bad-surface px-5 py-6">
      <p class="text-[13.5px] font-medium text-ink">Your account could not be read</p>
      <p class="mt-1.5 max-w-[62ch] text-[12.5px] leading-relaxed text-ink-muted">
        Pulse asks identity who you are, and that request did not answer. Without your id it
        cannot tell whether you already have a report for this repository and week, so it will
        not offer to write a second one.
      </p>
      <div class="mt-4 flex">
        <Btn size="sm" variant="secondary" @click="retryMe">Try again</Btn>
      </div>
    </div>

    <NewReportForm
      v-else-if="!report"
      class="mt-8"
      :repositories="repositories"
      :repo-id="repoId"
      :week="week"
      :weeks="weeks"
      :duplicate="duplicate"
      :free-week="freeWeek"
      :counts="activity?.counts ?? null"
      :counts-pending="repoId !== null && countsPending"
      :counts-failed="countsFailed"
      :working="working"
      :error-message="errorMessage"
      @update:repo-id="repoId = $event"
      @update:week="week = $event"
      @create="start"
    />

    <!-- The draft, editable where it stands. -->
    <section v-else class="sec mt-8 border-t border-line-subtle pt-6" aria-labelledby="draft-heading">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div class="min-w-0">
          <Eyebrow>Draft created</Eyebrow>
          <h2 id="draft-heading" class="mt-2 flex flex-wrap items-center gap-x-2.5 gap-y-1.5 text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">
            <span class="mono">#{{ report.id }}</span>
            <span class="text-[13px] font-normal text-ink-muted">{{ reportRepoLabel(report, repoName) }} · {{ formatDate(report.week_start) }}</span>
            <span :class="['inline-flex items-center rounded px-2 py-1 text-[12px] font-normal', statusClass(report.status)]">{{ statusLabel(report.status) }}</span>
          </h2>
          <p class="mono mt-2 text-[12px] text-ink-muted">
            <template v-if="report.generated_at">
              generated_at {{ report.generated_at }} · prompt_version {{ report.prompt_version ?? "none" }}
            </template>
            <template v-else>written by hand · summaries are null until you save</template>
          </p>
        </div>
        <div class="flex gap-2">
          <NuxtLink :to="`/reports/${report.id}`"><Btn size="sm" variant="secondary">Open the report</Btn></NuxtLink>
          <Btn size="sm" variant="ghost" @click="reset">Start another</Btn>
        </div>
      </div>

      <div class="mt-6 space-y-5">
        <div v-for="field in REPORT_FIELDS" :key="field.key" class="border-t border-line-subtle pt-3.5">
          <div class="flex flex-wrap items-center gap-2.5">
            <label :for="`new-${field.key}`" class="text-[13px] font-medium tracking-tight text-ink">
              {{ field.label }}
            </label>
            <span class="mono text-[12px] text-ink-faint">{{ field.api }}</span>
            <span class="mono ml-auto text-[12px] text-ink-muted">
              {{ fields[field.key].trim().length }} characters
            </span>
          </div>
          <textarea
            :id="`new-${field.key}`"
            v-model="fields[field.key]"
            :rows="field.key === 'summary_manager' ? 7 : 4"
            :class="[FOCUS, 'mt-2 w-full resize-y rounded-md bg-sunken px-3 py-2.5 text-[12.5px] leading-relaxed text-ink ring-1 ring-inset ring-line transition-colors placeholder:text-ink-faint hover:ring-line-strong']"
          />
        </div>
      </div>

      <p v-if="report.generated_at" class="mt-4 max-w-[86ch] text-[12.5px] leading-relaxed text-ink-muted">
        Written by a model from the week's items, and wrong in the ordinary ways a summary is
        wrong: it can flatten two unrelated pieces of work into one sentence, and it cannot know
        what you were blocked on. Edit it before it goes anywhere — it is your report, not the
        model's.
      </p>

      <div class="mt-6 flex flex-wrap items-center gap-2 border-t border-line-subtle pt-5">
        <Btn :disabled="allEmpty" :busy="submit.isPending.value" @click="submit.mutate()">
          Submit for review
        </Btn>
        <Btn variant="secondary" :busy="save.isPending.value" @click="save.mutate()">Save draft</Btn>
        <p class="mono ml-auto text-[12px] text-ink-muted">
          patch /reports/{{ report.id }} · post /reports/{{ report.id }}/submit
        </p>
      </div>

      <p v-if="errorMessage" role="alert" class="mt-3 max-w-[80ch] text-[12.5px] leading-relaxed text-bad">
        {{ errorMessage }}
      </p>

      <p v-else-if="allEmpty" class="mt-3 max-w-[80ch] text-[12.5px] leading-relaxed text-ink-muted">
        All three fields are empty, so there is nothing to submit — the endpoint answers
        <span class="mono text-[12px] text-ink">422</span> rather than putting a blank page in
        somebody's queue. Saving it as a draft is fine; a draft is only ever visible to you.
      </p>

      <div class="mt-5 rounded-md bg-sunken/60 px-4 py-3.5 ring-1 ring-inset ring-line-subtle">
        <Eyebrow>Who decides it</Eyebrow>
        <p class="mt-2 max-w-[80ch] text-[12.5px] leading-relaxed text-ink-muted">
          Not you. Submitting hands it to {{ approverPhrase }}<template v-if="repo?.dept_id === null">. No department admin inherits it either, since the report carries no department for one to inherit it through</template><template v-else>, or an admin of the department it is filed to</template>. The API
          refuses your own decision on your own report with a
          <span class="mono text-[12px] text-ink">403</span>, whatever your role is.
        </p>
      </div>
    </section>
  </PulseShell>
</template>
