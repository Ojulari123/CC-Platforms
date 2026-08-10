<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import type {
  ActivityResponse,
  GitHubAccountResponse,
  Page,
  SyncRunResponse,
} from "~/types/api";

definePageMeta({ middleware: "auth" });

const auth = useAuth();
const api = useApi();
const route = useRoute();
const router = useRouter();
const { repositories, repoName } = useRepositories();
const { others: teammates, hasDepartment } = useTeammates();

const RANGES = [
  { days: 7, label: "Last 7 days" },
  { days: 30, label: "Last 30 days" },
  { days: 90, label: "Last 90 days" },
  { days: 0, label: "All time" },
];

const selectedUserId = ref<number | null>(null);
const selectedRepoId = ref<number | null>(null);
const rangeDays = ref(30);

const since = computed(() => (rangeDays.value > 0 ? isoDaysAgo(rangeDays.value) : undefined));
const viewingSelf = computed(() => selectedUserId.value === null);

const {
  data: activity,
  isPending,
  isError,
  error,
} = useQuery({
  queryKey: computed(() => [
    "activity",
    selectedUserId.value ?? "me",
    selectedRepoId.value ?? "all",
    since.value ?? "all",
  ]),
  queryFn: () =>
    api.request<ActivityResponse>(
      viewingSelf.value ? "/activity/me" : `/activity/${selectedUserId.value}`,
      { query: { since: since.value, repo_id: selectedRepoId.value ?? undefined } },
    ),
});

const counts = computed(() => activity.value?.counts ?? null);
const isEmpty = computed(() => {
  const c = counts.value;
  return !!c && c.commits === 0 && c.pull_requests === 0 && c.reviews === 0 && c.issues === 0;
});

const { data: githubAccount, isFetched: githubChecked } = useQuery({
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

const { data: syncRuns } = useQuery({
  queryKey: ["sync-runs"],
  enabled: computed(() => viewingSelf.value && isEmpty.value),
  queryFn: () => api.request<Page<SyncRunResponse>>("/github/sync-runs", { query: { limit: 5 } }),
});

const connecting = ref(false);
const connectError = ref<string | null>(null);

async function connectGitHub() {
  connecting.value = true;
  connectError.value = null;
  try {
    const res = await api.request<{ authorize_url: string }>("/github/connect");
    // Same tab on purpose: window.open after an await is outside the click's call
    // stack and gets blocked as a popup.
    window.location.href = res.authorize_url;
  } catch (err: unknown) {
    connectError.value = apiMessage(err, "Could not start the GitHub connection.");
    connecting.value = false;
  }
}

const CONNECT_MESSAGES: Record<string, { ok: boolean; text: string }> = {
  connected: {
    ok: true,
    text: "GitHub connected. Your commits, pull requests and reviews will appear after the next sync.",
  },
  denied: {
    ok: false,
    text: "You cancelled on GitHub, so nothing was connected. You can try again whenever you like.",
  },
  expired: {
    ok: false,
    text: "That connect link was no longer valid — they only last a few minutes. Start again.",
  },
  already_linked: {
    ok: false,
    text: "That GitHub account is already connected to a different Pulse user. Connect a different account, or ask an admin to release it.",
  },
  not_configured: {
    ok: false,
    text: "GitHub connecting isn't set up on this server yet. Ask a platform admin to finish the setup.",
  },
  failed: {
    ok: false,
    text: "Connecting to GitHub didn't finish. Try again, and tell an admin if it keeps happening.",
  },
};

const connectResult = ref<{ ok: boolean; text: string } | null>(null);

onMounted(() => {
  const outcome = route.query.github;
  if (typeof outcome !== "string") return;
  connectResult.value = CONNECT_MESSAGES[outcome] ?? CONNECT_MESSAGES.failed!;
  const { github: _github, ...rest } = route.query;
  router.replace({ query: rest });
});

const selectedTeammate = computed(
  () => teammates.value.find((mate) => mate.user_id === selectedUserId.value) ?? null,
);

const subjectName = computed(() => {
  if (viewingSelf.value) return "You";
  const mate = selectedTeammate.value;
  if (mate) return `${mate.first_name} ${mate.last_name}`.trim();
  const a = activity.value;
  return a ? personName(a.user, a.user_id) : "This person";
});

const selfLabel = computed(() => {
  const me = auth.user.value;
  if (!me) return "You";
  const full = `${me.first_name ?? ""} ${me.last_name ?? ""}`.trim();
  return full ? `${full} (you)` : "You";
});
</script>

<template>
  <div class="mx-auto max-w-6xl px-4 py-8">
    <header class="mb-6">
      <h1 class="text-2xl font-semibold">
        {{ viewingSelf ? "Your GitHub activity" : `${subjectName}'s GitHub activity` }}
      </h1>
      <p class="mt-1 text-sm text-gray-500">
        Synced from GitHub on a daily schedule, attributed to CypherCrescent accounts.
      </p>
    </header>

    <div
      v-if="connectResult"
      class="mb-6 flex items-start justify-between gap-4 rounded-lg border p-4 text-sm"
      :class="
        connectResult.ok
          ? 'border-green-200 bg-green-50 text-green-800'
          : 'border-red-200 bg-red-50 text-red-700'
      "
    >
      <p>{{ connectResult.text }}</p>
      <button class="shrink-0 text-xs underline" @click="connectResult = null">Dismiss</button>
    </div>

    <section class="mb-6 flex flex-wrap items-end gap-4">
      <div>
        <label for="who" class="mb-1 block text-xs font-medium text-gray-600">Whose activity</label>
        <select
          id="who"
          v-model="selectedUserId"
          class="w-56 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm"
        >
          <option :value="null">{{ selfLabel }}</option>
          <option v-for="mate in teammates" :key="mate.user_id" :value="mate.user_id">
            {{ mate.first_name }} {{ mate.last_name }}
          </option>
        </select>
        <p v-if="!hasDepartment" class="mt-1 text-xs text-gray-500">
          You're not in a department yet, so there's nobody else to look at.
        </p>
      </div>

      <div>
        <label for="repo" class="mb-1 block text-xs font-medium text-gray-600">Repository</label>
        <select
          id="repo"
          v-model="selectedRepoId"
          class="w-64 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm"
        >
          <option :value="null">All repositories</option>
          <option v-for="repo in repositories" :key="repo.id" :value="repo.id">
            {{ repo.full_name }}
          </option>
        </select>
      </div>

      <div>
        <label for="range" class="mb-1 block text-xs font-medium text-gray-600">Period</label>
        <select
          id="range"
          v-model="rangeDays"
          class="w-40 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm"
        >
          <option v-for="range in RANGES" :key="range.days" :value="range.days">
            {{ range.label }}
          </option>
        </select>
      </div>
    </section>

    <p v-if="isPending" class="text-sm text-gray-500">Loading activity…</p>

    <p v-else-if="isError" class="text-sm text-red-600">
      {{ apiMessage(error, "Could not reach the Pulse API. Check that the service is running.") }}
    </p>

    <template v-else-if="activity">
      <section class="mb-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div class="rounded-lg border border-gray-200 bg-white p-5">
          <p class="text-sm text-gray-500">Commits</p>
          <p class="mt-1 text-2xl font-semibold">{{ activity.counts.commits }}</p>
        </div>
        <div class="rounded-lg border border-gray-200 bg-white p-5">
          <p class="text-sm text-gray-500">Pull requests</p>
          <p class="mt-1 text-2xl font-semibold">{{ activity.counts.pull_requests }}</p>
        </div>
        <div class="rounded-lg border border-gray-200 bg-white p-5">
          <p class="text-sm text-gray-500">Reviews</p>
          <p class="mt-1 text-2xl font-semibold">{{ activity.counts.reviews }}</p>
        </div>
        <div class="rounded-lg border border-gray-200 bg-white p-5">
          <p class="text-sm text-gray-500">Issues</p>
          <p class="mt-1 text-2xl font-semibold">{{ activity.counts.issues }}</p>
        </div>
      </section>

      <section
        v-if="isEmpty"
        class="mb-8 rounded-lg border border-gray-200 bg-white p-6"
      >
        <h2 class="text-base font-semibold">Nothing here yet</h2>

        <template v-if="!viewingSelf">
          <p class="mt-1 text-sm text-gray-500">
            Either {{ subjectName }} has no synced activity in this period, or none of it
            is in a repository you oversee. Pulse shows you a person's work only through
            the repos you lead, deputise, or whose department you administer.
          </p>
        </template>

        <template v-else-if="githubChecked && !githubAccount">
          <p class="mt-1 text-sm text-gray-500">
            Your GitHub account isn't connected, so nothing can be attributed to you.
            Connect it and the next sync will pick up your work.
          </p>
          <button
            :disabled="connecting"
            class="mt-3 rounded-md bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-60"
            @click="connectGitHub"
          >
            {{ connecting ? "Opening GitHub…" : "Connect GitHub" }}
          </button>
          <p v-if="connectError" class="mt-2 text-sm text-red-600">{{ connectError }}</p>
        </template>

        <template v-else>
          <p class="mt-1 text-sm text-gray-500">
            <template v-if="githubAccount">
              GitHub is connected as <span class="font-medium">@{{ githubAccount.github_login }}</span>.
            </template>
            No commits, pull requests, reviews or issues were synced for this period
            {{ selectedRepoId ? "in this repository" : "" }}. Widen the period, or check
            the last sync below.
          </p>

          <div v-if="syncRuns && syncRuns.items.length" class="mt-4">
            <p class="mb-2 text-xs font-medium text-gray-600">Recent sync passes</p>
            <ul class="space-y-1 text-sm text-gray-600">
              <li v-for="run in syncRuns.items" :key="run.id">
                <span class="font-medium">{{ run.repo_full_name ?? "All repositories" }}</span>
                — {{ run.status }} · {{ formatDateTime(run.started_at) }}
                <span v-if="run.detail" class="text-gray-500">· {{ run.detail }}</span>
              </li>
            </ul>
          </div>
          <p v-else class="mt-4 text-sm text-gray-500">
            No sync has run yet for any repository you can see.
          </p>
        </template>
      </section>

      <section v-else class="grid gap-6 lg:grid-cols-2">
        <div class="rounded-lg border border-gray-200 bg-white">
          <h2 class="border-b border-gray-200 px-4 py-3 text-sm font-semibold">Recent commits</h2>
          <p v-if="!activity.recent_commits.length" class="px-4 py-3 text-sm text-gray-500">
            No commits in this period.
          </p>
          <ul v-else class="divide-y divide-gray-100">
            <li v-for="commit in activity.recent_commits" :key="commit.sha" class="px-4 py-3">
              <a
                v-if="commit.url"
                :href="commit.url"
                target="_blank"
                rel="noopener"
                class="block truncate text-sm font-medium text-gray-900 hover:underline"
              >
                {{ (commit.message ?? "(no message)").split("\n")[0] }}
              </a>
              <p v-else class="truncate text-sm font-medium text-gray-900">
                {{ (commit.message ?? "(no message)").split("\n")[0] }}
              </p>
              <p class="mt-0.5 text-xs text-gray-500">
                {{ repoName(commit.repo_id) }} · {{ commit.sha.slice(0, 7) }} ·
                {{ formatDateTime(commit.committed_at) }}
              </p>
            </li>
          </ul>
        </div>

        <div class="rounded-lg border border-gray-200 bg-white">
          <h2 class="border-b border-gray-200 px-4 py-3 text-sm font-semibold">
            Recent pull requests
          </h2>
          <p v-if="!activity.recent_pull_requests.length" class="px-4 py-3 text-sm text-gray-500">
            No pull requests in this period.
          </p>
          <ul v-else class="divide-y divide-gray-100">
            <li
              v-for="pr in activity.recent_pull_requests"
              :key="`${pr.repo_id}-${pr.number}`"
              class="px-4 py-3"
            >
              <a
                v-if="pr.url"
                :href="pr.url"
                target="_blank"
                rel="noopener"
                class="block truncate text-sm font-medium text-gray-900 hover:underline"
              >
                #{{ pr.number }} {{ pr.title ?? "(no title)" }}
              </a>
              <p v-else class="truncate text-sm font-medium text-gray-900">
                #{{ pr.number }} {{ pr.title ?? "(no title)" }}
              </p>
              <p class="mt-0.5 text-xs text-gray-500">
                {{ repoName(pr.repo_id) }} · {{ pr.merged ? "merged" : pr.state }} ·
                {{ formatDateTime(pr.gh_created_at) }}
              </p>
            </li>
          </ul>
        </div>

        <div class="rounded-lg border border-gray-200 bg-white">
          <h2 class="border-b border-gray-200 px-4 py-3 text-sm font-semibold">Recent reviews</h2>
          <p v-if="!activity.recent_reviews.length" class="px-4 py-3 text-sm text-gray-500">
            No reviews in this period.
          </p>
          <ul v-else class="divide-y divide-gray-100">
            <li
              v-for="(review, index) in activity.recent_reviews"
              :key="`${review.pull_request_id}-${index}`"
              class="px-4 py-3"
            >
              <a
                v-if="review.url"
                :href="review.url"
                target="_blank"
                rel="noopener"
                class="text-sm font-medium text-gray-900 hover:underline"
              >
                Review on pull request #{{ review.pull_request_id }}
              </a>
              <p v-else class="text-sm font-medium text-gray-900">
                Review on pull request #{{ review.pull_request_id }}
              </p>
              <p class="mt-0.5 text-xs text-gray-500">
                {{ review.state }} · {{ formatDateTime(review.submitted_at) }}
              </p>
            </li>
          </ul>
        </div>

        <div class="rounded-lg border border-gray-200 bg-white">
          <h2 class="border-b border-gray-200 px-4 py-3 text-sm font-semibold">Recent issues</h2>
          <p v-if="!activity.recent_issues.length" class="px-4 py-3 text-sm text-gray-500">
            No issues in this period.
          </p>
          <ul v-else class="divide-y divide-gray-100">
            <li
              v-for="issue in activity.recent_issues"
              :key="`${issue.repo_id}-${issue.number}`"
              class="px-4 py-3"
            >
              <a
                v-if="issue.url"
                :href="issue.url"
                target="_blank"
                rel="noopener"
                class="block truncate text-sm font-medium text-gray-900 hover:underline"
              >
                #{{ issue.number }} {{ issue.title ?? "(no title)" }}
              </a>
              <p v-else class="truncate text-sm font-medium text-gray-900">
                #{{ issue.number }} {{ issue.title ?? "(no title)" }}
              </p>
              <p class="mt-0.5 text-xs text-gray-500">
                {{ repoName(issue.repo_id) }} · {{ issue.state }} ·
                {{ formatDateTime(issue.gh_created_at) }}
              </p>
            </li>
          </ul>
        </div>
      </section>
    </template>
  </div>
</template>
