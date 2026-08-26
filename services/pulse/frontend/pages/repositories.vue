<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import type { SelectOption, TabItem } from "@crescent/ui/types/ui";
import type {
  ApproverCandidateList,
  DepartmentResponse,
  Page,
  ReportResponse,
  RepositoryResponse,
  UserMeResponse,
} from "~/types/api";

definePageMeta({ middleware: "auth" });

/* The screen the whole approval flow depends on. A repository arrives from the sync with
   no department and nobody named; in that state a report about it belongs to no
   department and only a platform admin can decide it. */

const auth = useAuth();
const api = useApi();
const identity = useIdentityApi();
const route = useRoute();
const router = useRouter();
const queryClient = useQueryClient();
const announce = useAnnounce();
const { show: showToast } = useToast();
const { repositories, isPending, isError, error } = useRepositories();

const me = computed(() => auth.user.value as UserMeResponse | null);
const canFile = computed(
  () => !!me.value && (me.value.is_platform_admin || (me.value.memberships ?? []).some((m) => m.role === "admin")),
);

const { data: unfiled, isError: unfiledFailed } = useQuery({
  queryKey: ["repositories", "unfiled"],
  enabled: canFile,
  queryFn: () =>
    api.request<Page<RepositoryResponse>>("/github/repositories/unfiled", { query: { limit: 50, offset: 0 } }),
});

// Departments come from identity; Pulse holds no copy of them, only the ids.
const { data: departments, isError: deptsFailed } = useQuery({
  queryKey: ["departments"],
  queryFn: () => identity.request<DepartmentResponse[]>("/departments"),
});

const deptName = computed(() => {
  const map = new Map<number, string>();
  for (const dept of departments.value ?? []) map.set(dept.id, dept.name);
  return map;
});

const deptOptions = computed<SelectOption[]>(() =>
  (departments.value ?? []).map((d) => ({ value: String(d.id), label: d.name })),
);

const needsFiling = computed(() => unfiled.value?.items ?? []);

/* ── search, filter, sort ──────────────────────────────────────────────────── */

const query = ref("");
const filter = ref<"all" | "unfiled" | "untracked">("all");
const sort = ref<"name" | "synced" | "reports">("name");
const dir = ref<"asc" | "desc">("asc");

const untrackedRows = computed(() => repositories.value.filter((r) => !r.is_tracked));

const tabs = computed<TabItem[]>(() => [
  { id: "all", label: "All", hint: String(repositories.value.length) },
  { id: "unfiled", label: "Unfiled", hint: String(repositories.value.filter((r) => r.dept_id === null).length) },
  { id: "untracked", label: "Not tracked", hint: String(untrackedRows.value.length) },
]);

// One report count per repository, read from /reports so the number is real rather than
// inferred. Cheap: limit=1, only `total` is used.
const { data: reportCounts } = useQuery({
  queryKey: computed(() => ["report-counts", repositories.value.map((r) => r.id).join(",")]),
  enabled: computed(() => repositories.value.length > 0),
  queryFn: async () => {
    const out: Record<number, number> = {};
    await Promise.all(
      repositories.value.map(async (repo) => {
        try {
          const res = await api.request<Page<ReportResponse>>("/reports", {
            query: { repo_id: repo.id, limit: 1, offset: 0 },
          });
          out[repo.id] = res.total;
        } catch {
          // A repository you cannot list reports for keeps an unknown count rather
          // than a fabricated zero.
        }
      }),
    );
    return out;
  },
});

function reportCount(repoId: number): number | null {
  const counts = reportCounts.value;
  return counts && repoId in counts ? counts[repoId]! : null;
}

const shown = computed(() => {
  const needle = query.value.trim().toLowerCase();
  let rows = repositories.value;
  if (filter.value === "unfiled") rows = rows.filter((r) => r.dept_id === null);
  if (filter.value === "untracked") rows = rows.filter((r) => !r.is_tracked);
  if (needle) {
    rows = rows.filter((r) =>
      [
        r.full_name,
        r.dept_id === null ? "unfiled" : deptName.value.get(r.dept_id) ?? "",
        approverLabel(r),
      ]
        .join(" ")
        .toLowerCase()
        .includes(needle),
    );
  }
  const sign = dir.value === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    if (sort.value === "name") return sign * a.full_name.localeCompare(b.full_name);
    if (sort.value === "synced") {
      return sign * (Date.parse(a.last_synced_at ?? "") || 0) - sign * (Date.parse(b.last_synced_at ?? "") || 0);
    }
    return sign * ((reportCount(a.id) ?? -1) - (reportCount(b.id) ?? -1));
  });
});

function toggleSort(next: "name" | "synced" | "reports") {
  if (sort.value === next) {
    dir.value = dir.value === "asc" ? "desc" : "asc";
  } else {
    sort.value = next;
    dir.value = "asc";
  }
}

function ariaSort(column: "name" | "synced" | "reports"): "ascending" | "descending" | "none" {
  if (sort.value !== column) return "none";
  return dir.value === "asc" ? "ascending" : "descending";
}

/* ── the open row ──────────────────────────────────────────────────────────── */

const openRow = computed({
  get: () => (route.query.open ? Number(route.query.open) : null),
  set: (value) =>
    router.replace({ query: { ...route.query, open: value === null ? undefined : String(value) } }),
});

const { data: candidates, isPending: candidatesPending } = useQuery({
  queryKey: computed(() => ["repositories", openRow.value ?? "none", "approver-candidates"]),
  enabled: computed(() => openRow.value !== null),
  queryFn: () =>
    api.request<ApproverCandidateList>(`/github/repositories/${openRow.value}/approver-candidates`),
});

const { data: rowReports } = useQuery({
  queryKey: computed(() => ["reports", "for-repo-panel", openRow.value ?? "none"]),
  enabled: computed(() => openRow.value !== null),
  queryFn: () =>
    api.request<Page<ReportResponse>>("/reports", { query: { repo_id: openRow.value, limit: 5, offset: 0 } }),
});

/* ── the writes ────────────────────────────────────────────────────────────── */

// Keyed per write so two rows can be saving independently.
const busy = ref<string | null>(null);
const approverError = ref<string | null>(null);

function invalidateRepos() {
  queryClient.invalidateQueries({ queryKey: ["repositories"] });
  // Reports carry a denormalised dept_id, so filing a repo restamps them, and changing
  // a post changes who can decide. Both queues can be stale.
  queryClient.invalidateQueries({ queryKey: ["reports"] });
  queryClient.invalidateQueries({ queryKey: ["review-queue"] });
  queryClient.invalidateQueries({ queryKey: ["report-totals"] });
}

const fileRepo = useMutation({
  mutationFn: (vars: { repoId: number; deptId: number }) =>
    api.request<RepositoryResponse>(`/github/repositories/${vars.repoId}/department/${vars.deptId}`, {
      method: "PUT",
    }),
  onMutate: (vars) => {
    busy.value = `file-${vars.repoId}`;
  },
  onSuccess: (_res, vars) => {
    busy.value = null;
    invalidateRepos();
    showToast(
      `Filed under ${deptName.value.get(vars.deptId) ?? `department ${vars.deptId}`}. Reports already written about it moved too.`,
      "ok",
    );
  },
  onError: (err) => {
    busy.value = null;
    showToast(
      httpStatus(err) === 403
        ? "403 · filing a repository needs department admin or platform admin."
        : apiMessage(err, "Could not file that repository."),
      "bad",
    );
  },
});

const fileDraft = ref<Record<number, string>>({});

// The API rejects one person holding both posts, so a straight swap has to vacate the
// clashing post before claiming it, or the first call 400s on the old value.
const saveApprovers = useMutation({
  mutationFn: async (vars: { repo: RepositoryResponse; lead: number | null; deputy: number | null }) => {
    const base = `/github/repositories/${vars.repo.id}`;
    if (vars.lead !== null && vars.lead === vars.repo.deputy_user_id) {
      await api.request<RepositoryResponse>(`${base}/deputy`, { method: "DELETE" });
    }
    if (vars.deputy !== null && vars.deputy === vars.repo.lead_user_id) {
      await api.request<RepositoryResponse>(`${base}/lead`, { method: "DELETE" });
    }
    if (vars.lead !== vars.repo.lead_user_id) {
      await (vars.lead === null
        ? api.request<RepositoryResponse>(`${base}/lead`, { method: "DELETE" })
        : api.request<RepositoryResponse>(`${base}/lead/${vars.lead}`, { method: "PUT" }));
    }
    if (vars.deputy !== vars.repo.deputy_user_id) {
      await (vars.deputy === null
        ? api.request<RepositoryResponse>(`${base}/deputy`, { method: "DELETE" })
        : api.request<RepositoryResponse>(`${base}/deputy/${vars.deputy}`, { method: "PUT" }));
    }
  },
  onMutate: (vars) => {
    approverError.value = null;
    busy.value = `approvers-${vars.repo.id}`;
  },
  onSuccess: () => {
    busy.value = null;
    invalidateRepos();
    showToast("Posts saved. Who can decide a report here has changed.", "ok");
  },
  onError: (err) => {
    busy.value = null;
    approverError.value = apiMessage(err, "Could not change the posts.");
  },
});

const setTracking = useMutation({
  mutationFn: (vars: { repoId: number; tracked: boolean }) =>
    api.request<RepositoryResponse>(`/github/repositories/${vars.repoId}/tracked`, {
      method: vars.tracked ? "PUT" : "DELETE",
    }),
  onMutate: (vars) => {
    busy.value = `track-${vars.repoId}`;
  },
  onSuccess: (_res, vars) => {
    busy.value = null;
    untrackTarget.value = null;
    invalidateRepos();
    showToast(vars.tracked ? "Tracking resumed from the stored cursor." : "The next run will record it as skipped.", "muted");
  },
  onError: (err) => {
    busy.value = null;
    untrackTarget.value = null;
    showToast(apiMessage(err, "Could not change tracking."), "bad");
  },
});

const untrackTarget = ref<RepositoryResponse | null>(null);

watch(filter, (next) => {
  const n = next === "all"
    ? repositories.value.length
    : next === "unfiled"
      ? repositories.value.filter((r) => r.dept_id === null).length
      : untrackedRows.value.length;
  announce(`${n} repositories in this filter`);
});
</script>

<template>
  <PulseShell :readout="`${repositories.length} repositories`">
    <header class="sec flex flex-wrap items-end justify-between gap-4">
      <div class="min-w-0">
        <Eyebrow>Pulse · repositories</Eyebrow>
        <h1 class="mt-3 text-[clamp(1.5rem,2.2vw,1.9rem)] font-semibold leading-[1.05] tracking-[-0.035em]">
          Repositories
        </h1>
        <p class="mt-1.5 max-w-[72ch] text-[12.5px] leading-relaxed text-ink-muted">
          A repository arrives from the sync with no department and nobody named. Until it has
          both, a report written about it belongs to no department and only a platform admin can
          decide it. Filing it and naming a lead are the two writes that put it back inside the
          approval flow.
        </p>
      </div>
      <p class="mono flex shrink-0 items-center gap-2 rounded-md bg-sunken px-2.5 py-2 text-[12px] ring-1 ring-inset ring-line-subtle">
        <span :class="[MONO_LABEL, 'text-ink-faint']">get</span>
        <span class="text-ink">/github/repositories</span>
        <span class="hidden text-ink-muted sm:inline">?limit=50&offset=0</span>
      </p>
    </header>

    <!-- The unfiled queue. -->
    <section
      v-if="canFile"
      class="sec mt-8 rounded-md bg-surface/40 px-5 py-5 ring-1 ring-inset ring-line-subtle"
      style="animation-delay: 40ms"
      aria-labelledby="unfiled-heading"
    >
      <Eyebrow>Unfiled queue</Eyebrow>
      <!-- An unread queue is not an empty one. When the call fails this used to count zero
           and then say every repository has a department, which is a claim the page has no
           standing to make. -->
      <h2 id="unfiled-heading" class="mt-2 text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">
        <template v-if="unfiledFailed">The unfiled queue could not be read</template>
        <template v-else>
          {{ needsFiling.length }} {{ needsFiling.length === 1 ? "repository has" : "repositories have" }} no department
        </template>
      </h2>

      <p v-if="unfiledFailed" role="alert" class="mt-2 max-w-[80ch] text-[12.5px] leading-relaxed text-ink-muted">
        Pulse did not answer, so how many repositories are waiting to be filed is unknown. Nothing
        was changed.
      </p>

      <p v-else-if="!needsFiling.length" class="mt-2 max-w-[80ch] text-[12.5px] leading-relaxed text-ink-muted">
        Every repository has a department. New ones appear here after the next sync finds them.
      </p>

      <template v-else>
        <p class="mt-2 max-w-[80ch] text-[12.5px] leading-relaxed text-ink-muted">
          These are synced and being read, but they are not attached to anything. A report written
          about one of them is stamped with no department, so it never reaches a department's
          review queue and no department admin inherits the right to decide it. Filing one
          restamps the reports already written about it, which is why a stranded report can become
          reviewable without being rewritten.
        </p>

        <ul class="mt-4 divide-y divide-line-subtle border-t border-line-subtle">
          <li
            v-for="repo in needsFiling"
            :key="repo.id"
            class="flex flex-wrap items-center justify-between gap-3 py-3"
          >
            <div class="min-w-0">
              <p class="mono text-[12.5px] text-ink">{{ repo.full_name }}</p>
              <p class="mt-0.5 text-[12px] text-ink-muted">
                {{ approverLabel(repo) }} ·
                <template v-if="reportCount(repo.id) === null">report count unavailable</template>
                <template v-else>{{ reportCount(repo.id) }} reports already written</template>
              </p>
            </div>
            <div class="flex shrink-0 items-center gap-2">
              <Select
                class="w-[220px]"
                :label="`Department for ${repo.full_name}`"
                placeholder="Choose a department"
                :model-value="fileDraft[repo.id] ?? ''"
                :options="deptOptions"
                :disabled="deptsFailed"
                @update:model-value="fileDraft[repo.id] = $event"
              />
              <Btn
                size="sm"
                :disabled="!fileDraft[repo.id]"
                :busy="busy === `file-${repo.id}`"
                @click="fileRepo.mutate({ repoId: repo.id, deptId: Number(fileDraft[repo.id]) })"
              >File</Btn>
            </div>
          </li>
        </ul>

        <p v-if="deptsFailed" role="alert" class="mt-3 text-[12.5px] text-bad">
          The department list comes from identity and did not load, so there is nothing to file
          these under yet.
        </p>

        <!-- One unbreakable token: without `break-all` the path spills out of the panel's
             padding at 390px, since normal wrapping has nowhere to break it. -->
        <p class="mono mt-3 break-all text-[12px] text-ink-faint">
          put /github/repositories/{repo_id}/department/{dept_id}
        </p>
      </template>
    </section>

    <!-- Search and filter. -->
    <div class="sec mt-8 flex flex-wrap items-center gap-3" style="animation-delay: 80ms">
      <label
        :class="[
          'flex min-w-[280px] flex-1 items-center gap-2 rounded-md bg-sunken px-2.5 py-2 ring-1 ring-inset ring-line-subtle focus-within:ring-line',
        ]"
      >
        <Icon name="search" class="h-3.5 w-3.5 shrink-0 text-ink-faint" />
        <span class="sr-only">Search repositories</span>
        <input
          v-model="query"
          type="search"
          autocomplete="off"
          placeholder="Repository, department or approver"
          class="w-full bg-transparent text-[12.5px] text-ink outline-none placeholder:text-ink-faint"
        />
        <button
          v-if="query"
          type="button"
          aria-label="Clear search"
          :class="[FOCUS, 'rounded p-0.5 text-ink-faint transition-colors hover:text-ink']"
          @click="query = ''"
        >
          <Icon name="x" class="h-3.5 w-3.5" />
        </button>
      </label>
      <p class="mono text-[12px] text-ink-muted">{{ shown.length }} of {{ repositories.length }} shown</p>
    </div>

    <div class="sec mt-4" style="animation-delay: 80ms">
      <Tabs
        id="repos"
        :model-value="filter"
        label="Repository filter"
        :items="tabs"
        @update:model-value="filter = $event as 'all' | 'unfiled' | 'untracked'"
      />
    </div>

    <p v-if="isPending" class="mt-6 text-[12.5px] text-ink-muted">Loading repositories…</p>

    <div v-else-if="isError" role="alert" class="mt-6 rounded-md bg-bad-surface px-5 py-6">
      <p class="text-[13.5px] font-medium text-ink">Could not load repositories</p>
      <p class="mt-1.5 max-w-[62ch] text-[12.5px] leading-relaxed text-ink-muted">
        {{ apiMessage(error, "The Pulse API did not answer. Check that the service is running.") }}
      </p>
      <div class="mt-4 flex">
        <Btn size="sm" variant="secondary" @click="queryClient.invalidateQueries({ queryKey: ['repositories'] })">
          Try again
        </Btn>
      </div>
    </div>

    <div v-else-if="!shown.length" class="sec mt-6 rounded-md bg-surface/40 px-5 py-10 ring-1 ring-inset ring-line-subtle">
      <p class="text-[13.5px] font-medium text-ink">No repository matches</p>
      <p class="mt-1.5 max-w-[54ch] text-[12.5px] leading-relaxed text-ink-muted">
        {{ repositories.length }} repositories are visible to you, none of them matching what you
        have narrowed to.
      </p>
      <div class="mt-4 flex">
        <Btn size="sm" variant="secondary" @click="query = ''; filter = 'all'">Clear search and filter</Btn>
      </div>
    </div>

    <!-- This scroller used to slice the department listbox in half — overflow-x:auto clips
         the y axis too — and carried a pair of padding/margin rules to grow past the popup.
         `Select` now teleports its listbox to <body> and positions it from the trigger's own
         rect, so the scroller is just a scroller again. -->
    <div v-else class="sec relative mt-1 overflow-x-auto" style="animation-delay: 120ms">
      <table class="w-full min-w-[820px] border-collapse text-left">
        <caption class="sr-only">
          Synced repositories, their department, their named approvers and their sync state.
        </caption>
        <thead>
          <tr class="border-b border-line-subtle">
            <th scope="col" :aria-sort="ariaSort('name')" class="py-2 pr-3">
              <button
                type="button"
                :class="[FOCUS, MONO_LABEL, 'inline-flex items-center gap-1 rounded transition-colors', sort === 'name' ? 'text-ink' : 'text-ink-faint hover:text-ink']"
                @click="toggleSort('name')"
              >
                Repository
                <Icon name="chevronDown" :class="['h-3 w-3 transition-transform', sort !== 'name' && 'opacity-0', sort === 'name' && dir === 'asc' && 'rotate-180']" />
              </button>
            </th>
            <th scope="col" :class="[MONO_LABEL, 'px-3 py-2 text-ink-faint']">Department</th>
            <th scope="col" :class="[MONO_LABEL, 'px-3 py-2 text-ink-faint']">Approvers</th>
            <th scope="col" :class="[MONO_LABEL, 'px-3 py-2 text-ink-faint']">Tracking</th>
            <th scope="col" :aria-sort="ariaSort('synced')" class="px-3 py-2">
              <button
                type="button"
                :class="[FOCUS, MONO_LABEL, 'inline-flex items-center gap-1 rounded transition-colors', sort === 'synced' ? 'text-ink' : 'text-ink-faint hover:text-ink']"
                @click="toggleSort('synced')"
              >
                Last synced
                <Icon name="chevronDown" :class="['h-3 w-3 transition-transform', sort !== 'synced' && 'opacity-0', sort === 'synced' && dir === 'asc' && 'rotate-180']" />
              </button>
            </th>
            <th scope="col" :aria-sort="ariaSort('reports')" class="px-3 py-2">
              <button
                type="button"
                :class="[FOCUS, MONO_LABEL, 'inline-flex items-center gap-1 rounded transition-colors', sort === 'reports' ? 'text-ink' : 'text-ink-faint hover:text-ink']"
                @click="toggleSort('reports')"
              >
                Reports
                <Icon name="chevronDown" :class="['h-3 w-3 transition-transform', sort !== 'reports' && 'opacity-0', sort === 'reports' && dir === 'asc' && 'rotate-180']" />
              </button>
            </th>
            <th scope="col" class="py-2 pl-3"><span class="sr-only">Manage</span></th>
          </tr>
        </thead>
        <tbody>
          <template v-for="(repo, i) in shown" :key="repo.id">
            <tr class="sec border-b border-line-subtle/70 align-top" :style="`animation-delay: ${Math.min(i, 3) * 40}ms`">
              <td class="py-3 pr-3">
                <span class="mono text-[12.5px] text-ink">{{ repo.full_name }}</span>
                <span class="mono mt-1 block text-[12px] text-ink-muted">
                  repo_id {{ repo.id }} · {{ repo.default_branch ?? "no default branch" }} ·
                  {{ repo.private ? "private" : "public" }}
                </span>
              </td>
              <td class="px-3 py-3 text-[12.5px]">
                <span v-if="repo.dept_id !== null" class="text-ink">
                  {{ deptName.get(repo.dept_id) ?? `department ${repo.dept_id}` }}
                </span>
                <StatusDot v-else tone="warn">Unfiled</StatusDot>
              </td>
              <td class="px-3 py-3 text-[12.5px]">
                <template v-if="repo.lead_user_id === null && repo.deputy_user_id === null">
                  <span class="text-ink-muted">Nobody named</span>
                </template>
                <template v-else>
                  <span v-if="repo.lead_user_id !== null" class="block text-ink">
                    {{ personName(repo.lead, repo.lead_user_id) }}
                    <span class="mono text-[12px] text-ink-faint">lead</span>
                  </span>
                  <span v-if="repo.deputy_user_id !== null" class="block text-ink-muted">
                    {{ personName(repo.deputy, repo.deputy_user_id) }}
                    <span class="mono text-[12px] text-ink-faint">deputy</span>
                  </span>
                </template>
              </td>
              <td class="px-3 py-3">
                <StatusDot :tone="repo.is_tracked ? 'ok' : 'muted'" quiet>
                  {{ repo.is_tracked ? "Tracked" : "Not tracked" }}
                </StatusDot>
              </td>
              <td class="mono whitespace-nowrap px-3 py-3 text-[12px] text-ink-muted">
                {{ formatStamp(repo.last_synced_at) }}
              </td>
              <td class="mono px-3 py-3 text-[12px] text-ink-muted">
                {{ reportCount(repo.id) ?? "—" }}
              </td>
              <td class="py-3 pl-3 text-right">
                <button
                  type="button"
                  :aria-expanded="openRow === repo.id"
                  :aria-controls="`repo-panel-${repo.id}`"
                  :class="[FOCUS, TAP, 'inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-[12px] text-ink-muted transition-colors hover:bg-surface-hover hover:text-ink']"
                  @click="openRow = openRow === repo.id ? null : repo.id"
                >
                  {{ openRow === repo.id ? "Close" : "Manage" }}
                  <Icon name="chevronDown" :class="['h-3.5 w-3.5 transition-transform duration-150', openRow === repo.id && 'rotate-180']" />
                </button>
              </td>
            </tr>

            <tr class="border-b border-line-subtle/70">
              <td :colspan="7" class="p-0">
                <div :id="`repo-panel-${repo.id}`" class="sec-collapse" :data-open="openRow === repo.id ? 'true' : 'false'" :aria-hidden="openRow !== repo.id">
                  <!-- `.sec-collapse > *` clips so the 0fr → 1fr row can animate. It no longer
                       has to make an exception for an open listbox: `Select` teleports its
                       popup to <body>, so nothing in here can clip it. -->
                  <div>
                    <div class="grid gap-6 bg-sunken/50 px-4 py-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                      <div class="min-w-0">
                        <ApproverPicker
                          v-if="canAdminRepo(repo, me)"
                          :repo="repo"
                          :candidates="openRow === repo.id ? candidates?.items ?? [] : []"
                          :pending="openRow === repo.id && candidatesPending"
                          :busy="busy === `approvers-${repo.id}`"
                          :active="openRow === repo.id"
                          :server-error="approverError"
                          @save="(lead, deputy) => saveApprovers.mutate({ repo, lead, deputy })"
                        />
                        <p v-else class="max-w-[62ch] text-[12.5px] leading-relaxed text-ink-muted">
                          Naming a lead or deputy needs department admin on the department this
                          repository is filed to, or platform admin. You can read the posts above.
                        </p>

                        <div class="mt-4 flex flex-wrap items-center gap-2 border-t border-line-subtle pt-4">
                          <template v-if="repo.dept_id === null">
                            <Select
                              class="w-[200px]"
                              :label="`Department for ${repo.full_name}`"
                              placeholder="Choose a department"
                              :disabled="openRow !== repo.id || !canFile"
                              :model-value="fileDraft[repo.id] ?? ''"
                              :options="deptOptions"
                              @update:model-value="fileDraft[repo.id] = $event"
                            />
                            <Btn
                              size="sm"
                              variant="secondary"
                              :disabled="openRow !== repo.id || !fileDraft[repo.id]"
                              :busy="busy === `file-${repo.id}`"
                              @click="fileRepo.mutate({ repoId: repo.id, deptId: Number(fileDraft[repo.id]) })"
                            >File to department</Btn>
                          </template>
                          <template v-else>
                            <p class="text-[12px] text-ink-muted">
                              Filed under
                              <span class="text-ink">{{ deptName.get(repo.dept_id) ?? `department ${repo.dept_id}` }}</span
                              >. Refiling moves every report written about it too.
                            </p>
                            <Select
                              class="w-[180px]"
                              :label="`Move ${repo.full_name} to another department`"
                              placeholder="Move to…"
                              :disabled="openRow !== repo.id || !canAdminRepo(repo, me)"
                              model-value=""
                              :options="deptOptions.filter((o) => o.value !== String(repo.dept_id))"
                              @update:model-value="fileRepo.mutate({ repoId: repo.id, deptId: Number($event) })"
                            />
                          </template>

                          <Btn
                            v-if="repo.is_tracked"
                            size="sm"
                            variant="destructive"
                            :disabled="openRow !== repo.id || !canAdminRepo(repo, me)"
                            @click="untrackTarget = repo"
                          >Stop tracking</Btn>
                          <Btn
                            v-else
                            size="sm"
                            variant="secondary"
                            :disabled="openRow !== repo.id || !canAdminRepo(repo, me)"
                            :busy="busy === `track-${repo.id}`"
                            @click="setTracking.mutate({ repoId: repo.id, tracked: true })"
                          >Track again</Btn>
                        </div>
                      </div>

                      <div class="min-w-0">
                        <Eyebrow>Reports written about it</Eyebrow>
                        <p
                          v-if="openRow === repo.id && !(rowReports?.items ?? []).length"
                          class="mt-2 max-w-[58ch] text-[12.5px] leading-relaxed text-ink-muted"
                        >
                          Nothing yet. Synced activity exists on its own — a report only appears
                          once somebody drafts one for a week.
                        </p>
                        <ul v-else-if="openRow === repo.id" class="mt-2.5 divide-y divide-line-subtle border-y border-line-subtle">
                          <li v-for="report in rowReports?.items ?? []" :key="report.id">
                            <NuxtLink
                              :to="`/reports/${report.id}`"
                              :class="[FOCUS, TAP, 'flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-1 py-2.5 text-left transition-colors hover:bg-surface-hover']"
                            >
                              <span class="mono text-[12px] text-ink">#{{ report.id }}</span>
                              <span class="mono text-[12px] text-ink-muted">{{ formatDate(report.week_start) }}</span>
                              <span class="min-w-0 flex-1 truncate text-[12px] text-ink-muted">
                                {{ personName(report.author, report.author_user_id) }}
                              </span>
                              <span :class="['inline-flex items-center rounded px-2 py-1 text-[12px]', statusClass(report.status)]">
                                {{ statusLabel(report.status) }}
                              </span>
                            </NuxtLink>
                          </li>
                        </ul>
                        <p v-if="openRow === repo.id && (rowReports?.total ?? 0) > 5" class="mono mt-2.5 text-[12px] text-ink-muted">
                          5 of {{ rowReports?.total }} shown · get /reports?repo_id={{ repo.id }}
                        </p>

                        <div class="mt-4 flex flex-wrap gap-2">
                          <NuxtLink :to="`/reports/new?repo=${repo.id}`">
                            <Btn size="sm" variant="secondary" :disabled="openRow !== repo.id">New report</Btn>
                          </NuxtLink>
                          <NuxtLink :to="`/sync?repo=${repo.id}`">
                            <Btn size="sm" variant="ghost" :disabled="openRow !== repo.id">Sync history</Btn>
                          </NuxtLink>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>

    <p class="mt-6 max-w-[86ch] text-[12.5px] leading-relaxed text-ink-muted">
      You see a repository once you have worked in it, lead or deputise it, or administer the
      department it is filed to. A short list here is not the whole GitHub organisation — it is the
      part of it you have standing over.
    </p>

    <!-- Untracking is a real consequence, so it asks. -->
    <Modal
      :open="untrackTarget !== null"
      title="Stop tracking this repository?"
      :description="untrackTarget ? `${untrackTarget.full_name} stays in Pulse. What stops is the sync visiting it.` : undefined"
      :close-on-backdrop="false"
      @close="untrackTarget = null"
    >
      <ul class="space-y-2 text-[12.5px] leading-relaxed text-ink-muted">
        <li class="flex gap-2">
          <span class="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-ink-faint" aria-hidden="true" />
          The next run records it as <span class="mono text-[12px] text-ink">skipped</span> instead
          of fetching it, so no new commits, pull requests or issues arrive.
        </li>
        <li class="flex gap-2">
          <span class="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-ink-faint" aria-hidden="true" />
          Activity already synced stays, and so do the
          <span class="mono text-[12px] text-ink">{{ untrackTarget ? reportCount(untrackTarget.id) ?? "?" : 0 }}</span>
          reports written about it.
        </li>
        <li class="flex gap-2">
          <span class="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-ink-faint" aria-hidden="true" />
          A report drafted from now on draws on a stale week, because the week it summarises stops
          being filled in.
        </li>
        <li class="flex gap-2">
          <span class="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-ink-faint" aria-hidden="true" />
          Its department and its named posts are left alone. Tracking it again resumes from the
          stored cursor, so the gap is refetched rather than lost.
        </li>
      </ul>
      <template #footer>
        <Btn size="sm" variant="ghost" @click="untrackTarget = null">Keep tracking</Btn>
        <Btn
          size="sm"
          variant="destructive"
          :busy="busy !== null"
          @click="untrackTarget && setTracking.mutate({ repoId: untrackTarget.id, tracked: false })"
        >Stop tracking</Btn>
      </template>
    </Modal>
  </PulseShell>
</template>
