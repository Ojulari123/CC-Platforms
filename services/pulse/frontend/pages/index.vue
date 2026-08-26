<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import type { TabItem } from "@crescent/ui/types/ui";
import type { ActivityResponse, Page, ReportResponse } from "~/types/api";

definePageMeta({ middleware: "auth" });

const api = useApi();
const { repositories, repoName } = useRepositories();

const { me, unavailable: meUnavailable } = useMe();
const week = computed(() => mondayOf(new Date()));

// "This week" needs a subject, and the repository you are named lead on is the one you
// are answerable for. Deputy counts too; without either there is nothing to headline.
const leadRepo = computed(
  () =>
    repositories.value.find((r) => r.lead_user_id === me.value?.id)
      ?? repositories.value.find((r) => r.deputy_user_id === me.value?.id)
      ?? null,
);

const queue = useQuery({
  queryKey: ["review-queue", "home"],
  queryFn: () =>
    api.request<Page<ReportResponse>>("/reports/review-queue", {
      query: { status: "submitted", limit: 5, offset: 0 },
    }),
});

const mine = useQuery({
  queryKey: computed(() => ["reports", "mine-home", me.value?.id ?? "anon"]),
  enabled: computed(() => me.value !== null),
  queryFn: () =>
    api.request<Page<ReportResponse>>("/reports", {
      query: { author_user_id: me.value?.id, limit: 5, offset: 0 },
    }),
});

const drafts = useQuery({
  queryKey: computed(() => ["reports", "drafts-home", me.value?.id ?? "anon"]),
  enabled: computed(() => me.value !== null),
  queryFn: () =>
    api.request<Page<ReportResponse>>("/reports", {
      query: { author_user_id: me.value?.id, status: "draft", limit: 1, offset: 0 },
    }),
});

// The week's figures are a second request, so they can be missing on their own. Missing
// is not zero and the panel says which.
const thisWeekActivity = useQuery({
  queryKey: computed(() => ["activity", "home", leadRepo.value?.id ?? "none", week.value]),
  enabled: computed(() => leadRepo.value !== null),
  queryFn: () =>
    api.request<ActivityResponse>("/activity/me", {
      query: { since: week.value, repo_id: leadRepo.value?.id },
    }),
});

const thisWeekReport = computed(
  () =>
    (mine.data.value?.items ?? []).find(
      (r) => r.repo_id === leadRepo.value?.id && r.week_start === week.value,
    ) ?? null,
);

const scope = ref<"waiting" | "mine">("waiting");

const tabs = computed<TabItem[]>(() => [
  { id: "waiting", label: "Waiting on you", hint: String(queue.data.value?.total ?? 0) },
  { id: "mine", label: "Yours", hint: String(mine.data.value?.total ?? 0) },
]);

const rows = computed(() =>
  scope.value === "waiting" ? queue.data.value?.items ?? [] : mine.data.value?.items ?? [],
);

const listPending = computed(() =>
  scope.value === "waiting" ? queue.isPending.value : mine.isPending.value,
);
const listError = computed(() =>
  scope.value === "waiting" ? queue.error.value : mine.error.value,
);

const firstName = computed(() => me.value?.first_name ?? "Hello");
const deptLabel = computed(() => me.value?.memberships?.[0]?.dept_name ?? "unplaced");
const roleLabel = computed(
  () => me.value?.memberships?.[0]?.role ?? (me.value?.is_platform_admin ? "platform admin" : "member"),
);

const COUNT_META = [
  { key: "commits", label: "Commits" },
  { key: "pull_requests", label: "Pull requests" },
  { key: "reviews", label: "Reviews" },
  { key: "issues", label: "Issues" },
] as const;
</script>

<template>
  <PulseShell :readout="`week of ${formatDate(week)}`">
    <section class="pb-9">
      <Eyebrow class="sec">Pulse · overview</Eyebrow>

      <h1
        class="sec mt-3 max-w-[20ch] text-[clamp(1.7rem,3.6vw,2.5rem)] font-semibold leading-[1.02] tracking-[-0.035em]"
        style="animation-delay: 40ms"
      >
        {{ firstName }}, here is<br />
        <span class="text-ink-muted">the week so far.</span>
      </h1>

      <p
        :class="[MONO_LABEL, 'sec mt-6 flex flex-wrap items-baseline gap-x-2.5 gap-y-1 text-ink-muted']"
        style="animation-delay: 80ms"
      >
        <span class="text-ink">{{ queue.data.value?.total ?? "—" }}</span> awaiting your decision
        <span aria-hidden="true">·</span>
        <span class="text-ink">{{ drafts.data.value?.total ?? "—" }}</span>
        draft{{ drafts.data.value?.total === 1 ? "" : "s" }}
        <span aria-hidden="true">·</span>
        <span class="text-ink">{{ mine.data.value?.total ?? "—" }}</span> reports yours
        <span aria-hidden="true">·</span>
        week of {{ formatDate(week) }}
      </p>

      <p class="sec mt-5 max-w-[54ch] text-[13.5px] leading-relaxed text-ink-muted" style="animation-delay: 100ms">
        One report per repository per week, drafted from what the repository actually did and
        decided by that repository's lead. Nothing here is a score.
      </p>
    </section>

    <!-- This week, for the repository you are answerable for. -->
    <section class="sec border-t border-line-subtle pt-7" style="animation-delay: 140ms" aria-labelledby="this-week">
      <div class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
        <h2 id="this-week" class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">This week</h2>
        <p :class="[MONO_LABEL, 'text-ink-muted']">
          {{ leadRepo ? leadRepo.full_name : "no repository names you" }} · week of {{ formatDate(week) }}
        </p>
      </div>

      <p v-if="!leadRepo" class="mt-4 max-w-[62ch] border-t border-line-subtle pt-5 text-[13px] leading-relaxed text-ink-muted">
        No repository names you as its lead or deputy, so there is no week here that is yours to
        answer for. Reports you write still go to whoever is named on their repository.
      </p>

      <div v-else class="mt-4 grid gap-x-10 gap-y-6 border-t border-line-subtle pt-5 lg:grid-cols-[minmax(0,1fr)_260px]">
        <div class="min-w-0">
          <template v-if="thisWeekReport">
            <div class="flex flex-wrap items-center gap-2.5">
              <span
                :class="[MONO_LABEL, 'inline-flex items-center rounded px-2 py-0.5', statusClass(thisWeekReport.status)]"
              >
                {{ statusLabel(thisWeekReport.status) }}
              </span>
              <span class="mono text-[12px] text-ink-muted">report #{{ thisWeekReport.id }}</span>
              <span v-if="thisWeekReport.generated_at" class="mono text-[12px] text-ink-muted">
                AI-drafted · {{ thisWeekReport.prompt_version ?? "no version" }}
              </span>
            </div>
            <p class="mt-3.5 max-w-[58ch] text-[13.5px] leading-relaxed text-ink">
              {{ thisWeekReport.summary_exec ?? "Nothing written yet." }}
            </p>
            <NuxtLink
              :to="`/reports/${thisWeekReport.id}`"
              :class="[FOCUS, 'group/tw mt-4 inline-flex items-center gap-1.5 rounded text-[12.5px] font-medium text-ink transition-colors hover:text-ink-muted']"
            >
              Open the report
              <Icon name="arrow" class="h-3.5 w-3.5 transition-transform group-hover/tw:translate-x-0.5" />
            </NuxtLink>
          </template>

          <template v-else-if="mine.isPending.value">
            <p class="text-[13px] text-ink-muted">Reading your reports…</p>
          </template>

          <template v-else>
            <p class="max-w-[58ch] text-[13px] leading-relaxed text-ink-muted">
              No report filed for {{ leadRepo.full_name }} this week yet.
            </p>
            <NuxtLink :to="`/reports/new?repo=${leadRepo.id}&week=${week}`" class="mt-4 inline-block">
              <Btn size="sm">Write it</Btn>
            </NuxtLink>
          </template>
        </div>

        <dl class="grid grid-cols-2 gap-x-6 gap-y-4 lg:border-l lg:border-line-subtle lg:pl-8">
          <div v-for="meta in COUNT_META" :key="meta.key">
            <dt :class="[MONO_LABEL, 'text-ink-faint']">{{ meta.label }}</dt>
            <dd class="mono mt-1 text-[28px] font-medium leading-none tracking-[-0.02em] text-ink">
              <template v-if="thisWeekActivity.isPending.value">
                <span class="inline-block h-6 w-9 animate-pulse rounded bg-surface" />
              </template>
              <template v-else-if="thisWeekActivity.data.value">
                {{ thisWeekActivity.data.value.counts[meta.key] }}
              </template>
              <template v-else>—</template>
            </dd>
          </div>
        </dl>
      </div>

      <p
        v-if="leadRepo && thisWeekActivity.isError.value"
        role="alert"
        class="mt-5 flex items-start gap-2.5 rounded-md bg-warn-surface px-3.5 py-2.5 text-[12px] leading-relaxed text-ink"
      >
        <span class="mt-px shrink-0 text-warn"><Icon name="alert" class="h-3.5 w-3.5" /></span>
        The week's activity is a separate request, and it did not come back — the figures above
        are missing rather than zero.
        {{ apiMessage(thisWeekActivity.error.value, "") }}
      </p>
    </section>

    <!-- Recent reports. -->
    <section class="sec mt-10" style="animation-delay: 180ms" aria-labelledby="recent-reports">
      <!-- The heading and the two links used to ride inside the tab rail's trailing slot.
           A tablist cannot wrap without stranding its travelling indicator, so at 390px
           four items on one no-wrap row overflowed their own underline. They are a header
           above the rail now: the rail carries the two tabs and nothing else, and the row
           above it is free to wrap. -->
      <div class="flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
        <div class="min-w-0">
          <h2 id="recent-reports" class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">
            Recent reports
          </h2>
          <p class="mt-1 text-[13px] leading-relaxed text-ink-muted">
            The five most recent in each list.
          </p>
        </div>
        <span class="flex flex-wrap items-center gap-x-5 gap-y-1">
          <NuxtLink to="/reports/new" :class="[FOCUS, 'rounded text-[13px] text-ink-muted transition-colors hover:text-ink']">
            New weekly report
          </NuxtLink>
          <NuxtLink to="/reports/adhoc" :class="[FOCUS, 'rounded text-[13px] text-ink-muted transition-colors hover:text-ink']">
            New custom report
          </NuxtLink>
          <NuxtLink to="/reports" :class="[FOCUS, 'group/all rounded text-[13px] text-ink-muted transition-colors hover:text-ink']">
            All reports
            <Icon name="arrow" class="ml-1 inline h-3 w-3 transition-transform group-hover/all:translate-x-0.5" />
          </NuxtLink>
        </span>
      </div>

      <Tabs id="home-scope" v-model="scope" label="Which reports to list" variant="mono" class="mt-4" :items="tabs" has-panel />

      <TabPanel id="home-scope" :tab="scope" class="mt-1">
        <p
          v-if="scope === 'mine' && meUnavailable"
          role="alert"
          class="border-b border-line-subtle px-1 py-8 text-[12.5px] leading-relaxed text-ink-muted"
        >
          Identity did not answer when Pulse asked who you are, so this list cannot be narrowed
          to what you wrote.
        </p>

        <p v-else-if="listPending" class="border-b border-line-subtle px-1 py-8 text-[12.5px] text-ink-muted">
          Loading…
        </p>

        <p
          v-else-if="listError"
          role="alert"
          class="border-b border-line-subtle px-1 py-8 text-[12.5px] leading-relaxed text-bad"
        >
          {{ apiMessage(listError, "Could not reach the Pulse API. Check that the service is running.") }}
        </p>

        <ul v-else-if="rows.length" :key="scope" class="xfade">
          <li v-for="row in rows" :key="row.id" class="border-b border-line-subtle">
            <NuxtLink
              :to="`/reports/${row.id}`"
              :class="[FOCUS, 'flex w-full flex-wrap items-center gap-x-4 gap-y-1.5 px-1 py-3 text-left transition-colors hover:bg-surface-hover/40']"
            >
              <span class="mono w-[92px] shrink-0 text-[12px] text-ink-muted">#{{ row.id }}</span>
              <span class="mono min-w-0 flex-1 truncate text-[12.5px] text-ink">{{ reportRepoLabel(row, repoName) }}</span>
              <span class="mono hidden w-[104px] shrink-0 text-[12px] text-ink-muted sm:block">
                {{ isAdhoc(row) ? formatDate(row.range_start) : formatDate(row.week_start) }}
              </span>
              <span class="hidden w-[150px] shrink-0 truncate text-[12px] text-ink-muted md:block">
                {{ row.author_user_id === me?.id ? "You" : personName(row.author, row.author_user_id) }}
              </span>
              <span
                class="w-[150px] shrink-0"
              ><span :class="['inline-flex items-center rounded px-2 py-1 text-[12px]', statusClass(row.status)]">{{ statusLabel(row.status) }}</span></span>
              <span class="mono hidden w-[74px] shrink-0 text-right text-[12px] text-ink-muted lg:block">
                {{ relativeTime(row.updated_at) }}
              </span>
            </NuxtLink>
          </li>
        </ul>

        <p v-else :key="`${scope}-empty`" class="xfade border-b border-line-subtle px-1 py-8 text-[12.5px] leading-relaxed text-ink-muted">
          <template v-if="scope === 'waiting'">
            Nothing is waiting on your decision. Reports you wrote never appear here, so an empty
            list does not mean nobody filed.
          </template>
          <template v-else>You have not written a report yet.</template>
        </p>
      </TabPanel>
    </section>

    <!-- The two doors out of here. -->
    <section class="mt-10 grid border-t border-line-subtle sm:grid-cols-2" aria-label="Elsewhere in Pulse">
      <div class="sec relative border-b border-line-subtle" style="animation-delay: 220ms">
        <Cross class="absolute -bottom-[5px] -right-[5px] hidden sm:block" />
        <NuxtLink
          to="/activity"
          :class="[FOCUS, 'group/door flex h-full w-full flex-col items-start px-0 py-6 text-left transition-colors hover:bg-surface-hover/40 sm:px-5']"
        >
          <span class="flex items-center gap-2.5">
            <span class="grid h-8 w-8 shrink-0 place-items-center rounded-md bg-sunken text-ink-muted ring-1 ring-inset ring-line-subtle transition-colors group-hover/door:text-ink">
              <Icon name="pulse" class="h-[15px] w-[15px]" />
            </span>
            <span class="text-[15px] font-medium tracking-tight">Activity</span>
            <Icon name="arrow" class="h-3.5 w-3.5 text-ink-faint transition-transform group-hover/door:translate-x-0.5" />
          </span>
          <span class="mt-3.5 block max-w-[42ch] text-[12.5px] leading-relaxed text-ink-muted">
            Commits, pull requests, reviews and issues for a person, a repository and a window.
          </span>
          <span :class="[MONO_LABEL, 'mt-4 block text-ink-faint']">four counts · four capped lists</span>
        </NuxtLink>
      </div>

      <div class="sec relative border-b border-line-subtle sm:border-l" style="animation-delay: 280ms">
        <Cross class="absolute -bottom-[5px] -right-[5px] hidden sm:block" />
        <NuxtLink
          to="/reports"
          :class="[FOCUS, 'group/door flex h-full w-full flex-col items-start px-0 py-6 text-left transition-colors hover:bg-surface-hover/40 sm:px-5']"
        >
          <span class="flex items-center gap-2.5">
            <span class="grid h-8 w-8 shrink-0 place-items-center rounded-md bg-sunken text-ink-muted ring-1 ring-inset ring-line-subtle transition-colors group-hover/door:text-ink">
              <Icon name="doc" class="h-[15px] w-[15px]" />
            </span>
            <span class="text-[15px] font-medium tracking-tight">Reports</span>
            <Icon name="arrow" class="h-3.5 w-3.5 text-ink-faint transition-transform group-hover/door:translate-x-0.5" />
          </span>
          <span class="mt-3.5 block max-w-[42ch] text-[12.5px] leading-relaxed text-ink-muted">
            Everything you wrote, and everything waiting on your decision, in one place.
          </span>
          <span :class="[MONO_LABEL, 'mt-4 block text-ink-faint']">
            {{ mine.data.value?.total ?? 0 }} yours · {{ queue.data.value?.total ?? 0 }} awaiting review
          </span>
        </NuxtLink>
      </div>
    </section>

    <div class="flex flex-wrap items-center justify-between gap-3 pt-6">
      <NuxtLink to="/sync" :class="[FOCUS, 'rounded text-[12px] text-ink-muted transition-colors hover:text-ink']">
        Sync and run history
      </NuxtLink>
      <p :class="[MONO_LABEL, 'text-ink-muted']">
        user_id {{ me?.id ?? "—" }} · {{ deptLabel }} · {{ roleLabel }}
      </p>
    </div>
  </PulseShell>
</template>
