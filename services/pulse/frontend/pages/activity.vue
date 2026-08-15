<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import type { SelectOption } from "@crescent/ui/types/ui";
import type { ActivityResponse, GitHubAccountResponse, UserMeResponse } from "~/types/api";

definePageMeta({ middleware: "auth" });

/* Built against exactly what /activity returns: four exact counts and four lists capped
   at ten rows, with two query parameters. There is no per-day series in the payload, so
   nothing here looks like a chart — ten rows could not honestly draw a thirty-day line. */

const auth = useAuth();
const api = useApi();
const route = useRoute();
const router = useRouter();
const { repositories, repoName } = useRepositories();
const { others: teammates, hasDepartment } = useTeammates();
const announce = useAnnounce();

const PERIODS = [7, 30, 90] as const;
type Kind = "commits" | "pull_requests" | "reviews" | "issues";

// Filter state lives in the query string: "send me the link to Ada's last 90 days" is a
// real request, and a ref cannot answer it.
const subjectId = computed({
  get: () => (route.query.user ? Number(route.query.user) : null),
  set: (value) => patchQuery({ user: value === null ? undefined : String(value) }),
});
const period = computed({
  get: () => {
    const raw = Number(route.query.since);
    return (PERIODS as readonly number[]).includes(raw) ? raw : 30;
  },
  set: (value) => patchQuery({ since: String(value) }),
});
const repoId = computed({
  get: () => (route.query.repo ? Number(route.query.repo) : null),
  set: (value) => patchQuery({ repo: value === null ? undefined : String(value) }),
});

function patchQuery(patch: Record<string, string | undefined>) {
  router.replace({ query: { ...route.query, ...patch } });
}

const only = ref<Kind | null>(null);
const since = computed(() => isoDaysAgo(period.value));
const viewingSelf = computed(() => subjectId.value === null);
const me = computed(() => auth.user.value as UserMeResponse | null);

const { data, isPending, isError, error } = useQuery({
  queryKey: computed(() => [
    "activity",
    subjectId.value ?? "me",
    repoId.value ?? "all",
    since.value,
  ]),
  retry: false,
  queryFn: () =>
    api.request<ActivityResponse>(
      viewingSelf.value ? "/activity/me" : `/activity/${subjectId.value}`,
      { query: { since: since.value, repo_id: repoId.value ?? undefined } },
    ),
});

const counts = computed(() => data.value?.counts ?? null);
const isEmpty = computed(() => {
  const c = counts.value;
  return !!c && c.commits === 0 && c.pull_requests === 0 && c.reviews === 0 && c.issues === 0;
});

// 404 on /github/account is the not-connected state, not an error. Only worth asking
// when your own numbers are all zero, because that is the only time it explains them.
const { data: account, isFetched: accountChecked } = useQuery({
  queryKey: ["github-account"],
  enabled: computed(() => viewingSelf.value && isEmpty.value),
  retry: false,
  queryFn: async () => {
    try {
      return await api.request<GitHubAccountResponse>("/github/account");
    } catch (err: unknown) {
      if (httpStatus(err) === 404) return null;
      throw err;
    }
  },
});

watch([counts, period], () => {
  const c = counts.value;
  if (!c) return;
  announce(
    `${c.commits} commits, ${c.pull_requests} pull requests, ${c.reviews} reviews, ${c.issues} issues in the last ${period.value} days`,
  );
});

const personOptions = computed<SelectOption[]>(() => {
  const self = me.value;
  const selfLabel = self
    ? `${`${self.first_name ?? ""} ${self.last_name ?? ""}`.trim() || self.email} · you · user_id ${self.id}`
    : "You";
  return [
    { value: "me", label: selfLabel },
    ...teammates.value.map((mate) => ({
      value: String(mate.user_id),
      label: `${mate.first_name} ${mate.last_name}`.trim() || mate.email,
    })),
  ];
});

const repoOptions = computed<SelectOption[]>(() => [
  { value: "all", label: "All repositories · repo_id omitted" },
  ...repositories.value.map((r) => ({ value: String(r.id), label: r.full_name })),
]);

const subjectName = computed(() => {
  if (viewingSelf.value) {
    const self = me.value;
    return self ? `${`${self.first_name ?? ""} ${self.last_name ?? ""}`.trim() || self.email}` : "You";
  }
  const mate = teammates.value.find((m) => m.user_id === subjectId.value);
  if (mate) return `${mate.first_name} ${mate.last_name}`.trim();
  return data.value ? personName(data.value.user, data.value.user_id) : "This person";
});

// The activity payload carries only repo_id. An id identity cannot resolve renders as
// an id in italics, never as a fabricated name.
function repoCell(id: number): { label: string; resolved: boolean } {
  const known = repositories.value.find((r) => r.id === id);
  return known
    ? { label: known.full_name.split("/").pop() ?? known.full_name, resolved: true }
    : { label: `repo_id ${id}`, resolved: false };
}

const KIND_META = [
  { key: "commits", label: "Commits" },
  { key: "pull_requests", label: "Pull requests" },
  { key: "reviews", label: "Reviews" },
  { key: "issues", label: "Issues" },
] as const;

const forbidden = computed(() => httpStatus(error.value) === 403);
// Only a request for a named person can be answered "no such user". A 404 on
// /activity/me is the service being unreachable, and saying otherwise is a guess.
const notFound = computed(() => !viewingSelf.value && httpStatus(error.value) === 404);

function show(kind: Kind): boolean {
  return only.value === null || only.value === kind;
}

function toggleOnly(kind: Kind) {
  only.value = only.value === kind ? null : kind;
}
</script>

<template>
  <PulseShell :readout="`last ${period} days`">
    <header class="sec flex flex-wrap items-end justify-between gap-4">
      <div class="min-w-0">
        <Eyebrow>Pulse · activity</Eyebrow>
        <div class="mt-3 flex items-center gap-3">
          <Avatar :name="subjectName" />
          <h1 class="text-[clamp(1.5rem,2.2vw,1.9rem)] font-semibold leading-[1.05] tracking-[-0.035em]">
            {{ subjectName }}
          </h1>
        </div>
        <p class="mt-1.5 text-[12.5px] leading-relaxed text-ink-muted">
          Synced GitHub work
          {{ viewingSelf ? "you did" : "Pulse can attribute to them" }} ·
          <span class="mono">user_id {{ data?.user_id ?? subjectId ?? me?.id ?? "—" }}</span>
        </p>
      </div>
      <p class="mono flex shrink-0 items-center gap-2 rounded-md bg-sunken px-2.5 py-2 text-[11px] ring-1 ring-inset ring-line-subtle">
        <span :class="[MONO_LABEL, 'text-ink-faint']">get</span>
        <span class="text-ink">{{ viewingSelf ? "/activity/me" : `/activity/${subjectId}` }}</span>
        <span class="hidden text-ink-muted sm:inline">?since={{ since }}</span>
      </p>
    </header>

    <section class="sec mt-6 flex flex-wrap items-center gap-3" style="animation-delay: 40ms" aria-label="Narrow the window">
      <Select
        class="w-[280px]"
        label="Whose activity"
        :model-value="subjectId === null ? 'me' : String(subjectId)"
        :options="personOptions"
        @update:model-value="subjectId = $event === 'me' ? null : Number($event)"
      />

      <div role="group" aria-label="Period" class="flex items-center gap-1 rounded-md bg-sunken p-1 ring-1 ring-inset ring-line-subtle">
        <button
          v-for="days in PERIODS"
          :key="days"
          type="button"
          :aria-pressed="period === days"
          :class="[
            FOCUS,
            TAP,
            'rounded px-2.5 py-1.5 text-[12px] transition-colors',
            period === days ? 'bg-surface-active font-medium text-ink' : 'text-ink-muted hover:text-ink',
          ]"
          @click="period = days"
        >
          Last {{ days }} days
        </button>
      </div>

      <Select
        class="w-[280px]"
        label="Repository"
        :model-value="repoId === null ? 'all' : String(repoId)"
        :options="repoOptions"
        @update:model-value="repoId = $event === 'all' ? null : Number($event)"
      />

      <p class="mono ml-auto text-[11px] text-ink-muted">window {{ since }} → today</p>
    </section>

    <p v-if="!hasDepartment" class="mt-3 text-[12px] text-ink-muted">
      You are not in a department yet, so there is nobody else to look at.
    </p>

    <!-- Loading, error, then the numbers. -->
    <section class="sec mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4" style="animation-delay: 80ms" aria-label="Counts">
      <div
        v-for="meta in KIND_META"
        :key="meta.key"
        class="rounded-md bg-surface/40 px-4 py-3.5 ring-1 ring-inset ring-line-subtle"
      >
        <p :class="[MONO_LABEL, 'text-ink-faint']">{{ meta.label }}</p>
        <p class="mono mt-2 text-[30px] font-medium leading-none tracking-[-0.02em] text-ink">
          <template v-if="isPending"><span class="inline-block h-7 w-10 animate-pulse rounded bg-surface" /></template>
          <template v-else-if="counts">{{ counts[meta.key] }}</template>
          <template v-else>—</template>
        </p>
        <button
          type="button"
          :aria-pressed="only === meta.key"
          :disabled="isPending || !counts"
          :class="[
            FOCUS,
            'mt-3 rounded text-[11px] transition-colors disabled:opacity-40',
            only === meta.key ? 'text-ink' : 'text-ink-muted hover:text-ink',
          ]"
          @click="toggleOnly(meta.key)"
        >
          {{ only === meta.key ? "Showing only this" : "Only this" }}
        </button>
      </div>
    </section>

    <p
      v-if="isError"
      role="alert"
      class="mt-6 max-w-[74ch] rounded-md bg-bad-surface px-4 py-3 text-[12.5px] leading-relaxed text-ink"
    >
      <template v-if="forbidden">
        You have no oversight of {{ subjectName }}. Pulse shows one person's work to another only
        through repositories you lead, deputise, or whose department you administer — so this is a
        403, not an empty week.
      </template>
      <template v-else-if="notFound">
        No such user. The person picker is built from your departments, so this id came from the
        URL rather than from the list.
      </template>
      <template v-else>
        {{ apiMessage(error, "Could not reach the Pulse API. Check that the service is running.") }}
      </template>
    </p>

    <p v-else-if="!isPending" class="mt-4 max-w-[86ch] text-[12.5px] leading-relaxed text-ink-muted">
      Counts are exact totals for the window. Pulse keeps no per-day series, so there is nothing to
      plot. Select a count to show only that list.
    </p>

    <!-- Nothing at all, and why. -->
    <section
      v-if="!isError && !isPending && isEmpty"
      class="sec mt-6 rounded-md bg-surface/40 px-5 py-8 ring-1 ring-inset ring-line-subtle"
      style="animation-delay: 120ms"
    >
      <p class="text-[13.5px] font-medium text-ink">Four zeroes</p>

      <template v-if="!viewingSelf">
        <p class="mt-1.5 max-w-[62ch] text-[12.5px] leading-relaxed text-ink-muted">
          Either {{ subjectName }} has no synced activity in this window, or none of it sits in a
          repository you oversee. The payload cannot tell the two apart, so neither can this
          screen.
        </p>
      </template>

      <template v-else-if="accountChecked && !account">
        <p class="mt-1.5 max-w-[62ch] text-[12.5px] leading-relaxed text-ink-muted">
          Your GitHub account is not connected, so nothing can be attributed to you. Connect it and
          the next run picks up your work.
        </p>
        <NuxtLink to="/sync" class="mt-4 inline-block"><Btn size="sm" arrow>Go to Sync</Btn></NuxtLink>
      </template>

      <template v-else>
        <p class="mt-1.5 max-w-[62ch] text-[12.5px] leading-relaxed text-ink-muted">
          <template v-if="account">
            GitHub is connected as <span class="mono text-ink">{{ account.github_login }}</span>.
          </template>
          Nothing was synced for this window{{ repoId ? " in this repository" : "" }}. Widen the
          period, or check the
          <NuxtLink to="/sync" :class="[FOCUS, 'rounded underline underline-offset-2 hover:text-ink']">run history</NuxtLink>.
        </p>
      </template>
    </section>

    <!-- Four lists, each capped at ten rows by the endpoint. -->
    <div v-else-if="!isError" class="sec mt-6 grid gap-4 lg:grid-cols-2" style="animation-delay: 120ms">
      <section v-if="show('commits')" aria-labelledby="list-commits" class="rounded-md bg-surface/40 ring-1 ring-inset ring-line-subtle">
        <div class="flex items-baseline justify-between gap-3 border-b border-line-subtle px-4 py-3">
          <h2 id="list-commits" class="text-[13px] font-medium tracking-tight">Commits</h2>
          <p class="mono text-[11px] text-ink-muted">
            {{ data?.recent_commits.length ?? 0 }} of {{ counts?.commits ?? 0 }}
          </p>
        </div>
        <p v-if="isPending" class="px-4 py-4 text-[12.5px] text-ink-muted">Loading…</p>
        <p v-else-if="!data?.recent_commits.length" class="px-4 py-4 text-[12.5px] text-ink-muted">
          No commits in this window.
        </p>
        <ul v-else class="divide-y divide-line-subtle">
          <li v-for="commit in data.recent_commits" :key="commit.sha" class="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-2.5">
            <span class="mono w-[68px] shrink-0 text-[11px] text-ink-muted">{{ commit.sha.slice(0, 7) }}</span>
            <a
              v-if="commit.url"
              :href="commit.url"
              target="_blank"
              rel="noopener"
              :class="[FOCUS, 'min-w-0 flex-1 truncate rounded text-[12.5px] text-ink hover:underline']"
            >{{ (commit.message ?? "(no message)").split("\n")[0] }}</a>
            <span v-else class="min-w-0 flex-1 truncate text-[12.5px] text-ink">
              {{ (commit.message ?? "(no message)").split("\n")[0] }}
            </span>
            <span
              class="mono shrink-0 text-[11px]"
              :class="repoCell(commit.repo_id).resolved ? 'text-ink-muted' : 'italic text-ink-muted'"
            >{{ repoCell(commit.repo_id).label }}</span>
            <span class="mono shrink-0 text-[11px] text-ink-muted">{{ formatStamp(commit.committed_at) }}</span>
          </li>
        </ul>
        <p v-if="counts && data && counts.commits > data.recent_commits.length" class="border-t border-line-subtle px-4 py-2.5 text-[11.5px] leading-relaxed text-ink-muted">
          Only the ten most recent are returned — {{ counts.commits - data.recent_commits.length }}
          more are in the count but not in this list. The endpoint has no pagination.
        </p>
      </section>

      <section v-if="show('pull_requests')" aria-labelledby="list-prs" class="rounded-md bg-surface/40 ring-1 ring-inset ring-line-subtle">
        <div class="flex items-baseline justify-between gap-3 border-b border-line-subtle px-4 py-3">
          <h2 id="list-prs" class="text-[13px] font-medium tracking-tight">Pull requests</h2>
          <p class="mono text-[11px] text-ink-muted">
            {{ data?.recent_pull_requests.length ?? 0 }} of {{ counts?.pull_requests ?? 0 }}
          </p>
        </div>
        <p v-if="isPending" class="px-4 py-4 text-[12.5px] text-ink-muted">Loading…</p>
        <p v-else-if="!data?.recent_pull_requests.length" class="px-4 py-4 text-[12.5px] text-ink-muted">
          No pull requests in this window.
        </p>
        <ul v-else class="divide-y divide-line-subtle">
          <li v-for="pr in data.recent_pull_requests" :key="`${pr.repo_id}-${pr.number}`" class="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-2.5">
            <span class="mono w-[52px] shrink-0 text-[11px] text-ink-muted">#{{ pr.number }}</span>
            <a
              v-if="pr.url"
              :href="pr.url"
              target="_blank"
              rel="noopener"
              :class="[FOCUS, 'min-w-0 flex-1 truncate rounded text-[12.5px] text-ink hover:underline']"
            >{{ pr.title ?? "(no title)" }}</a>
            <span v-else class="min-w-0 flex-1 truncate text-[12.5px] text-ink">{{ pr.title ?? "(no title)" }}</span>
            <span :class="[MONO_LABEL, 'shrink-0 text-ink-muted']">{{ pr.merged ? "merged" : pr.state }}</span>
            <span
              class="mono shrink-0 text-[11px]"
              :class="repoCell(pr.repo_id).resolved ? 'text-ink-muted' : 'italic text-ink-muted'"
            >{{ repoCell(pr.repo_id).label }}</span>
            <span class="mono shrink-0 text-[11px] text-ink-muted">{{ formatStamp(pr.gh_created_at) }}</span>
          </li>
        </ul>
      </section>

      <section v-if="show('reviews')" aria-labelledby="list-reviews" class="rounded-md bg-surface/40 ring-1 ring-inset ring-line-subtle">
        <div class="flex items-baseline justify-between gap-3 border-b border-line-subtle px-4 py-3">
          <h2 id="list-reviews" class="text-[13px] font-medium tracking-tight">Reviews</h2>
          <p class="mono text-[11px] text-ink-muted">
            {{ data?.recent_reviews.length ?? 0 }} of {{ counts?.reviews ?? 0 }}
          </p>
        </div>
        <p v-if="isPending" class="px-4 py-4 text-[12.5px] text-ink-muted">Loading…</p>
        <p v-else-if="!data?.recent_reviews.length" class="px-4 py-4 text-[12.5px] text-ink-muted">
          No reviews in this window.
        </p>
        <ul v-else class="divide-y divide-line-subtle">
          <li v-for="(review, i) in data.recent_reviews" :key="`${review.pull_request_id}-${i}`" class="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-2.5">
            <span :class="[MONO_LABEL, 'w-[150px] shrink-0 text-ink-muted']">{{ review.state.replace(/_/g, " ") }}</span>
            <a
              v-if="review.url"
              :href="review.url"
              target="_blank"
              rel="noopener"
              :class="[FOCUS, 'min-w-0 flex-1 truncate rounded text-[12.5px] text-ink hover:underline']"
            >Review on pull_request_id {{ review.pull_request_id }}</a>
            <span v-else class="min-w-0 flex-1 truncate text-[12.5px] text-ink">
              Review on pull_request_id {{ review.pull_request_id }}
            </span>
            <span class="mono shrink-0 text-[11px] italic text-ink-muted">no repo returned</span>
            <span class="mono shrink-0 text-[11px] text-ink-muted">{{ formatStamp(review.submitted_at) }}</span>
          </li>
        </ul>
        <p class="border-t border-line-subtle px-4 py-2.5 text-[11.5px] leading-relaxed text-ink-muted">
          A review comes back with an internal <span class="mono">pull_request_id</span> and nothing
          else — no repository, no GitHub pull request number. The id above is Pulse's own row id.
        </p>
      </section>

      <section v-if="show('issues')" aria-labelledby="list-issues" class="rounded-md bg-surface/40 ring-1 ring-inset ring-line-subtle">
        <div class="flex items-baseline justify-between gap-3 border-b border-line-subtle px-4 py-3">
          <h2 id="list-issues" class="text-[13px] font-medium tracking-tight">Issues</h2>
          <p class="mono text-[11px] text-ink-muted">
            {{ data?.recent_issues.length ?? 0 }} of {{ counts?.issues ?? 0 }}
          </p>
        </div>
        <p v-if="isPending" class="px-4 py-4 text-[12.5px] text-ink-muted">Loading…</p>
        <p v-else-if="!data?.recent_issues.length" class="px-4 py-4 text-[12.5px] text-ink-muted">
          No issues in this window.
        </p>
        <ul v-else class="divide-y divide-line-subtle">
          <li v-for="issue in data.recent_issues" :key="`${issue.repo_id}-${issue.number}`" class="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-2.5">
            <span class="mono w-[52px] shrink-0 text-[11px] text-ink-muted">#{{ issue.number }}</span>
            <a
              v-if="issue.url"
              :href="issue.url"
              target="_blank"
              rel="noopener"
              :class="[FOCUS, 'min-w-0 flex-1 truncate rounded text-[12.5px] text-ink hover:underline']"
            >{{ issue.title ?? "(no title)" }}</a>
            <span v-else class="min-w-0 flex-1 truncate text-[12.5px] text-ink">{{ issue.title ?? "(no title)" }}</span>
            <span :class="[MONO_LABEL, 'shrink-0 text-ink-muted']">{{ issue.state }}</span>
            <span
              class="mono shrink-0 text-[11px]"
              :class="repoCell(issue.repo_id).resolved ? 'text-ink-muted' : 'italic text-ink-muted'"
            >{{ repoCell(issue.repo_id).label }}</span>
            <span class="mono shrink-0 text-[11px] text-ink-muted">{{ formatStamp(issue.gh_created_at) }}</span>
          </li>
        </ul>
      </section>
    </div>

    <p class="mt-6 max-w-[86ch] text-[12px] leading-relaxed text-ink-muted">
      Repository names are resolved separately; the activity payload carries only
      <span class="mono">repo_id</span>, so an id Pulse cannot resolve renders as an id.
    </p>
  </PulseShell>
</template>
