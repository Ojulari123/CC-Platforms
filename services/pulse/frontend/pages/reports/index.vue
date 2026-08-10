<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import type { DepartmentResponse, Page, ReportResponse, ReportStatus } from "~/types/api";

definePageMeta({ middleware: "auth" });

const auth = useAuth();
const api = useApi();
const identity = useIdentityApi();
const { repositories, repoName } = useRepositories();
const { others: teammates } = useTeammates();

const STATUSES: ReportStatus[] = [
  "draft",
  "submitted",
  "changes_requested",
  "approved",
  "rejected",
];
const LIMIT = 20;

const statusFilter = ref<ReportStatus | null>(null);
const repoFilter = ref<number | null>(null);
const deptFilter = ref<number | null>(null);
const authorFilter = ref<number | null>(null);
const offset = ref(0);

const { data: departments } = useQuery({
  queryKey: ["departments"],
  queryFn: () => identity.request<DepartmentResponse[]>("/departments"),
});

watch([statusFilter, repoFilter, deptFilter, authorFilter], () => {
  offset.value = 0;
});

const { data, isPending, isError, error } = useQuery({
  queryKey: computed(() => [
    "reports",
    statusFilter.value ?? "any",
    repoFilter.value ?? "any",
    deptFilter.value ?? "any",
    authorFilter.value ?? "any",
    offset.value,
  ]),
  queryFn: () =>
    api.request<Page<ReportResponse>>("/reports", {
      query: {
        status: statusFilter.value ?? undefined,
        repo_id: repoFilter.value ?? undefined,
        dept_id: deptFilter.value ?? undefined,
        author_user_id: authorFilter.value ?? undefined,
        limit: LIMIT,
        offset: offset.value,
      },
    }),
});

const items = computed(() => data.value?.items ?? []);
const total = computed(() => data.value?.total ?? 0);
const showingTo = computed(() => Math.min(offset.value + LIMIT, total.value));
const anyFilter = computed(
  () =>
    statusFilter.value !== null ||
    repoFilter.value !== null ||
    deptFilter.value !== null ||
    authorFilter.value !== null,
);

const selfId = computed(() => auth.user.value?.id ?? null);

function clearFilters() {
  statusFilter.value = null;
  repoFilter.value = null;
  deptFilter.value = null;
  authorFilter.value = null;
}
</script>

<template>
  <div class="mx-auto max-w-6xl px-4 py-8">
    <header class="mb-6">
      <h1 class="text-2xl font-semibold">Reports</h1>
      <p class="mt-1 text-sm text-gray-500">
        Your weekly reports, plus any you can see as a repository lead, deputy or
        department admin.
      </p>
    </header>

    <NewReportForm />

    <section class="mb-6 flex flex-wrap items-end gap-4">
      <div>
        <label for="f-status" class="mb-1 block text-xs font-medium text-gray-600">Status</label>
        <select
          id="f-status"
          v-model="statusFilter"
          class="w-48 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm"
        >
          <option :value="null">Any status</option>
          <option v-for="value in STATUSES" :key="value" :value="value">
            {{ statusLabel(value) }}
          </option>
        </select>
      </div>

      <div>
        <label for="f-repo" class="mb-1 block text-xs font-medium text-gray-600">Repository</label>
        <select
          id="f-repo"
          v-model="repoFilter"
          class="w-64 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm"
        >
          <option :value="null">Any repository</option>
          <option v-for="repo in repositories" :key="repo.id" :value="repo.id">
            {{ repo.full_name }}
          </option>
        </select>
      </div>

      <div>
        <label for="f-dept" class="mb-1 block text-xs font-medium text-gray-600">Department</label>
        <select
          id="f-dept"
          v-model="deptFilter"
          class="w-48 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm"
        >
          <option :value="null">Any department</option>
          <option v-for="dept in departments ?? []" :key="dept.id" :value="dept.id">
            {{ dept.name }}
          </option>
        </select>
      </div>

      <div>
        <label for="f-author" class="mb-1 block text-xs font-medium text-gray-600">Author</label>
        <select
          id="f-author"
          v-model="authorFilter"
          class="w-48 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm"
        >
          <option :value="null">Anyone</option>
          <option v-if="selfId !== null" :value="selfId">Me</option>
          <option v-for="mate in teammates" :key="mate.user_id" :value="mate.user_id">
            {{ mate.first_name }} {{ mate.last_name }}
          </option>
        </select>
      </div>

      <button
        v-if="anyFilter"
        class="rounded-md border border-gray-300 px-3 py-2 text-sm font-medium hover:bg-gray-100"
        @click="clearFilters"
      >
        Clear filters
      </button>
    </section>

    <p v-if="isPending" class="text-sm text-gray-500">Loading reports…</p>

    <p v-else-if="isError" class="text-sm text-red-600">
      {{ apiMessage(error, "Could not load reports. Check that the Pulse service is running.") }}
    </p>

    <div v-else-if="!items.length" class="rounded-lg border border-gray-200 bg-white p-6">
      <p class="text-sm font-medium">No reports {{ anyFilter ? "match these filters" : "yet" }}.</p>
      <p class="mt-1 text-sm text-gray-500">
        <template v-if="anyFilter">Widen or clear the filters to see more.</template>
        <template v-else>
          Reports are written per repository, per week, by people who have synced
          activity in that repository. Start one above.
        </template>
      </p>
    </div>

    <template v-else>
      <div class="overflow-x-auto rounded-lg border border-gray-200 bg-white">
        <table class="w-full text-left text-sm">
          <thead class="border-b border-gray-200 bg-gray-50 text-gray-600">
            <tr>
              <th class="whitespace-nowrap px-4 py-2 font-medium">Week</th>
              <th class="px-4 py-2 font-medium">Repository</th>
              <th class="px-4 py-2 font-medium">Author</th>
              <th class="px-4 py-2 font-medium">Status</th>
              <th class="whitespace-nowrap px-4 py-2 font-medium">Updated</th>
              <th class="px-4 py-2 font-medium"></th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="report in items"
              :key="report.id"
              class="border-b border-gray-100 last:border-0 hover:bg-gray-50"
            >
              <td class="whitespace-nowrap px-4 py-2 font-medium">
                {{ formatDate(report.week_start) }}
              </td>
              <td class="px-4 py-2 text-gray-600">{{ repoName(report.repo_id) }}</td>
              <td class="px-4 py-2 text-gray-600">
                {{ personName(report.author, report.author_user_id) }}
              </td>
              <td class="px-4 py-2">
                <span
                  class="rounded-full px-2 py-0.5 text-xs font-medium"
                  :class="statusClass(report.status)"
                >
                  {{ statusLabel(report.status) }}
                </span>
              </td>
              <td class="whitespace-nowrap px-4 py-2 text-gray-600">
                {{ formatDate(report.updated_at) }}
              </td>
              <td class="whitespace-nowrap px-4 py-2">
                <NuxtLink
                  :to="`/reports/${report.id}`"
                  class="font-medium text-gray-900 hover:underline"
                >
                  Open
                </NuxtLink>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="mt-4 flex items-center justify-between text-sm text-gray-500">
        <span>Showing {{ offset + 1 }}–{{ showingTo }} of {{ total }}</span>
        <div class="flex gap-2">
          <button
            :disabled="offset === 0"
            class="rounded-md border border-gray-300 px-3 py-1.5 font-medium hover:bg-gray-100 disabled:opacity-40"
            @click="offset = Math.max(0, offset - LIMIT)"
          >
            Previous
          </button>
          <button
            :disabled="showingTo >= total"
            class="rounded-md border border-gray-300 px-3 py-1.5 font-medium hover:bg-gray-100 disabled:opacity-40"
            @click="offset = offset + LIMIT"
          >
            Next
          </button>
        </div>
      </div>
    </template>
  </div>
</template>
