<script setup lang="ts">
import type { ComponentPublicInstance } from "vue";
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import type { SelectOption, TabItem } from "@crescent/ui/types/ui";
import type { Decision } from "~/components/ReportDecision.vue";
import type { ActivityResponse, Page, ReportResponse } from "~/types/api";

definePageMeta({ middleware: "auth" });

/* Two lists that never overlap: what you wrote, and what is waiting on your decision.
   A queue row opens where it sits — reading a report and deciding it is one task. */

const PER_PAGE = 8;

const api = useApi();
const route = useRoute();
const router = useRouter();
const queryClient = useQueryClient();
const { repositories, repoName } = useRepositories();
const { show: showToast } = useToast();

const { me, unavailable: meUnavailable, retry: retryMe } = useMe();

// Filter and page state lives in the query string: "send me the link to my rejected
// reports" is a real request.
const scope = computed({
  get: () => (route.query.scope === "queue" ? "queue" : "mine") as "mine" | "queue",
  set: (value) => patchQuery({ scope: value, status: undefined, repo: undefined, page: undefined }),
});
const status = computed({
  get: () => (typeof route.query.status === "string" ? route.query.status : "all"),
  set: (value) => patchQuery({ status: value === "all" ? undefined : value, page: undefined }),
});
const repoFilter = computed({
  get: () => (route.query.repo ? Number(route.query.repo) : null),
  set: (value) => patchQuery({ repo: value === null ? undefined : String(value), page: undefined }),
});
const page = computed({
  get: () => Math.max(0, Number(route.query.page ?? 0) || 0),
  set: (value) => patchQuery({ page: value === 0 ? undefined : String(value) }),
});

function patchQuery(patch: Record<string, string | undefined>) {
  open.value = null;
  menu.value = null;
  router.replace({ query: { ...route.query, ...patch } });
}

const offset = computed(() => page.value * PER_PAGE);

const listQuery = computed(() =>
  scope.value === "queue"
    ? {
        path: "/reports/review-queue",
        query: {
          status: status.value === "all" ? "submitted" : status.value,
          limit: PER_PAGE,
          offset: offset.value,
        },
      }
    : {
        path: "/reports",
        query: {
          author_user_id: me.value?.id,
          repo_id: repoFilter.value ?? undefined,
          status: status.value === "all" ? undefined : status.value,
          limit: PER_PAGE,
          offset: offset.value,
        },
      },
);

const { data, isPending, isError, error } = useQuery({
  queryKey: computed(() => [
    "reports",
    scope.value,
    me.value?.id ?? "anon",
    status.value,
    repoFilter.value ?? "all",
    offset.value,
  ]),
  enabled: computed(() => scope.value === "queue" || me.value !== null),
  queryFn: () => api.request<Page<ReportResponse>>(listQuery.value.path, { query: listQuery.value.query }),
});

// The API has no aggregate endpoint, so a chip's count is a limit=1 request per status
// asked only for its `total`. Five small reads, and every number on screen is real.
const { data: totals } = useQuery({
  queryKey: computed(() => [
    "report-totals",
    scope.value,
    me.value?.id ?? "anon",
    repoFilter.value ?? "all",
  ]),
  enabled: computed(() => scope.value === "queue" || me.value !== null),
  queryFn: async () => {
    const out: Record<string, number> = {};
    await Promise.all(
      REPORT_STATUSES.map(async (value) => {
        const path = scope.value === "queue" ? "/reports/review-queue" : "/reports";
        const query = scope.value === "queue"
          ? { status: value, limit: 1, offset: 0 }
          : { author_user_id: me.value?.id, repo_id: repoFilter.value ?? undefined, status: value, limit: 1, offset: 0 };
        const res = await api.request<Page<ReportResponse>>(path, { query });
        out[value] = res.total;
      }),
    );
    return out;
  },
});

const rows = computed(() => data.value?.items ?? []);
const total = computed(() => data.value?.total ?? 0);
const pages = computed(() => pageCount(total.value, PER_PAGE));
const scopeTotal = computed(() =>
  Object.values(totals.value ?? {}).reduce((sum, n) => sum + n, 0),
);
const filtering = computed(() => status.value !== "all" || repoFilter.value !== null);

const tabs = computed<TabItem[]>(() => [
  { id: "mine", label: "My reports", hint: scope.value === "mine" ? String(scopeTotal.value) : undefined },
  { id: "queue", label: "Review queue", hint: scope.value === "queue" ? String(scopeTotal.value) : undefined },
]);

const repoOptions = computed<SelectOption[]>(() => [
  { value: "all", label: "All repositories" },
  ...repositories.value.map((r) => ({ value: String(r.id), label: r.full_name })),
]);

/* ── the expanded queue row ────────────────────────────────────────────────── */

const open = ref<number | null>(null);
const openReport = computed(() => rows.value.find((r) => r.id === open.value) ?? null);

// Evidence for the open row: the author's week in that repository, so the claim and the
// week it describes sit side by side.
const { data: evidence, isError: evidenceFailed } = useQuery({
  queryKey: computed(() => ["activity", "queue-row", open.value ?? "none"]),
  enabled: computed(() => openReport.value !== null),
  retry: false,
  queryFn: () =>
    api.request<ActivityResponse>(`/activity/${openReport.value!.author_user_id}`, {
      query: { since: openReport.value!.week_start, repo_id: openReport.value!.repo_id },
    }),
});

function repoOf(report: ReportResponse) {
  return repositories.value.find((r) => r.id === report.repo_id) ?? null;
}

function verdict(report: ReportResponse) {
  return canDecide(report, repoOf(report), me.value);
}

const decide = useMutation({
  mutationFn: (vars: { id: number; decision: Decision; note: string }) =>
    api.request<ReportResponse>(`/reports/${vars.id}/${vars.decision}`, {
      method: "POST",
      body: { note: vars.note || null },
    }),
  onSuccess: (_updated, vars) => {
    open.value = null;
    queryClient.invalidateQueries({ queryKey: ["reports"] });
    queryClient.invalidateQueries({ queryKey: ["report-totals"] });
    queryClient.invalidateQueries({ queryKey: ["review-queue"] });
    queryClient.invalidateQueries({ queryKey: ["report", String(vars.id)] });
    showToast(`Recorded on report ${vars.id}. The author was notified.`, "ok");
  },
  onError: (err, vars) => {
    const code = httpStatus(err);
    showToast(
      code === 403
        ? `403 · you cannot decide report ${vars.id}. Authorship is checked before any admin power.`
        : code === 409
          ? `409 · report ${vars.id} has already been decided.`
          : apiMessage(err, "Could not record that decision."),
      "bad",
    );
  },
});

/* ── the row menu ──────────────────────────────────────────────────────────── */

const menu = ref<number | null>(null);
const menuBox = ref<HTMLElement | null>(null);

function setMenuBox(el: Element | ComponentPublicInstance | null, id: number) {
  if (menu.value === id) menuBox.value = (el as HTMLElement | null) ?? null;
}

function onDocumentDown(event: MouseEvent) {
  if (menuBox.value && !menuBox.value.contains(event.target as Node)) menu.value = null;
}

function onDocumentKey(event: KeyboardEvent) {
  if (event.key === "Escape") menu.value = null;
}

watch(menu, (id) => {
  if (id === null) {
    document.removeEventListener("mousedown", onDocumentDown);
    document.removeEventListener("keydown", onDocumentKey);
  } else {
    document.addEventListener("mousedown", onDocumentDown);
    document.addEventListener("keydown", onDocumentKey);
  }
});

onBeforeUnmount(() => {
  document.removeEventListener("mousedown", onDocumentDown);
  document.removeEventListener("keydown", onDocumentKey);
});

const submit = useMutation({
  mutationFn: (id: number) => api.request<ReportResponse>(`/reports/${id}/submit`, { method: "POST" }),
  onSuccess: (_res, id) => {
    queryClient.invalidateQueries({ queryKey: ["reports"] });
    queryClient.invalidateQueries({ queryKey: ["report-totals"] });
    showToast(`Report ${id} submitted for review.`, "info");
  },
  onError: (err, id) => {
    showToast(
      httpStatus(err) === 422
        ? `422 · report ${id} has no summaries yet, so it cannot be submitted.`
        : apiMessage(err, "Could not submit that report."),
      "warn",
    );
  },
});

function hasBody(report: ReportResponse): boolean {
  return [report.summary_manager, report.summary_exec, report.next_week_goals].some(
    (field) => (field ?? "").trim() !== "",
  );
}

// The endpoint answers 422 for an empty report. Saying so before the request costs
// nothing, and the real 422 is still handled above.
function submitForReview(report: ReportResponse) {
  menu.value = null;
  if (!hasBody(report)) {
    showToast(`422 · report ${report.id} has no summaries yet, so it cannot be submitted.`, "warn");
    return;
  }
  submit.mutate(report.id);
}

const confirmDelete = ref<ReportResponse | null>(null);

const remove = useMutation({
  mutationFn: (id: number) => api.request<void>(`/reports/${id}`, { method: "DELETE" }),
  onSuccess: (_res, id) => {
    confirmDelete.value = null;
    queryClient.invalidateQueries({ queryKey: ["reports"] });
    queryClient.invalidateQueries({ queryKey: ["report-totals"] });
    showToast(`Draft ${id} deleted.`, "muted");
  },
  onError: (err) => {
    confirmDelete.value = null;
    showToast(apiMessage(err, "Could not delete that draft."), "bad");
  },
});

const who = ref(false);
</script>

<template>
  <PulseShell :readout="`${total} reports`">
    <header class="sec flex flex-wrap items-end justify-between gap-4">
      <div class="min-w-0">
        <Eyebrow>Pulse · reports</Eyebrow>
        <h1 class="mt-3 text-[clamp(1.5rem,2.2vw,1.9rem)] font-semibold leading-[1.05] tracking-[-0.035em]">
          Weekly reports
        </h1>
        <p class="mt-1.5 max-w-[68ch] text-[12.5px] leading-relaxed text-ink-muted">
          One report per repository, per week. What you wrote sits on the left; what is waiting on
          your decision sits on the right, and the two sets never overlap.
        </p>
      </div>
      <div class="flex shrink-0 flex-wrap items-center gap-2">
        <p class="mono flex items-center gap-2 rounded-md bg-sunken px-2.5 py-2 text-[11px] ring-1 ring-inset ring-line-subtle">
          <span :class="[MONO_LABEL, 'text-ink-faint']">get</span>
          <span class="text-ink">{{ listQuery.path }}</span>
          <span class="hidden text-ink-muted sm:inline">?limit={{ PER_PAGE }}&offset={{ offset }}</span>
        </p>
        <NuxtLink to="/reports/new"><Btn size="sm">New report</Btn></NuxtLink>
      </div>
    </header>

    <div class="sec" style="animation-delay: 40ms">
      <Tabs
        id="reports"
        :model-value="scope"
        label="Report scope"
        class="mt-6"
        has-panel
        :items="tabs"
        @update:model-value="scope = $event as 'mine' | 'queue'"
      />
    </div>

    <TabPanel id="reports" :tab="scope" class="mt-4">
      <!-- The third clause of the queue rule is the one people assume is missing. -->
      <div v-if="scope === 'queue'" class="mb-4 rounded-md bg-surface/40 ring-1 ring-inset ring-line-subtle">
        <button
          type="button"
          :aria-expanded="who"
          aria-controls="who-decides"
          :class="[FOCUS, 'flex w-full items-center gap-2 rounded-md px-3.5 py-2.5 text-left transition-colors hover:bg-surface-hover/60']"
          @click="who = !who"
        >
          <Icon name="shield" class="h-3.5 w-3.5 shrink-0 text-ink-faint" />
          <span class="text-[12.5px] font-medium text-ink">Who decides</span>
          <Icon name="chevronDown" :class="['ml-auto h-3.5 w-3.5 shrink-0 text-ink-faint transition-transform', who && 'rotate-180']" />
        </button>
        <div id="who-decides" class="sec-collapse" :data-open="who ? 'true' : 'false'">
          <div>
            <div class="space-y-2 border-t border-line-subtle px-3.5 py-3 text-[12px] leading-relaxed text-ink-muted">
              <p>
                <span class="font-medium text-ink">You never review your own work.</span> A report
                you wrote cannot appear in this queue, whatever its status — if it needs a decision
                it goes to the lead of its repository or an admin of its department, not back to you.
              </p>
              <p>
                A report is here when it has been submitted <span class="italic">and</span> you are
                the named lead or deputy on its repository, or an admin of the department it was
                filed to, <span class="italic">and</span> you did not write it.
              </p>
              <p>
                Deciding a report takes it out of the queue. The decision, and any note you leave,
                is kept on the report under <span class="mono text-[12px] text-ink">History</span>.
              </p>
            </div>
          </div>
        </div>
      </div>

      <!-- Filters. -->
      <div class="sec flex flex-wrap items-center gap-2 border-b border-line-subtle pb-3" style="animation-delay: 40ms">
        <div role="group" aria-label="Filter by status" class="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            :aria-pressed="status === 'all'"
            :class="[
              FOCUS,
              'rounded-md px-2.5 py-1.5 text-[12px] ring-1 ring-inset transition-colors',
              status === 'all'
                ? 'bg-surface-active font-medium text-ink ring-line'
                : 'bg-sunken text-ink-muted ring-line-subtle hover:text-ink hover:ring-line',
            ]"
            @click="status = 'all'"
          >
            All <span class="mono ml-1 text-[11px] text-ink-muted">{{ scopeTotal }}</span>
          </button>

          <button
            v-for="value in REPORT_STATUSES"
            :key="value"
            type="button"
            :aria-pressed="status === value"
            :disabled="(totals?.[value] ?? 0) === 0 && status !== value"
            :class="[
              FOCUS,
              'inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[12px] ring-1 ring-inset transition-colors',
              status === value
                ? 'bg-surface-active font-medium text-ink ring-line'
                : 'bg-sunken text-ink-muted ring-line-subtle enabled:hover:text-ink enabled:hover:ring-line',
              (totals?.[value] ?? 0) === 0 && status !== value && 'cursor-default opacity-45',
            ]"
            @click="status = value"
          >
            <!-- A chip that filters to nothing keeps its word and loses its dot:
                 colour with no referent is noise. -->
            <span
              v-if="(totals?.[value] ?? 0) > 0 || status === value"
              :class="['h-1.5 w-1.5 shrink-0 rounded-full', DOT_BG[statusTone(value)]]"
              aria-hidden="true"
            />
            {{ statusLabel(value) }}
            <span class="mono text-[11px] text-ink-muted">{{ totals?.[value] ?? 0 }}</span>
          </button>
        </div>

        <Select
          v-if="scope === 'mine'"
          class="ml-auto w-[220px]"
          label="Repository"
          :model-value="repoFilter === null ? 'all' : String(repoFilter)"
          :options="repoOptions"
          @update:model-value="repoFilter = $event === 'all' ? null : Number($event)"
        />
      </div>

      <!-- Identity unreachable: "my reports" cannot be scoped to a user with no id, and
           a spinner that never ends is the wrong way to say so. -->
      <div v-if="scope === 'mine' && meUnavailable" role="alert" class="sec mt-6 rounded-md bg-bad-surface px-5 py-6">
        <p class="text-[13.5px] font-medium text-ink">Your account could not be read</p>
        <p class="mt-1.5 max-w-[62ch] text-[12.5px] leading-relaxed text-ink-muted">
          Pulse keeps no user record of its own, so it asks identity who you are. That request
          did not answer, and without your id this list cannot be narrowed to what you wrote.
        </p>
        <div class="mt-4 flex">
          <Btn size="sm" variant="secondary" @click="retryMe">Try again</Btn>
        </div>
      </div>

      <!-- Loading, error, then the three ways this list can be empty. -->
      <p v-else-if="isPending" class="sec mt-6 text-[12.5px] text-ink-muted">Loading reports…</p>

      <div
        v-else-if="isError"
        role="alert"
        class="sec mt-6 rounded-md bg-bad-surface px-5 py-6"
      >
        <p class="text-[13.5px] font-medium text-ink">Could not load this list</p>
        <p class="mt-1.5 max-w-[62ch] text-[12.5px] leading-relaxed text-ink-muted">
          {{ apiMessage(error, "The Pulse API did not answer. Check that the service is running, then try again.") }}
        </p>
        <div class="mt-4 flex">
          <Btn size="sm" variant="secondary" @click="queryClient.invalidateQueries({ queryKey: ['reports'] })">
            Try again
          </Btn>
        </div>
      </div>

      <div
        v-else-if="!rows.length && filtering"
        class="sec mt-6 rounded-md bg-surface/40 px-5 py-10 ring-1 ring-inset ring-line-subtle"
      >
        <p class="text-[13.5px] font-medium text-ink">No report matches this filter</p>
        <p class="mt-1.5 max-w-[54ch] text-[12.5px] leading-relaxed text-ink-muted">
          {{ scopeTotal }} report{{ scopeTotal === 1 ? "" : "s" }} in this scope, none of them
          matching what you have narrowed to.
        </p>
        <div class="mt-4 flex">
          <Btn size="sm" variant="secondary" @click="patchQuery({ status: undefined, repo: undefined, page: undefined })">
            Clear filters
          </Btn>
        </div>
      </div>

      <div
        v-else-if="!rows.length && scope === 'queue'"
        class="sec mt-6 rounded-md bg-surface/40 px-5 py-10 ring-1 ring-inset ring-line-subtle"
      >
        <p class="text-[13.5px] font-medium text-ink">Nothing is waiting on you</p>
        <p class="mt-1.5 max-w-[54ch] text-[12.5px] leading-relaxed text-ink-muted">
          No submitted report names you as its approver right now. Reports you wrote yourself are
          never counted here, so an empty queue does not mean there is no work — it means none of
          it is yours to decide.
        </p>
        <div class="mt-4 flex">
          <Btn size="sm" variant="secondary" @click="scope = 'mine'">Go to my reports</Btn>
        </div>
      </div>

      <div v-else-if="!rows.length" class="sec mt-6 rounded-md bg-surface/40 px-5 py-10 ring-1 ring-inset ring-line-subtle">
        <p class="text-[13.5px] font-medium text-ink">You have not written a report yet</p>
        <p class="mt-1.5 max-w-[54ch] text-[12.5px] leading-relaxed text-ink-muted">
          Pulse drafts one per repository per week from your synced GitHub activity. Nothing has
          been drafted or written under
          <span class="mono text-[12px] text-ink-muted">user_id {{ me?.id ?? "—" }}</span> so far.
        </p>
        <div class="mt-4 flex">
          <NuxtLink to="/reports/new"><Btn size="sm">New report</Btn></NuxtLink>
        </div>
      </div>

      <template v-else>
        <!-- `relative`: sr-only is position:absolute, and with no positioned ancestor
             the caption anchors to the page and widens the document. -->
        <div class="sec relative mt-1 overflow-x-auto" style="animation-delay: 80ms">
          <table class="w-full min-w-[560px] border-collapse text-left">
            <caption class="sr-only">
              {{ scope === "queue" ? "Reports awaiting your decision, newest week first." : "Reports you wrote, newest week first." }}
            </caption>
            <thead>
              <tr class="border-b border-line-subtle">
                <!-- The list endpoint orders by week_start desc, id desc and takes no
                     sort parameter, so this states the order rather than offering one. -->
                <th scope="col" aria-sort="descending" :class="[MONO_LABEL, 'py-2 pr-3 text-ink-faint']">Week</th>
                <th scope="col" :class="[MONO_LABEL, 'hidden py-2 pr-3 text-ink-faint sm:table-cell']">Repository</th>
                <th v-if="scope === 'queue'" scope="col" :class="[MONO_LABEL, 'hidden py-2 pr-3 text-ink-faint md:table-cell']">Author</th>
                <th scope="col" :class="[MONO_LABEL, 'py-2 pr-3 text-ink-faint']">Status</th>
                <th scope="col" :class="[MONO_LABEL, 'hidden py-2 pr-3 text-ink-faint md:table-cell']">Updated</th>
                <th scope="col" :class="[MONO_LABEL, 'py-2 text-right text-ink-faint']">Action</th>
              </tr>
            </thead>
            <tbody>
              <template v-for="(report, i) in rows" :key="report.id">
                <tr
                  :class="[
                    'sec border-b border-line-subtle/70',
                    open === report.id && 'bg-surface/60',
                    menu === report.id && 'relative z-40',
                  ]"
                  :style="`animation-delay: ${Math.min(i, 3) * 40}ms`"
                >
                  <td class="py-2.5 pr-3 align-middle">
                    <NuxtLink :to="`/reports/${report.id}`" :class="[FOCUS, 'block rounded transition-colors hover:text-ink']">
                      <span class="mono block text-[12px] text-ink">{{ formatDate(report.week_start) }}</span>
                      <span class="mono block text-[11px] text-ink-muted">report {{ report.id }}</span>
                    </NuxtLink>
                  </td>
                  <td class="hidden py-2.5 pr-3 align-middle sm:table-cell">
                    <span
                      class="mono text-[12px]"
                      :class="repositories.some((r) => r.id === report.repo_id) ? 'text-ink-muted' : 'italic text-ink-muted'"
                    >{{ repoName(report.repo_id) }}</span>
                  </td>
                  <td v-if="scope === 'queue'" class="hidden py-2.5 pr-3 align-middle md:table-cell">
                    <span class="flex items-center gap-2">
                      <Avatar :name="personName(report.author, report.author_user_id)" size="sm" />
                      <span class="min-w-0">
                        <span class="block truncate text-[12px] text-ink-muted">
                          {{ personName(report.author, report.author_user_id) }}
                        </span>
                        <span class="mono block text-[11px] text-ink-muted">user_id {{ report.author_user_id }}</span>
                      </span>
                    </span>
                  </td>
                  <td class="py-2.5 pr-3 align-middle">
                    <StatusDot :tone="statusTone(report.status)" quiet>{{ statusLabel(report.status) }}</StatusDot>
                  </td>
                  <td class="mono hidden py-2.5 pr-3 align-middle text-[11px] text-ink-muted md:table-cell">
                    {{ relativeTime(report.updated_at) }}
                  </td>
                  <td class="py-2.5 text-right align-middle">
                    <button
                      v-if="scope === 'queue'"
                      type="button"
                      :aria-expanded="open === report.id"
                      :aria-controls="`review-${report.id}`"
                      :class="[FOCUS, 'inline-flex items-center gap-1.5 rounded-md bg-sunken px-2.5 py-1.5 text-[12px] text-ink ring-1 ring-inset ring-line-subtle transition-colors hover:bg-surface-hover hover:ring-line']"
                      @click="open = open === report.id ? null : report.id"
                    >
                      {{ open === report.id ? "Close" : "Read and decide" }}
                      <Icon name="chevronDown" :class="['h-3.5 w-3.5 text-ink-faint transition-transform', open === report.id && 'rotate-180']" />
                    </button>

                    <span v-else class="inline-flex items-center justify-end gap-1">
                      <NuxtLink
                        :to="`/reports/${report.id}`"
                        :class="[FOCUS, 'rounded-md px-2 py-1.5 text-[12px] text-ink-muted transition-colors hover:bg-surface-hover hover:text-ink']"
                      >Open</NuxtLink>
                      <span class="relative inline-block" :ref="(el) => setMenuBox(el, report.id)">
                        <button
                          type="button"
                          aria-haspopup="menu"
                          :aria-expanded="menu === report.id"
                          :aria-label="`Actions for report ${report.id}`"
                          :class="[FOCUS, 'rounded-md px-2 py-1.5 text-[13px] leading-none text-ink-muted transition-colors hover:bg-surface-hover hover:text-ink']"
                          @click="menu = menu === report.id ? null : report.id"
                        >⋯</button>
                        <span
                          v-if="menu === report.id"
                          role="menu"
                          :aria-label="`Report ${report.id}`"
                          class="xfade absolute right-0 top-full z-40 mt-1 block w-[190px] overflow-hidden rounded-md bg-surface p-1 text-left shadow-2xl ring-1 ring-line"
                        >
                          <NuxtLink
                            role="menuitem"
                            :to="`/reports/${report.id}`"
                            :class="[FOCUS, 'block w-full rounded-md px-2.5 py-2 text-left text-[12.5px] text-ink transition-colors hover:bg-surface-hover']"
                          >Edit</NuxtLink>
                          <button
                            type="button"
                            role="menuitem"
                            :disabled="report.status !== 'draft' && report.status !== 'changes_requested'"
                            :class="[FOCUS, 'block w-full rounded-md px-2.5 py-2 text-left text-[12.5px] text-ink transition-colors enabled:hover:bg-surface-hover disabled:cursor-default disabled:opacity-40']"
                            @click="submitForReview(report)"
                          >Submit for review</button>
                          <button
                            type="button"
                            role="menuitem"
                            :disabled="report.status !== 'draft'"
                            :class="[FOCUS, 'block w-full rounded-md px-2.5 py-2 text-left text-[12.5px] text-bad transition-colors enabled:hover:bg-bad-surface disabled:cursor-default disabled:opacity-40']"
                            @click="menu = null; confirmDelete = report"
                          >Delete draft</button>
                        </span>
                      </span>
                    </span>
                  </td>
                </tr>

                <!-- Stays mounted so both directions animate and aria-controls always
                     points at something real. Controls are disabled while collapsed:
                     clipped content is otherwise still in the tab order. -->
                <tr v-if="scope === 'queue'" :class="['border-line-subtle/70', open === report.id && 'border-b bg-surface/60']">
                  <td :id="`review-${report.id}`" :colspan="6" class="p-0">
                    <div class="sec-collapse" :data-open="open === report.id ? 'true' : 'false'" :aria-hidden="open !== report.id">
                      <div>
                        <div class="grid gap-5 px-0 pb-4 pt-1 lg:grid-cols-[minmax(0,1fr)_300px]">
                          <div class="min-w-0 space-y-4">
                            <div v-for="field in REPORT_FIELDS" :key="field.key">
                              <Eyebrow>{{ field.label }}</Eyebrow>
                              <p class="mt-1.5 max-w-[74ch] whitespace-pre-wrap text-[12.5px] leading-relaxed text-ink">
                                <template v-if="report[field.key]">{{ report[field.key] }}</template>
                                <span v-else class="italic text-ink-muted">Not written.</span>
                              </p>
                            </div>

                            <div>
                              <Eyebrow>Drafted from</Eyebrow>
                              <div
                                v-if="open === report.id && evidence"
                                class="mt-1.5 flex flex-wrap gap-x-5 gap-y-1.5 text-[12px] text-ink-muted"
                              >
                                <span><span class="mono text-ink">{{ evidence.counts.commits }}</span> commits</span>
                                <span><span class="mono text-ink">{{ evidence.counts.pull_requests }}</span> pull requests</span>
                                <span><span class="mono text-ink">{{ evidence.counts.reviews }}</span> reviews</span>
                                <span><span class="mono text-ink">{{ evidence.counts.issues }}</span> issues</span>
                                <span class="mono">week of {{ formatDate(report.week_start) }}</span>
                              </div>
                              <p v-else-if="open === report.id && evidenceFailed" class="mt-1.5 text-[12px] italic text-ink-muted">
                                The activity counts came back empty, so this report cannot be checked
                                against the week it claims to describe.
                              </p>
                              <p v-else class="mt-1.5 text-[12px] text-ink-muted">Reading the week…</p>
                            </div>
                          </div>

                          <ReportDecision
                            :report-id="report.id"
                            :allowed="verdict(report).allowed"
                            :reason="verdict(report).reason"
                            :author-name="personName(report.author, report.author_user_id)"
                            :busy="decide.isPending.value"
                            :active="open === report.id"
                            @decide="(decision, note) => decide.mutate({ id: report.id, decision, note })"
                          />
                        </div>
                      </div>
                    </div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>

        <div class="sec mt-4 flex flex-wrap items-center gap-3 border-t border-line-subtle pt-3" style="animation-delay: 120ms">
          <p class="mono text-[11px] text-ink-muted">
            {{ offset + 1 }}–{{ Math.min(offset + PER_PAGE, total) }} of {{ total }}
            <span v-if="filtering"> · filtered</span>
          </p>
          <div class="ml-auto flex items-center gap-1.5">
            <button
              type="button"
              :disabled="page === 0"
              :class="[FOCUS, 'rounded-md px-2.5 py-1.5 text-[12px] text-ink-muted ring-1 ring-inset ring-line-subtle transition-colors enabled:hover:bg-surface-hover enabled:hover:text-ink disabled:opacity-40']"
              @click="page = Math.max(0, page - 1)"
            >Previous</button>
            <span class="mono px-1 text-[11px] text-ink-muted">page {{ page + 1 }} of {{ pages }}</span>
            <button
              type="button"
              :disabled="page + 1 >= pages"
              :class="[FOCUS, 'rounded-md px-2.5 py-1.5 text-[12px] text-ink-muted ring-1 ring-inset ring-line-subtle transition-colors enabled:hover:bg-surface-hover enabled:hover:text-ink disabled:opacity-40']"
              @click="page = page + 1"
            >Next</button>
          </div>
        </div>
      </template>
    </TabPanel>

    <Modal
      :open="confirmDelete !== null"
      title="Delete this draft?"
      :description="confirmDelete ? `Report ${confirmDelete.id} for ${repoName(confirmDelete.repo_id)}, week of ${formatDate(confirmDelete.week_start)}. Drafts are only visible to you, so nobody else has read it — but deleting cannot be undone.` : undefined"
      :close-on-backdrop="false"
      @close="confirmDelete = null"
    >
      <p class="text-[12.5px] leading-relaxed text-ink-muted">
        Pulse can draft a new one for this week from your synced activity, but anything you typed
        into this draft goes with it.
      </p>
      <template #footer>
        <Btn size="sm" variant="ghost" @click="confirmDelete = null">Keep it</Btn>
        <Btn
          size="sm"
          variant="destructive"
          :busy="remove.isPending.value"
          @click="confirmDelete && remove.mutate(confirmDelete.id)"
        >Delete draft</Btn>
      </template>
    </Modal>
  </PulseShell>
</template>
