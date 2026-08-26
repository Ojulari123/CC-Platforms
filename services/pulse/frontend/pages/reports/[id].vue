<script setup lang="ts">
import type { ComponentPublicInstance } from "vue";
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import type { Decision } from "~/components/ReportDecision.vue";
import type {
  ActivityResponse,
  ApprovalResponse,
  CommentResponse,
  Page,
  PersonaResponse,
  ReportResponse,
  UserMeResponse,
} from "~/types/api";

definePageMeta({ middleware: "auth" });

/* One report, its evidence and its history. The evidence sits beside the claim rather
   than behind a link: reading the claim and checking it is one movement. */

const route = useRoute();
const auth = useAuth();
const api = useApi();
const config = useRuntimeConfig();
const queryClient = useQueryClient();
const announce = useAnnounce();
const { show: showToast } = useToast();
const { repositories, repoName } = useRepositories();

const id = computed(() => String(route.params.id));

const { data: report, isPending, isError, error } = useQuery({
  queryKey: computed(() => ["report", id.value]),
  queryFn: () => api.request<ReportResponse>(`/reports/${id.value}`),
  retry: false,
});

const me = computed(() => auth.user.value as UserMeResponse | null);
const repo = computed(() =>
  repositories.value.find((r) => report.value?.repo_id !== null && r.id === report.value?.repo_id) ?? null,
);

/* A custom report is a different document wearing the same row: any range rather than a
   week, possibly a repository Pulse has never synced, and one attributed section per
   contributor rather than one summary. */
const adhoc = computed(() => isAdhoc(report.value));
const sections = computed(() => orderedSubjects(report.value));
const repoLabel = computed(() => (report.value ? reportRepoLabel(report.value, repoName) : ""));

// summary_manager on a custom report is the sections above, joined, so offering it as a
// fourth editable box would be offering the same text twice.
const fields = computed(() => (adhoc.value ? REPORT_FIELDS.filter((f) => f.key !== "summary_manager") : REPORT_FIELDS));

// Only for naming the persona a report was written with; the report itself carries the
// id alone. A persona that has since been deleted stays an id rather than a guess.
const { data: personaPage } = useQuery({
  queryKey: ["personas"],
  retry: false,
  enabled: computed(() => report.value?.persona_id != null),
  queryFn: () => api.request<Page<PersonaResponse>>("/personas", { query: { limit: 100, offset: 0 } }),
});

const personaName = computed(() => {
  const id = report.value?.persona_id;
  if (id == null) return null;
  return personaPage.value?.items.find((p) => p.id === id)?.name ?? `persona_id ${id}`;
});
const isAuthor = computed(() => !!report.value && report.value.author_user_id === me.value?.id);
// An approved report is closed to edits; the API answers 409/403 and so does this.
const isEditable = computed(
  () => isAuthor.value && !!report.value && ["draft", "changes_requested"].includes(report.value.status),
);
const verdict = computed(() => canDecide(report.value ?? null, repo.value, me.value));

const { data: approvals } = useQuery({
  queryKey: computed(() => ["report", id.value, "approvals"]),
  enabled: computed(() => !!report.value),
  queryFn: () =>
    api.request<Page<ApprovalResponse>>(`/reports/${id.value}/approvals`, { query: { limit: 100 } }),
});

const { data: comments, isError: commentsFailed } = useQuery({
  queryKey: computed(() => ["report", id.value, "comments"]),
  enabled: computed(() => !!report.value),
  queryFn: () =>
    api.request<Page<CommentResponse>>(`/reports/${id.value}/comments`, { query: { limit: 100 } }),
});

// The week the report claims to describe, read back from the same source it was drafted
// from. It can come back empty on its own, which is not the same as four zeroes.
const { data: evidence, isPending: evidencePending, isError: evidenceFailed } = useQuery({
  queryKey: computed(() => ["activity", "report", id.value]),
  // /activity is per author, per week, per tracked repository — none of which describes
  // a custom report, whose evidence is the attributed sections themselves.
  enabled: computed(() => !!report.value && !adhoc.value && report.value.repo_id !== null),
  retry: false,
  queryFn: () =>
    api.request<ActivityResponse>(`/activity/${report.value!.author_user_id}`, {
      query: { since: report.value!.week_start, repo_id: report.value!.repo_id },
    }),
});

const only = ref<"commits" | "pull_requests" | "reviews" | "issues" | null>(null);

const evidenceRows = computed(() => {
  const a = evidence.value;
  if (!a) return [];
  const rows: { key: string; label: string; detail: string; stamp: string | null; kind: string }[] = [];
  if (!only.value || only.value === "commits") {
    for (const c of a.recent_commits) {
      rows.push({
        key: `c-${c.sha}`,
        label: c.sha.slice(0, 7),
        detail: (c.message ?? "(no message)").split("\n")[0] ?? "",
        stamp: c.committed_at,
        kind: "commits",
      });
    }
  }
  if (!only.value || only.value === "pull_requests") {
    for (const p of a.recent_pull_requests) {
      rows.push({
        key: `p-${p.repo_id}-${p.number}`,
        label: `#${p.number}`,
        detail: p.title ?? "(no title)",
        stamp: p.gh_created_at,
        kind: "pull_requests",
      });
    }
  }
  if (!only.value || only.value === "reviews") {
    a.recent_reviews.forEach((r, i) => {
      rows.push({
        key: `r-${r.pull_request_id}-${i}`,
        label: r.state.replace(/_/g, " "),
        detail: `Review on pull_request_id ${r.pull_request_id}`,
        stamp: r.submitted_at,
        kind: "reviews",
      });
    });
  }
  if (!only.value || only.value === "issues") {
    for (const issue of a.recent_issues) {
      rows.push({
        key: `i-${issue.repo_id}-${issue.number}`,
        label: `#${issue.number}`,
        detail: issue.title ?? "(no title)",
        stamp: issue.gh_created_at,
        kind: "issues",
      });
    }
  }
  return rows;
});

const COUNT_META = [
  { key: "commits", label: "Commits" },
  { key: "pull_requests", label: "Pull requests" },
  { key: "reviews", label: "Reviews" },
  { key: "issues", label: "Issues" },
] as const;

/* ── editing a field in place ──────────────────────────────────────────────── */

const editing = ref<string | null>(null);
const draftText = ref("");
const saveError = ref<string | null>(null);
const editButtons = ref<Record<string, HTMLElement | null>>({});

function setEditButton(el: Element | ComponentPublicInstance | null, key: string) {
  editButtons.value[key] = (el as HTMLElement | null) ?? null;
}

function startEdit(key: string, current: string | null) {
  saveError.value = null;
  editing.value = key;
  draftText.value = current ?? "";
}

const save = useMutation({
  mutationFn: (vars: { key: string; value: string }) =>
    api.request<ReportResponse>(`/reports/${id.value}`, {
      method: "PATCH",
      body: { [vars.key]: vars.value.trim() === "" ? null : vars.value },
    }),
  onSuccess: (updated, vars) => {
    queryClient.setQueryData(["report", id.value], updated);
    queryClient.invalidateQueries({ queryKey: ["reports"] });
    editing.value = null;
    announce("Saved");
    // Focus goes back to the control that opened the field, not to the top of the page.
    nextTick(() => editButtons.value[vars.key]?.focus());
  },
  onError: (err) => {
    const code = httpStatus(err);
    saveError.value =
      code === 409 || code === 403
        ? "This report is closed to edits — an approved report stays on the record as it was reviewed."
        : apiMessage(err, "Could not save that field.");
  },
});

const submit = useMutation({
  mutationFn: () => api.request<ReportResponse>(`/reports/${id.value}/submit`, { method: "POST" }),
  onSuccess: (updated) => {
    queryClient.setQueryData(["report", id.value], updated);
    queryClient.invalidateQueries({ queryKey: ["reports"] });
    queryClient.invalidateQueries({ queryKey: ["report", id.value, "approvals"] });
    announce("Submitted for review");
    showToast("Submitted for review.", "info");
  },
  onError: (err) => {
    saveError.value =
      httpStatus(err) === 422
        ? "422 · all three fields are empty, so there is nothing to submit."
        : apiMessage(err, "Could not submit this report.");
  },
});

const decide = useMutation({
  mutationFn: (vars: { decision: Decision; note: string }) =>
    api.request<ReportResponse>(`/reports/${id.value}/${vars.decision}`, {
      method: "POST",
      body: { note: vars.note || null },
    }),
  onSuccess: (updated) => {
    queryClient.setQueryData(["report", id.value], updated);
    queryClient.invalidateQueries({ queryKey: ["reports"] });
    queryClient.invalidateQueries({ queryKey: ["report", id.value, "approvals"] });
    announce(`Report is now ${statusLabel(updated.status).toLowerCase()}`);
    showToast("Decision recorded. The author was notified.", "ok");
  },
  onError: (err) => {
    const code = httpStatus(err);
    showToast(
      code === 403
        ? "403 · you cannot decide this report. Authorship is checked before any admin power."
        : code === 409
          ? "409 · this report has already been decided."
          : apiMessage(err, "Could not record that decision."),
      "bad",
    );
  },
});

const isDeletable = computed(() => isAuthor.value && report.value?.status === "draft");
const confirmDelete = ref(false);

const remove = useMutation({
  mutationFn: () => api.request<void>(`/reports/${id.value}`, { method: "DELETE" }),
  onSuccess: () => {
    confirmDelete.value = false;
    queryClient.invalidateQueries({ queryKey: ["reports"] });
    queryClient.removeQueries({ queryKey: ["report", id.value] });
    navigateTo("/reports");
  },
  onError: (err) => {
    confirmDelete.value = false;
    showToast(apiMessage(err, "Could not delete this draft."), "bad");
  },
});

/* ── comments ──────────────────────────────────────────────────────────────── */

const newComment = ref("");
const commentError = ref<string | null>(null);

const addComment = useMutation({
  mutationFn: () =>
    api.request<CommentResponse>(`/reports/${id.value}/comments`, {
      method: "POST",
      body: { body: newComment.value.trim() },
    }),
  onSuccess: () => {
    newComment.value = "";
    commentError.value = null;
    queryClient.invalidateQueries({ queryKey: ["report", id.value, "comments"] });
  },
  onError: (err) => {
    commentError.value = apiMessage(err, "Could not post that comment.");
  },
});

const editingCommentId = ref<number | null>(null);
const editingCommentBody = ref("");

const updateComment = useMutation({
  mutationFn: (commentId: number) =>
    api.request<CommentResponse>(`/reports/${id.value}/comments/${commentId}`, {
      method: "PATCH",
      body: { body: editingCommentBody.value.trim() },
    }),
  onSuccess: () => {
    editingCommentId.value = null;
    queryClient.invalidateQueries({ queryKey: ["report", id.value, "comments"] });
  },
  onError: (err) => {
    commentError.value = apiMessage(err, "Could not save that comment.");
  },
});

const removeComment = useMutation({
  mutationFn: (commentId: number) =>
    api.request<void>(`/reports/${id.value}/comments/${commentId}`, { method: "DELETE" }),
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: ["report", id.value, "comments"] });
  },
  onError: (err) => {
    commentError.value = apiMessage(err, "Could not delete that comment.");
  },
});

function startCommentEdit(comment: CommentResponse) {
  editingCommentId.value = comment.id;
  editingCommentBody.value = comment.body;
  commentError.value = null;
}

/* ── pdf ───────────────────────────────────────────────────────────────────── */

const pdfLoading = ref(false);

// The PDF endpoint needs the bearer token, so it cannot be a plain <a href>.
async function openPdf() {
  pdfLoading.value = true;
  try {
    const blob = await $fetch<Blob>(`${config.public.pulseUrl}/reports/${id.value}/pdf`, {
      responseType: "blob",
      headers: { Authorization: `Bearer ${auth.accessToken.value}` },
    });
    window.open(URL.createObjectURL(blob), "_blank", "noopener");
  } catch (err: unknown) {
    showToast(apiMessage(err, "Could not build the PDF."), "bad");
  } finally {
    pdfLoading.value = false;
  }
}

const unreachable = computed(() => {
  const code = httpStatus(error.value);
  return code === 403 || code === 404;
});
</script>

<template>
  <PulseShell :readout="`report ${id}`">
    <header class="sec">
      <NuxtLink
        to="/reports"
        :class="[FOCUS, TAP, '-ml-1 inline-flex items-center gap-1.5 rounded px-1 py-1 text-[12px] text-ink-muted transition-colors hover:text-ink']"
      >
        <Icon name="arrowLeft" class="h-3.5 w-3.5" />
        All reports
      </NuxtLink>
    </header>

    <p v-if="isPending" class="mt-8 text-[12.5px] text-ink-muted">Loading report…</p>

    <div v-else-if="unreachable" class="mt-8 rounded-md bg-surface/40 px-5 py-10 ring-1 ring-inset ring-line-subtle">
      <h1 class="text-[15px] font-medium tracking-tight">This report is not available to you</h1>
      <p class="mt-1.5 max-w-[54ch] text-[12.5px] leading-relaxed text-ink-muted">
        It may have been deleted, or you may not be its author, its repository's lead or deputy, or
        an admin of its department.
      </p>
      <div class="mt-4 flex">
        <NuxtLink to="/reports"><Btn size="sm" variant="secondary">Back to reports</Btn></NuxtLink>
      </div>
    </div>

    <div v-else-if="isError" role="alert" class="mt-8 rounded-md bg-bad-surface px-5 py-6">
      <h1 class="text-[15px] font-medium tracking-tight">Could not load this report</h1>
      <p class="mt-1.5 max-w-[54ch] text-[12.5px] leading-relaxed text-ink-muted">
        {{ apiMessage(error, "The Pulse API did not answer. Check that the service is running.") }}
      </p>
      <div class="mt-4 flex gap-2">
        <Btn size="sm" variant="secondary" @click="queryClient.invalidateQueries({ queryKey: ['report', id] })">
          Try again
        </Btn>
        <NuxtLink to="/reports"><Btn size="sm" variant="ghost">Back to reports</Btn></NuxtLink>
      </div>
    </div>

    <template v-else-if="report">
      <div class="sec mt-3">
        <Eyebrow>Pulse · report</Eyebrow>
        <p class="mono mt-3 text-[12px] text-ink-muted" data-test="report-scope">
          {{ repoLabel }}
          <span v-if="report.repo_id === null && report.repo_full_name" class="text-ink-faint">(not tracked by Pulse)</span>
          › {{ reportRange(report) }}
        </p>
        <div class="mt-1 flex flex-wrap items-center gap-3">
          <!-- The kind is the heading. It used to be the heading *and* a chip beside it
               carrying the raw API value, which said the same thing twice, once in a word
               nobody outside the codebase uses. -->
          <h1
            class="text-[clamp(1.5rem,2.2vw,1.9rem)] font-semibold leading-[1.05] tracking-[-0.035em]"
            data-test="report-kind"
          >{{ reportKindLabel(report) }}</h1>
          <span
            aria-live="polite"
            :class="[MONO_LABEL, 'inline-flex items-center rounded px-2 py-1', statusClass(report.status)]"
          >{{ statusLabel(report.status) }}</span>
          <span class="mono text-[12px] text-ink-muted">report_id {{ report.id }}</span>
        </div>
        <p class="mt-2 flex flex-wrap items-center gap-2 text-[12.5px] text-ink-muted">
          <Avatar :name="personName(report.author, report.author_user_id)" size="sm" />
          Written by
          <span class="text-ink">{{ personName(report.author, report.author_user_id) }}</span>
          <span v-if="isAuthor">(you)</span>
          <span class="mono text-[12px]">· user_id {{ report.author_user_id }}</span>
          <span v-if="report.generated_at" class="mono text-[12px]">
            · AI-drafted {{ formatDateTime(report.generated_at) }}
            <template v-if="report.prompt_version">· {{ report.prompt_version }}</template>
          </span>
          <span v-if="personaName" class="mono text-[12px]" data-test="report-persona">
            · persona {{ personaName }}
          </span>
        </p>
      </div>

      <!-- Delete sits on its own side of the row with a rule between. It used to be the
           third button in a run of three, one tab-stop from Submit. -->
      <div class="sec mt-5 flex flex-wrap items-center gap-2" style="animation-delay: 40ms">
        <Btn v-if="isEditable" size="sm" :busy="submit.isPending.value" @click="submit.mutate()">
          Submit for review
        </Btn>
        <Btn size="sm" variant="secondary" :busy="pdfLoading" @click="openPdf">Download PDF</Btn>
        <template v-if="isDeletable">
          <span aria-hidden="true" class="ml-2 hidden h-6 w-px bg-line-subtle sm:block" />
          <Btn size="sm" variant="destructive" @click="confirmDelete = true">
            Delete draft
          </Btn>
        </template>
      </div>

      <p v-if="saveError" role="alert" class="mt-4 max-w-[74ch] rounded-md bg-bad-surface px-4 py-3 text-[12.5px] leading-relaxed text-ink">
        {{ saveError }}
      </p>

      <div class="mt-8 grid gap-8 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div class="min-w-0">
          <!-- Counts as filters over the evidence beside them. -->
          <section v-if="!adhoc" class="sec grid grid-cols-2 gap-3 md:grid-cols-4" style="animation-delay: 60ms" aria-label="The week's counts">
            <button
              v-for="meta in COUNT_META"
              :key="meta.key"
              type="button"
              :aria-pressed="only === meta.key"
              :disabled="!evidence"
              :class="[
                FOCUS,
                DISABLED,
                'rounded-md px-4 py-3.5 text-left ring-1 ring-inset transition-colors',
                only === meta.key ? 'bg-surface-active ring-line' : 'bg-surface/40 ring-line-subtle enabled:hover:ring-line',
              ]"
              @click="only = only === meta.key ? null : meta.key"
            >
              <span :class="[MONO_LABEL, 'block text-ink-faint']">{{ meta.label }}</span>
              <span class="mono mt-2 block text-[26px] leading-none tracking-tight text-ink">
                <template v-if="evidencePending"><span class="inline-block h-6 w-8 animate-pulse rounded bg-surface" /></template>
                <template v-else-if="evidence">{{ evidence.counts[meta.key] }}</template>
                <template v-else>—</template>
              </span>
            </button>
          </section>

          <template v-if="!adhoc">
            <p v-if="evidenceFailed" role="alert" class="mt-3 max-w-[74ch] text-[12.5px] leading-relaxed text-ink-muted">
              The week's activity did not come back, so the counts above are missing rather than
              zero. The report itself is unaffected — this is a second request.
            </p>
            <p v-else class="mt-3 max-w-[74ch] text-[12.5px] leading-relaxed text-ink-muted">
              Counts are the week's totals for this author in this repository. Selecting one narrows
              the evidence list to that kind.
            </p>
          </template>

          <!-- One section per contributor, in the order they were written, each under the
               name it describes. They are never run together: two people's work reading as
               one paragraph is exactly the failure this report exists to avoid. -->
          <section v-if="adhoc" class="sec" style="animation-delay: 60ms" aria-labelledby="sections-heading">
            <div class="flex flex-wrap items-baseline justify-between gap-3 border-b border-line-subtle pb-2">
              <h2 id="sections-heading" class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">
                By contributor
              </h2>
              <p class="mono text-[12px] text-ink-muted">
                {{ sections.length }} {{ sections.length === 1 ? "person" : "people" }} ·
                {{ reportRange(report) }}
              </p>
            </div>

            <p
              data-test="attribution-note"
              class="mt-3 max-w-[74ch] rounded-md bg-warn-surface px-3.5 py-2.5 text-[12.5px] leading-relaxed text-ink"
            >
              {{ ATTRIBUTION_NOTE }}
            </p>

            <p v-if="!sections.length" class="mt-4 max-w-[70ch] text-[12.5px] leading-relaxed text-ink-muted">
              This report has no attributed sections stored against it.
            </p>

            <div v-else data-test="sections">
              <article
                v-for="section in sections"
                :key="section.id"
                data-test="section"
                class="mt-6 border-t border-line-subtle pt-4 first:border-t-0"
              >
                <div class="flex flex-wrap items-center gap-2.5">
                  <Avatar :name="subjectLabel(section)" size="sm" />
                  <h3 class="text-[13.5px] font-medium tracking-tight text-ink" data-test="section-name">
                    {{ subjectLabel(section) }}
                  </h3>
                  <span
                    :class="[MONO_LABEL, 'rounded bg-sunken px-2 py-1 text-ink-muted ring-1 ring-inset ring-line-subtle']"
                  >{{ section.subject_user_id !== null ? "pulse user" : "github login" }}</span>
                  <span class="mono ml-auto text-[12px] text-ink-faint">#{{ section.position + 1 }}</span>
                </div>
                <p class="mt-2 max-w-[74ch] whitespace-pre-wrap text-[13px] leading-relaxed text-ink">
                  <template v-if="section.section">{{ section.section }}</template>
                  <span v-else class="italic text-ink-muted">No section was written for this person.</span>
                </p>
              </article>
            </div>

            <p class="mt-6 max-w-[74ch] text-[12px] leading-relaxed text-ink-muted">
              These sections are what an approver reads: they are stored as this report's manager
              summary, in this order.
            </p>
          </section>

          <!-- The three fields, each editable where it stands. -->
          <section class="sec mt-8" style="animation-delay: 80ms" aria-label="The report">
            <div v-for="field in fields" :key="field.key" class="border-t border-line-subtle pt-3.5 first:border-t-0 first:pt-0 [&+div]:mt-5">
              <div class="flex flex-wrap items-center gap-2.5">
                <h2 class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">{{ field.label }}</h2>
                <span class="mono text-[12px] text-ink-faint">{{ field.api }}</span>
                <button
                  v-if="isEditable && editing !== field.key"
                  :ref="(el) => setEditButton(el, field.key)"
                  type="button"
                  :class="[FOCUS, 'ml-auto rounded px-1 py-0.5 text-[12px] text-ink-muted transition-colors hover:text-ink']"
                  @click="startEdit(field.key, report[field.key])"
                >Edit</button>
              </div>

              <template v-if="editing === field.key">
                <label class="sr-only" :for="`field-${field.key}`">{{ field.label }}</label>
                <textarea
                  :id="`field-${field.key}`"
                  v-model="draftText"
                  rows="6"
                  :class="[FOCUS, 'mt-2 w-full resize-y rounded-md bg-sunken px-3 py-2.5 text-[12.5px] leading-relaxed text-ink ring-1 ring-inset ring-line transition-colors placeholder:text-ink-faint hover:ring-line-strong']"
                />
                <div class="mt-2 flex flex-wrap items-center gap-2">
                  <Btn size="sm" :busy="save.isPending.value" @click="save.mutate({ key: field.key, value: draftText })">
                    Save
                  </Btn>
                  <Btn size="sm" variant="ghost" @click="editing = null">Cancel</Btn>
                  <span class="mono ml-auto text-[12px] text-ink-muted">{{ draftText.trim().length }} characters</span>
                </div>
              </template>

              <p v-else class="mt-2 max-w-[74ch] whitespace-pre-wrap text-[13px] leading-relaxed text-ink">
                <template v-if="report[field.key]">{{ report[field.key] }}</template>
                <span v-else class="italic text-ink-muted">Not written yet.</span>
              </p>
            </div>

            <p v-if="isAuthor && !isEditable" class="mt-5 max-w-[74ch] text-[12.5px] leading-relaxed text-ink-muted">
              This report is {{ statusLabel(report.status).toLowerCase() }}, so it is closed to
              edits. It stays on the record as it was reviewed.
            </p>
          </section>

          <!-- A decision only exists while one is being asked for. -->
          <section class="sec mt-8" style="animation-delay: 100ms" aria-labelledby="decision-heading">
            <h2 id="decision-heading" class="sr-only">Decision</h2>
            <ReportDecision
              v-if="verdict.allowed"
              :report-id="report.id"
              :allowed="true"
              :author-name="personName(report.author, report.author_user_id)"
              :busy="decide.isPending.value"
              @decide="(decision, note) => decide.mutate({ decision, note })"
            />
            <div v-else class="rounded-md bg-surface/40 px-4 py-4 ring-1 ring-inset ring-line-subtle">
              <Eyebrow>Decision</Eyebrow>
              <p class="mt-2 max-w-[62ch] text-[12.5px] leading-relaxed text-ink-muted">
                <template v-if="verdict.reason">{{ verdict.reason }}</template>
                <template v-else>
                  This report is {{ statusLabel(report.status).toLowerCase() }}. Whatever happened
                  is in the history.
                </template>
              </p>
            </div>
          </section>

          <!-- Comments. The prototype has no thread; this page does, and it stays. -->
          <section class="sec mt-8 border-t border-line-subtle pt-6" style="animation-delay: 120ms" aria-labelledby="comments-heading">
            <h2 id="comments-heading" class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">Comments</h2>

            <p v-if="commentsFailed" role="alert" class="mt-2 text-[12.5px] text-ink-muted">
              The comment thread did not load. Everything else on this page is unaffected.
            </p>
            <p v-else-if="!comments || !comments.items.length" class="mt-2 text-[12.5px] text-ink-muted">
              No comments yet.
            </p>
            <ul v-else class="mt-3 divide-y divide-line-subtle border-y border-line-subtle">
              <li v-for="comment in comments.items" :key="comment.id" class="py-3">
                <p class="flex flex-wrap items-baseline gap-2 text-[12px] text-ink-muted">
                  <span class="text-ink">{{ personName(comment.author, comment.author_user_id) }}</span>
                  <span class="mono text-[12px]">{{ formatDateTime(comment.created_at) }}</span>
                  <span v-if="comment.edited_at" class="mono text-[12px]">(edited)</span>
                </p>

                <template v-if="editingCommentId === comment.id">
                  <label class="sr-only" :for="`comment-${comment.id}`">Edit your comment</label>
                  <textarea
                    :id="`comment-${comment.id}`"
                    v-model="editingCommentBody"
                    rows="3"
                    :class="[FOCUS, 'mt-2 w-full resize-y rounded-md bg-sunken px-3 py-2 text-[12.5px] leading-relaxed text-ink ring-1 ring-inset ring-line hover:ring-line-strong']"
                  />
                  <div class="mt-2 flex gap-2">
                    <Btn size="sm" :busy="updateComment.isPending.value" @click="updateComment.mutate(comment.id)">Save</Btn>
                    <Btn size="sm" variant="ghost" @click="editingCommentId = null">Cancel</Btn>
                  </div>
                </template>

                <template v-else>
                  <p class="mt-1.5 max-w-[74ch] whitespace-pre-wrap text-[12.5px] leading-relaxed text-ink">
                    {{ comment.body }}
                  </p>
                  <div v-if="comment.author_user_id === me?.id" class="mt-1.5 flex gap-3">
                    <button
                      type="button"
                      :class="[FOCUS, 'rounded text-[12.5px] text-ink-muted transition-colors hover:text-ink']"
                      @click="startCommentEdit(comment)"
                    >Edit</button>
                    <button
                      type="button"
                      :class="[FOCUS, 'rounded text-[12.5px] text-bad transition-colors hover:brightness-110']"
                      @click="removeComment.mutate(comment.id)"
                    >Delete</button>
                  </div>
                </template>
              </li>
            </ul>

            <label for="new-comment" class="mt-4 block text-[12px] text-ink-muted">Add a comment</label>
            <textarea
              id="new-comment"
              v-model="newComment"
              rows="3"
              :class="[FOCUS, 'mt-1.5 w-full resize-y rounded-md bg-sunken px-3 py-2 text-[12.5px] leading-relaxed text-ink ring-1 ring-inset ring-line hover:ring-line-strong']"
            />
            <div class="mt-2 flex items-center gap-2">
              <Btn
                size="sm"
                :disabled="!newComment.trim()"
                :busy="addComment.isPending.value"
                @click="addComment.mutate()"
              >Post comment</Btn>
            </div>
            <p v-if="commentError" role="alert" class="mt-2 text-[12.5px] text-bad">{{ commentError }}</p>
          </section>
        </div>

        <!-- Evidence and history. -->
        <aside class="min-w-0 space-y-8">
          <section v-if="!adhoc" aria-labelledby="evidence-heading" class="sec" style="animation-delay: 60ms">
            <div class="flex items-baseline justify-between gap-3 border-b border-line-subtle pb-2">
              <h2 id="evidence-heading" :class="[MONO_LABEL, 'text-ink-faint']">Evidence</h2>
              <p class="mono text-[12px] text-ink-muted">{{ evidenceRows.length }} shown</p>
            </div>
            <p v-if="evidencePending" class="mt-3 text-[12px] text-ink-muted">Reading the week…</p>
            <p v-else-if="evidenceFailed" class="mt-3 text-[12px] leading-relaxed text-ink-muted">
              No evidence could be read for this week.
            </p>
            <p v-else-if="!evidenceRows.length" class="mt-3 text-[12px] leading-relaxed text-ink-muted">
              Nothing was synced for this author in this repository that week.
            </p>
            <ul v-else class="divide-y divide-line-subtle">
              <li v-for="row in evidenceRows" :key="row.key" class="py-2.5">
                <p class="flex items-baseline justify-between gap-3">
                  <span class="mono text-[12px] text-ink-muted">{{ row.label }}</span>
                  <span class="mono shrink-0 text-[12px] text-ink-muted">{{ formatStamp(row.stamp) }}</span>
                </p>
                <p class="mt-0.5 text-[12.5px] leading-relaxed text-ink">{{ row.detail }}</p>
              </li>
            </ul>
          </section>

          <section aria-labelledby="history-heading" class="sec" style="animation-delay: 100ms">
            <h2 id="history-heading" :class="[MONO_LABEL, 'border-b border-line-subtle pb-2 text-ink-faint']">History</h2>
            <p v-if="!approvals || !approvals.items.length" class="mt-3 text-[12px] leading-relaxed text-ink-muted">
              Nothing yet. This report has not been submitted for review.
            </p>
            <ul v-else class="mt-3 space-y-3">
              <li v-for="entry in approvals.items" :key="entry.id" class="flex gap-2.5">
                <span class="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-ink-faint" aria-hidden="true" />
                <span class="min-w-0">
                  <span class="block text-[12.5px] leading-relaxed text-ink-muted">
                    <span class="text-ink">{{ personName(entry.actor, entry.actor_user_id) }}</span>
                    {{ actionLabel(entry.action) }}
                  </span>
                  <span class="mono block text-[12px] text-ink-muted">{{ formatDateTime(entry.created_at) }}</span>
                  <span v-if="entry.note" class="mt-1 block max-w-[46ch] whitespace-pre-wrap text-[12px] leading-relaxed text-ink">
                    {{ entry.note }}
                  </span>
                </span>
              </li>
            </ul>
          </section>

          <section v-if="!adhoc" class="rounded-md bg-sunken/60 px-4 py-3.5 ring-1 ring-inset ring-line-subtle">
            <Eyebrow>One per person, per repository, per week</Eyebrow>
            <p class="mt-2 max-w-[46ch] text-[12.5px] leading-relaxed text-ink-muted">
              This is yours for <span class="mono text-[12px] text-ink">{{ repoLabel }}</span
              >, week of <span class="mono text-[12px] text-ink">{{ report.week_start }}</span
              >. Rewriting it replaces what is here rather than adding a second copy, which is why
              the history matters.
            </p>
          </section>

          <section v-else class="rounded-md bg-sunken/60 px-4 py-3.5 ring-1 ring-inset ring-line-subtle">
            <Eyebrow>Asked for, not scheduled</Eyebrow>
            <p class="mt-2 max-w-[46ch] text-[12.5px] leading-relaxed text-ink-muted">
              A custom report covers
              <span class="mono text-[12px] text-ink">{{ report.range_start }}</span> to
              <span class="mono text-[12px] text-ink">{{ report.range_end }}</span> on
              <span class="mono text-[12px] text-ink">{{ repoLabel }}</span>. There is no
              uniqueness rule on it, so asking again writes a second report rather than replacing
              this one.
            </p>
          </section>
        </aside>
      </div>
    </template>

    <Modal
      :open="confirmDelete"
      title="Delete this draft?"
      description="Drafts are only visible to you, so nobody else has read it — but deleting cannot be undone."
      :close-on-backdrop="false"
      @close="confirmDelete = false"
    >
      <p class="text-[12.5px] leading-relaxed text-ink-muted">
        Pulse can draft a new one for this week from your synced activity, but anything you typed
        into this draft goes with it.
      </p>
      <template #footer>
        <Btn size="sm" variant="ghost" @click="confirmDelete = false">Keep it</Btn>
        <Btn size="sm" variant="destructive" :busy="remove.isPending.value" @click="remove.mutate()">
          Delete draft
        </Btn>
      </template>
    </Modal>
  </PulseShell>
</template>
