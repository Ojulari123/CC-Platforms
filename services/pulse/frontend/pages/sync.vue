<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import type { SelectOption } from "@crescent/ui/types/ui";
import type { ConnectedAccountResponse, Page, SyncRunResponse, UserMeResponse } from "~/types/api";

definePageMeta({ middleware: "auth" });

/* Every count anywhere in Pulse was put there by a run below, so this is a ledger rather
   than a status light: one row per repository per pass, with what that pass ingested and
   what it refused. */

const auth = useAuth();
const api = useApi();
const route = useRoute();
const router = useRouter();
const queryClient = useQueryClient();
const announce = useAnnounce();
const { show: showToast } = useToast();
const { repositories, repoName } = useRepositories();

const me = computed(() => auth.user.value as UserMeResponse | null);
const isPlatformAdmin = computed(() => me.value?.is_platform_admin === true);

// Not connected is `account: null` inside a 200, so the state most people start in is an
// answer rather than an error.
const {
  data: accountEnvelope,
  isPending: accountPending,
  isError: accountFailed,
  error: accountError,
} = useQuery({
  queryKey: ["github-account"],
  retry: false,
  queryFn: () => api.request<ConnectedAccountResponse>("/github/account"),
});

const account = computed(() => accountEnvelope.value?.account ?? null);
const connected = computed(() => account.value !== null);

const repoFilter = computed({
  get: () => (route.query.repo ? Number(route.query.repo) : null),
  set: (value) => {
    openRun.value = null;
    router.replace({ query: { ...route.query, repo: value === null ? undefined : String(value) } });
  },
});

const {
  data: runs,
  isPending: runsPending,
  isError: runsFailed,
  error: runsError,
} = useQuery({
  queryKey: computed(() => ["sync-runs", repoFilter.value ?? "all"]),
  queryFn: () =>
    api.request<Page<SyncRunResponse>>("/github/sync-runs", {
      query: { repo_id: repoFilter.value ?? undefined, limit: 50, offset: 0 },
    }),
});

const rows = computed(() => runs.value?.items ?? []);
const lastRun = computed(() => rows.value[0] ?? null);
const failing = computed(() => failedRuns(rows.value));
const next = computed(() => nextScheduledRun());

/* The stale-sync notice can be put away, and the dismissal is stored against the set of
   runs that are failing rather than against the notice. Read that way, closing it says
   "I have seen these five", not "stop telling me about failures" — the next failure has a
   different fingerprint and raises the notice again. A warning that can be silenced for
   good while the thing it warns about carries on is worse than no warning.

   `${authStoragePrefix}.<name>` in localStorage is the layer's key format (see
   composables/useTokenStorage.ts); this is a preference rather than a credential, but a
   second format for one key would only be a second thing to remember. */
const STALE_KEY = `${useRuntimeConfig().public.authStoragePrefix}.sync_stale_dismissed`;
const staleFingerprint = computed(() => failureFingerprint(rows.value));
const staleDismissed = ref<string | null>(null);
const staleVisible = computed(
  () => failing.value.length > 0 && staleDismissed.value !== staleFingerprint.value,
);

onMounted(() => {
  try {
    staleDismissed.value = localStorage.getItem(STALE_KEY);
  } catch {
    // Storage is unreadable in some private-browsing modes. The notice simply stays.
  }
});

function dismissStale() {
  staleDismissed.value = staleFingerprint.value;
  try {
    localStorage.setItem(STALE_KEY, staleFingerprint.value);
  } catch {
    // Unwritable storage costs the dismissal its persistence, not this visit.
  }
  announce("Stale sync notice dismissed. It returns if another run fails.");
}

const visited = computed(() => {
  const ids = new Set<number>();
  for (const run of rows.value) if (run.repo_id !== null) ids.add(run.repo_id);
  return ids.size;
});

const skipped = computed(() => rows.value.filter((run) => run.status === "skipped").length);

const repoOptions = computed<SelectOption[]>(() => [
  { value: "all", label: "Every repository" },
  ...repositories.value.map((r) => ({ value: String(r.id), label: r.full_name })),
]);

const openRun = ref<number | null>(null);

/* ── the writes ────────────────────────────────────────────────────────────── */

const connecting = ref(false);

/* One handoff, two endpoints. /github/connect is the first authorisation. /github/reconnect
   is for an account that is already stored and only needs wider access: it hands back a URL
   and deliberately leaves the stored token alone, so the connection in place keeps working
   until GitHub confirms the new one. Nothing is lost by starting it and walking away. */
async function connect() {
  connecting.value = true;
  const again = connected.value;
  try {
    const res = await api.request<{ authorize_url: string }>(
      again ? "/github/reconnect" : "/github/connect",
      { method: again ? "POST" : "GET" },
    );
    // Same tab on purpose: window.open after an await is outside the click's call stack
    // and gets blocked as a popup.
    window.location.href = res.authorize_url;
  } catch (err: unknown) {
    connecting.value = false;
    showToast(
      httpStatus(err) === 429
        ? "429 · too many connect attempts. Wait a minute and try again."
        : apiMessage(err, "Could not start the GitHub connection."),
      "bad",
    );
  }
}

const syncNow = useMutation({
  mutationFn: () => api.request<unknown>("/github/sync", { method: "POST" }),
  onSuccess: () => {
    announce("Sync queued to the worker");
    showToast("Sync queued. The rows below fill in as each repository finishes.", "info");
    queryClient.invalidateQueries({ queryKey: ["sync-runs"] });
  },
  onError: (err) => {
    const code = httpStatus(err);
    showToast(
      code === 403
        ? "403 · Sync now is a platform-admin action."
        : code === 429
          ? "429 · Sync now is limited to five a minute."
          : apiMessage(err, "Could not queue a sync."),
      "bad",
    );
  },
});

const confirmDisconnect = ref(false);

const disconnect = useMutation({
  mutationFn: () => api.request<void>("/github/account", { method: "DELETE" }),
  onSuccess: () => {
    confirmDisconnect.value = false;
    queryClient.invalidateQueries({ queryKey: ["github-account"] });
    showToast("GitHub account disconnected.", "muted");
  },
  onError: (err) => {
    confirmDisconnect.value = false;
    showToast(apiMessage(err, "Could not disconnect that account."), "bad");
  },
});

/* ── the OAuth return ──────────────────────────────────────────────────────── */

const OUTCOMES: Record<string, { tone: "ok" | "warn" | "bad"; text: string }> = {
  connected: {
    tone: "ok",
    text: "GitHub connected. Your commits, pull requests and reviews appear after the next run.",
  },
  denied: {
    tone: "warn",
    text: "You cancelled on GitHub, so nothing was connected. You can try again whenever you like.",
  },
  expired: {
    tone: "warn",
    text: "That connect link was no longer valid; they only last a few minutes. Start again.",
  },
  already_linked: {
    tone: "bad",
    text: "That GitHub account is already connected to a different Pulse user. Connect a different account, or ask an admin to release it.",
  },
  not_configured: {
    tone: "bad",
    text: "GitHub connecting is not set up on this server yet. Ask a platform admin to finish the setup.",
  },
  failed: {
    tone: "bad",
    text: "Connecting to GitHub did not finish. Try again, and tell an admin if it keeps happening.",
  },
};

onMounted(() => {
  const outcome = route.query.github;
  if (typeof outcome !== "string") return;
  const message = OUTCOMES[outcome] ?? OUTCOMES.failed!;
  showToast(message.text, message.tone);
  const { github: _github, ...rest } = route.query;
  router.replace({ query: rest });
});
</script>

<template>
  <PulseShell :readout="connected ? `next run ${next.away}` : 'not connected'">
    <header class="sec flex flex-wrap items-end justify-between gap-4">
      <div class="min-w-0">
        <Eyebrow>Pulse · sync</Eyebrow>
        <h1 class="mt-3 text-[clamp(1.5rem,2.2vw,1.9rem)] font-semibold leading-[1.05] tracking-[-0.035em]">
          GitHub sync
        </h1>
        <p class="mt-1.5 max-w-[74ch] text-[12.5px] leading-relaxed text-ink-muted">
          Every figure in Pulse — the counts on Activity, the material a report is drafted from —
          was put there by a run below. Nothing in the product reaches GitHub live, so a run that
          failed is a week of missing evidence rather than a slow page.
        </p>
      </div>
      <p class="mono flex shrink-0 items-center gap-2 rounded-md bg-sunken px-2.5 py-2 text-[12px] ring-1 ring-inset ring-line-subtle">
        <span :class="[MONO_LABEL, 'text-ink-faint']">get</span>
        <span class="text-ink">/github/sync-runs</span>
        <span class="hidden text-ink-muted sm:inline">?limit=50</span>
      </p>
    </header>

    <!-- The connection. -->
    <section
      aria-labelledby="conn-heading"
      class="sec mt-8 rounded-md bg-surface/40 px-5 py-5 ring-1 ring-inset ring-line-subtle"
      style="animation-delay: 40ms"
    >
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div class="min-w-0">
          <Eyebrow>Connection</Eyebrow>
          <h2 id="conn-heading" class="mt-2 flex flex-wrap items-center gap-2.5 text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">
            <template v-if="accountPending">
              <span class="text-ink-muted">Checking…</span>
            </template>
            <template v-else-if="connected">
              <span class="mono text-ink">{{ account?.github_login }}</span>
              <StatusDot tone="ok">Connected</StatusDot>
            </template>
            <template v-else>
              <span class="text-ink">No GitHub account</span>
              <StatusDot tone="warn">Nothing to sync</StatusDot>
            </template>
          </h2>
        </div>
        <div class="flex shrink-0 flex-wrap items-center gap-2">
          <template v-if="connected">
            <Btn
              v-if="isPlatformAdmin"
              size="sm"
              :busy="syncNow.isPending.value"
              @click="syncNow.mutate()"
            >Sync now</Btn>
            <Btn size="sm" variant="secondary" data-test="reconnect" :busy="connecting" @click="connect">
              Reconnect
            </Btn>
            <Btn size="sm" variant="destructive" @click="confirmDisconnect = true">Disconnect</Btn>
          </template>
          <Btn v-else-if="!accountPending" size="sm" arrow :busy="connecting" @click="connect">
            Connect GitHub
          </Btn>
        </div>
      </div>

      <p v-if="accountFailed" role="alert" class="mt-3 max-w-[74ch] text-[12.5px] leading-relaxed text-bad">
        {{ apiMessage(accountError, "Could not read the GitHub connection. Check that the Pulse service is running.") }}
      </p>

      <template v-else-if="connected && account">
        <dl class="mt-4 grid gap-x-8 gap-y-3 border-t border-line-subtle pt-4 sm:grid-cols-2 xl:grid-cols-4">
          <div class="min-w-0">
            <dt :class="[MONO_LABEL, 'text-ink-faint']">github_login</dt>
            <dd class="mono mt-1.5 break-words text-[12px] text-ink">{{ account.github_login }}</dd>
          </div>
          <div class="min-w-0">
            <dt :class="[MONO_LABEL, 'text-ink-faint']">github_user_id</dt>
            <dd class="mono mt-1.5 break-words text-[12px] text-ink">{{ account.github_user_id }}</dd>
          </div>
          <div class="min-w-0">
            <dt :class="[MONO_LABEL, 'text-ink-faint']">connected_at</dt>
            <dd class="mono mt-1.5 break-words text-[12px] text-ink">{{ formatDateTime(account.connected_at) }}</dd>
          </div>
          <div class="min-w-0">
            <dt :class="[MONO_LABEL, 'text-ink-faint']">scopes</dt>
            <dd class="mono mt-1.5 break-words text-[12px] text-ink">{{ account.scopes ?? "not recorded" }}</dd>
          </div>
        </dl>
        <p class="mt-4 max-w-[80ch] text-[12.5px] leading-relaxed text-ink-muted">
          This is an OAuth authorisation on one person's account, not an org-wide app install — so
          the sync only reaches what these scopes reach, and the token is stored encrypted. Pulse
          asks for <span class="mono text-[12px] text-ink">read:org</span> so it can match GitHub
          logins back to identity users; without it, commits arrive attributed to nobody.
        </p>
        <p v-if="!isPlatformAdmin" class="mt-3 max-w-[80ch] text-[12.5px] leading-relaxed text-ink-muted">
          Running a sync by hand is a platform-admin action, so there is no button for it here. The
          scheduled run at 02:00 UTC is unaffected.
        </p>
        <p class="mt-3 max-w-[80ch] text-[12.5px] leading-relaxed text-ink-muted" data-test="reconnect-note">
          Reconnect sends you to GitHub to approve access again, which is what widens a
          connection that cannot reach everything you need. Approving replaces this connection in
          place; the one above keeps working until it does, so starting it and changing your mind
          costs nothing.
        </p>
        <p class="mono mt-3 text-[12px] leading-relaxed text-ink-faint">
          get /github/account · post /github/reconnect · delete /github/account · post /github/sync
        </p>
      </template>

      <template v-else-if="!accountPending">
        <p class="mt-2.5 max-w-[80ch] text-[12.5px] leading-relaxed text-ink-muted">
          Connecting sends you to GitHub to authorise Pulse, then straight back here. Pulse never
          sees a password: it receives a token, stores it encrypted, and uses it to read commits,
          pull requests, reviews and issues in the repositories you can already see. It writes
          nothing to GitHub.
        </p>
        <ol class="mt-4 space-y-2 border-t border-line-subtle pt-4 text-[12.5px] leading-relaxed text-ink-muted">
          <li class="flex gap-2">
            <span class="mono shrink-0 text-[12px] text-ink-faint">01</span>
            <span>
              <span class="mono text-[12px] text-ink">GET /github/connect</span> returns an
              authorize URL and you land on GitHub.
            </span>
          </li>
          <li class="flex gap-2">
            <span class="mono shrink-0 text-[12px] text-ink-faint">02</span>
            <span>
              Approving sends you back to
              <span class="mono text-[12px] text-ink">/github/oauth/callback</span>, which
              redirects here with an outcome —
              <span class="mono text-[12px] text-ink">?github=connected</span>, or
              <span class="mono text-[12px] text-ink">denied</span>,
              <span class="mono text-[12px] text-ink">expired</span>,
              <span class="mono text-[12px] text-ink">already_linked</span>.
            </span>
          </li>
          <li class="flex gap-2">
            <span class="mono shrink-0 text-[12px] text-ink-faint">03</span>
            <span>
              Nothing appears until a run finishes. Until then your counts stay at zero, which
              reads exactly like having done no work.
            </span>
          </li>
        </ol>
      </template>
    </section>

    <!-- When it next runs, and what it reached. -->
    <div class="sec mt-4 grid gap-3 md:grid-cols-3" style="animation-delay: 80ms">
      <div class="rounded-md bg-surface/40 px-4 py-3.5 ring-1 ring-inset ring-line-subtle">
        <p :class="[MONO_LABEL, 'text-ink-faint']">Next scheduled run</p>
        <p class="mono mt-2 text-[13.5px] text-ink">{{ next.iso }}</p>
        <p class="mt-1.5 text-[12px] text-ink-muted">Daily at 02:00 UTC · {{ next.away }} away</p>
      </div>
      <div class="rounded-md bg-surface/40 px-4 py-3.5 ring-1 ring-inset ring-line-subtle">
        <p :class="[MONO_LABEL, 'text-ink-faint']">Last run</p>
        <p class="mono mt-2 text-[13.5px] text-ink">
          {{ lastRun ? formatStamp(lastRun.started_at) : "never" }}
        </p>
        <p class="mt-1.5 text-[12px] text-ink-muted">
          <template v-if="lastRun">
            {{ inferTrigger(lastRun) }} (inferred) · {{ runDuration(lastRun) }}
          </template>
          <template v-else>No run recorded yet</template>
        </p>
      </div>
      <div class="rounded-md bg-surface/40 px-4 py-3.5 ring-1 ring-inset ring-line-subtle">
        <p :class="[MONO_LABEL, 'text-ink-faint']">Repositories visited</p>
        <p class="mono mt-2 text-[13.5px] text-ink">{{ visited }}</p>
        <p class="mt-1.5 text-[12px] text-ink-muted">
          {{ skipped }} rows recorded as skipped ·
          <NuxtLink to="/repositories" :class="[FOCUS, 'rounded underline underline-offset-2 hover:text-ink']">
            change tracking
          </NuxtLink>
        </p>
      </div>
    </div>

    <!-- What incremental actually costs you. -->
    <section
      aria-labelledby="cursor-heading"
      class="sec mt-4 rounded-md bg-surface/40 px-5 py-5 ring-1 ring-inset ring-line-subtle"
      style="animation-delay: 120ms"
    >
      <Eyebrow>The cursor</Eyebrow>
      <h2 id="cursor-heading" class="mt-2 text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">
        Each run resumes where the last one stopped
      </h2>
      <p class="mt-2 max-w-[86ch] text-[12.5px] leading-relaxed text-ink-muted">
        A repository stores one timestamp — <span class="mono text-[12px] text-ink">last_synced_at</span>
        — and the next run asks GitHub only for what changed after it. That is what keeps a daily
        pass cheap, and it has three consequences worth being blunt about.
      </p>
      <ul class="mt-3.5 grid gap-3 border-t border-line-subtle pt-4 lg:grid-cols-3">
        <li>
          <p :class="[MONO_LABEL, 'text-ink-faint']">Before the first run</p>
          <p class="mt-1.5 text-[12.5px] leading-relaxed text-ink-muted">
            History from before a repository was first synced is not fetched, and no later run goes
            back for it. A report about an old week will find nothing to draw on, and will say so
            rather than invent.
          </p>
        </li>
        <li>
          <p :class="[MONO_LABEL, 'text-ink-faint']">The seven-day overlap</p>
          <p class="mt-1.5 text-[12.5px] leading-relaxed text-ink-muted">
            Commits are asked for from the cursor minus seven days, because a commit authored last
            week and pushed today is dated behind the cursor and a window starting exactly at it
            would never see the commit — on this run or any later one.
          </p>
        </li>
        <li>
          <p :class="[MONO_LABEL, 'text-ink-faint']">A failed run</p>
          <p class="mt-1.5 text-[12.5px] leading-relaxed text-ink-muted">
            The cursor is stamped before the fetch and left alone when the fetch throws, so a
            failure re-reads its window next time instead of stepping over it. Nothing is silently
            lost — it is only late.
          </p>
        </li>
      </ul>
    </section>

    <!-- Something is wrong right now. -->
    <div
      v-if="staleVisible"
      data-test="stale-notice"
      role="status"
      class="sec mt-4 flex items-start gap-3 rounded-md bg-warn-surface px-4 py-3.5"
      style="animation-delay: 120ms"
    >
      <span class="mt-0.5 shrink-0 text-warn"><Icon name="alert" /></span>
      <p class="min-w-0 flex-1 text-[13px] leading-relaxed text-ink">
        <span class="font-medium">
          {{ failing.length }} of the last {{ rows.length }} runs did not complete.
        </span>
        <span class="text-ink-muted">
          Those repositories are stale, so any report drafted from them is drafted from a short
          week. The rows are below, with the reason each one gave.
        </span>
      </p>
      <button
        type="button"
        data-test="stale-dismiss"
        aria-label="Dismiss the stale sync notice"
        :class="[FOCUS, TAP, '-mr-1 -mt-1 shrink-0 rounded p-1.5 text-ink-muted transition-colors hover:bg-surface-hover hover:text-ink']"
        @click="dismissStale"
      >
        <Icon name="x" class="h-3.5 w-3.5" />
      </button>
    </div>

    <!-- Run history. -->
    <div class="sec mt-8 flex flex-wrap items-end justify-between gap-3" style="animation-delay: 120ms">
      <div class="min-w-0">
        <Eyebrow>Run history</Eyebrow>
        <p class="mt-2 max-w-[70ch] text-[12.5px] leading-relaxed text-ink-muted">
          One row per repository per pass — the worker records each repository separately, so a
          single failure never hides the rest of the run.
        </p>
      </div>
      <Select
        class="w-[260px]"
        label="Repository"
        :model-value="repoFilter === null ? 'all' : String(repoFilter)"
        :options="repoOptions"
        @update:model-value="repoFilter = $event === 'all' ? null : Number($event)"
      />
    </div>

    <p v-if="runsPending" class="mt-4 text-[12.5px] text-ink-muted">Loading run history…</p>

    <div v-else-if="runsFailed" role="alert" class="sec mt-4 rounded-md bg-bad-surface px-5 py-6">
      <p class="text-[13.5px] font-medium text-ink">Could not load the run history</p>
      <p class="mt-1.5 max-w-[62ch] text-[12.5px] leading-relaxed text-ink-muted">
        {{ apiMessage(runsError, "The Pulse API did not answer. Check that the service is running.") }}
      </p>
      <div class="mt-4 flex">
        <Btn size="sm" variant="secondary" @click="queryClient.invalidateQueries({ queryKey: ['sync-runs'] })">
          Try again
        </Btn>
      </div>
    </div>

    <div v-else-if="!rows.length" class="sec mt-4 rounded-md bg-surface/40 px-5 py-10 ring-1 ring-inset ring-line-subtle">
      <p class="text-[13.5px] font-medium text-ink">
        {{ repoFilter === null ? "No run has been recorded yet" : "No run recorded for this repository" }}
      </p>
      <p class="mt-1.5 max-w-[54ch] text-[12.5px] leading-relaxed text-ink-muted">
        It has never been reached by a pass. If it was only just added, the next run at 02:00 UTC
        will be its first.
      </p>
    </div>

    <div v-else class="sec relative mt-4 overflow-x-auto" style="animation-delay: 120ms">
      <table class="w-full min-w-[880px] border-collapse text-left">
        <caption class="sr-only">Sync runs, newest first, with what each pass ingested.</caption>
        <thead>
          <tr class="border-b border-line-subtle">
            <th scope="col" :class="[MONO_LABEL, 'py-2 pr-3 text-ink-faint']">Started</th>
            <th scope="col" :class="[MONO_LABEL, 'py-2 pr-3 text-ink-faint']">Repository</th>
            <th scope="col" :class="[MONO_LABEL, 'py-2 pr-3 text-ink-faint']" title="Inferred from the hour: sync_runs records no trigger">
              Trigger (inferred)
            </th>
            <th scope="col" :class="[MONO_LABEL, 'py-2 pr-3 text-ink-faint']">Duration</th>
            <th v-for="head in ['Commits', 'Branches', 'PRs', 'Issues']" :key="head" scope="col" :class="[MONO_LABEL, 'px-3 py-2 text-right text-ink-faint']">
              {{ head }}
            </th>
            <th scope="col" :class="[MONO_LABEL, 'py-2 pl-3 text-ink-faint']">Outcome</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="(run, i) in rows" :key="run.id">
            <tr class="sec border-b border-line-subtle/70" :style="`animation-delay: ${Math.min(i, 3) * 40}ms`">
              <td class="mono whitespace-nowrap py-2.5 pr-3 text-[12px] text-ink">{{ formatStamp(run.started_at) }}</td>
              <td class="mono py-2.5 pr-3 text-[12px] text-ink-muted">
                {{ run.repo_full_name ?? (run.repo_id === null ? "whole run" : repoName(run.repo_id)) }}
              </td>
              <td class="py-2.5 pr-3 text-[12px] text-ink-muted">{{ inferTrigger(run) }}</td>
              <td class="mono py-2.5 pr-3 text-[12px] text-ink-muted">{{ runDuration(run) }}</td>
              <td
                v-for="key in (['commits', 'branches', 'pull_requests', 'issues'] as const)"
                :key="key"
                class="mono px-3 py-2.5 text-right text-[12px] text-ink-muted"
              >
                <template v-if="parseSyncCounts(run.detail)">{{ parseSyncCounts(run.detail)![key] }}</template>
                <template v-else>—</template>
              </td>
              <td class="py-2.5 pl-3">
                <button
                  v-if="!parseSyncCounts(run.detail)"
                  type="button"
                  :aria-expanded="openRun === run.id"
                  :aria-controls="`run-panel-${run.id}`"
                  :class="[FOCUS, TAP, 'inline-flex items-center gap-1.5 rounded px-1 py-1 transition-colors hover:bg-surface-hover']"
                  @click="openRun = openRun === run.id ? null : run.id"
                >
                  <StatusDot :tone="runTone(run.status)" quiet>{{ runLabel(run.status) }}</StatusDot>
                  <Icon name="chevronDown" :class="['h-3 w-3 text-ink-faint transition-transform duration-150', openRun === run.id && 'rotate-180']" />
                </button>
                <StatusDot v-else :tone="runTone(run.status)" quiet>{{ runLabel(run.status) }}</StatusDot>
              </td>
            </tr>

            <tr v-if="!parseSyncCounts(run.detail)" class="border-b border-line-subtle/70">
              <td :colspan="9" class="p-0">
                <div :id="`run-panel-${run.id}`" class="sec-collapse" :data-open="openRun === run.id ? 'true' : 'false'" :aria-hidden="openRun !== run.id">
                  <div>
                    <div class="bg-sunken/50 px-4 py-4">
                      <p :class="[MONO_LABEL, 'text-ink-faint']">sync_run {{ run.id }} · detail</p>
                      <p class="mono mt-2 max-w-[100ch] break-words text-[12px] leading-relaxed text-ink">
                        {{ run.detail ?? "The worker recorded no detail for this row." }}
                      </p>
                      <div v-if="isPlatformAdmin && connected" class="mt-3.5 flex flex-wrap gap-2">
                        <Btn
                          size="sm"
                          variant="secondary"
                          :disabled="openRun !== run.id"
                          :busy="syncNow.isPending.value"
                          @click="syncNow.mutate()"
                        >Run the sync again</Btn>
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

    <p class="mono mt-4 text-[12px] text-ink-muted">
      {{ rows.length }} of {{ runs?.total ?? rows.length }} runs · get
      /github/sync-runs?limit=50&offset=0<template v-if="repoFilter !== null">&repo_id={{ repoFilter }}</template>
    </p>

    <p class="mt-6 max-w-[86ch] text-[12.5px] leading-relaxed text-ink-muted">
      The counts above are parsed out of <span class="mono text-[12px]">detail</span>, one string
      the worker writes per repository. When it does not parse — a failure, a rate limit, a skip —
      the cells read <span class="mono">—</span> and the row opens to show the raw string. Reviews
      are ingested with their pull request and are not counted separately there. Trigger is
      inferred from the hour: <span class="mono text-[12px]">sync_runs</span> records no trigger
      column, so a run that happened to start at 02:xx by hand reads as scheduled.
    </p>

    <p class="mt-3 max-w-[86ch] text-[12.5px] leading-relaxed text-ink-muted">
      Sync now is a platform-admin action and it is rate limited to five a minute: the run is
      handed to the worker rather than done on the request, so it answers immediately and the rows
      above fill in as each repository finishes.
    </p>

    <!-- Disconnecting is not just a setting. -->
    <Modal
      :open="confirmDisconnect"
      title="Disconnect this GitHub account?"
      :description="account ? `The stored token for ${account.github_login} is deleted. Everything already synced stays exactly as it is.` : undefined"
      :close-on-backdrop="false"
      @close="confirmDisconnect = false"
    >
      <ul class="space-y-2 text-[12.5px] leading-relaxed text-ink-muted">
        <li class="flex gap-2">
          <span class="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-ink-faint" aria-hidden="true" />
          Runs that relied on this token stop finding anything. If it is the only account
          connected, the whole sync records an error rather than quietly doing nothing.
        </li>
        <li class="flex gap-2">
          <span class="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-ink-faint" aria-hidden="true" />
          Commits, pull requests, reviews and issues already ingested stay, and so does every
          report drafted from them.
        </li>
        <li class="flex gap-2">
          <span class="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-ink-faint" aria-hidden="true" />
          Your Activity counts stop moving from the next run. Nothing warns you a second time —
          four zeroes look the same as a quiet week.
        </li>
        <li class="flex gap-2">
          <span class="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-ink-faint" aria-hidden="true" />
          Reconnecting the same GitHub account later resumes from each repository's stored cursor,
          so the gap is refetched.
        </li>
      </ul>
      <template #footer>
        <Btn size="sm" variant="ghost" @click="confirmDisconnect = false">Keep it connected</Btn>
        <Btn size="sm" variant="destructive" :busy="disconnect.isPending.value" @click="disconnect.mutate()">
          Disconnect
        </Btn>
      </template>
    </Modal>
  </PulseShell>
</template>
