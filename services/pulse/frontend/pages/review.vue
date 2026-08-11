<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import type { Page, ReportResponse, ReportStatus } from "~/types/api";

definePageMeta({ middleware: "auth" });

const api = useApi();
const { repoName } = useRepositories();

const STATUSES: ReportStatus[] = [
  "submitted",
  "changes_requested",
  "approved",
  "rejected",
  "draft",
];
const LIMIT = 20;

const statusFilter = ref<ReportStatus>("submitted");
const offset = ref(0);
const openReportId = ref<number | null>(null);

watch(statusFilter, () => {
  offset.value = 0;
  openReportId.value = null;
});

const { data, isPending, isError, error } = useQuery({
  queryKey: computed(() => ["review-queue", statusFilter.value, offset.value]),
  queryFn: () =>
    api.request<Page<ReportResponse>>("/reports/review-queue", {
      query: { status: statusFilter.value, limit: LIMIT, offset: offset.value },
    }),
});

const items = computed(() => data.value?.items ?? []);
const total = computed(() => data.value?.total ?? 0);
const showingTo = computed(() => Math.min(offset.value + LIMIT, total.value));
</script>

<template>
  <div class="mx-auto max-w-6xl px-4 py-8">
    <header class="mb-6">
      <h1 class="text-2xl font-semibold">Review queue</h1>
      <p class="mt-1 text-sm text-gray-500">
        Reports you can decide on, across every repository you lead or deputise and every
        department you administer.
      </p>
    </header>

    <div class="mb-6">
      <label for="q-status" class="mb-1 block text-xs font-medium text-gray-600">Showing</label>
      <select
        id="q-status"
        v-model="statusFilter"
        class="w-56 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm"
      >
        <option v-for="value in STATUSES" :key="value" :value="value">
          {{ statusLabel(value) }}
        </option>
      </select>
    </div>

    <p v-if="isPending" class="text-sm text-gray-500">Loading queue…</p>

    <p v-else-if="isError" class="text-sm text-red-600">
      {{ apiMessage(error, "Could not load the review queue.") }}
    </p>

    <div v-else-if="!items.length" class="rounded-lg border border-gray-200 bg-white p-6">
      <p class="text-sm font-medium">
        Nothing {{ statusFilter === "submitted" ? "is waiting on you" : "to show" }}.
      </p>
      <p class="mt-1 text-sm text-gray-500">
        This queue only fills up if you're a repository's lead or deputy, or an admin of a
        department a report belongs to.
      </p>
    </div>

    <template v-else>
      <div class="overflow-hidden rounded-lg border border-gray-200 bg-white">
        <table class="w-full text-left text-sm">
          <thead class="border-b border-gray-200 bg-gray-50 text-gray-600">
            <tr>
              <th class="whitespace-nowrap px-4 py-2 font-medium">Week</th>
              <th class="px-4 py-2 font-medium">Repository</th>
              <th class="px-4 py-2 font-medium">Author</th>
              <th class="px-4 py-2 font-medium">Status</th>
              <th class="px-4 py-2 font-medium"></th>
            </tr>
          </thead>
          <tbody>
            <template v-for="report in items" :key="report.id">
              <tr class="border-b border-gray-100 hover:bg-gray-50">
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
                <td class="whitespace-nowrap px-4 py-2">
                  <NuxtLink
                    :to="`/reports/${report.id}`"
                    class="mr-3 font-medium text-gray-900 hover:underline"
                  >
                    Read
                  </NuxtLink>
                  <button
                    v-if="report.status === 'submitted'"
                    class="font-medium text-gray-500 hover:underline"
                    @click="openReportId = openReportId === report.id ? null : report.id"
                  >
                    {{ openReportId === report.id ? "Close" : "Decide" }}
                  </button>
                </td>
              </tr>
              <tr v-if="openReportId === report.id" class="border-b border-gray-100 bg-gray-50">
                <td colspan="5" class="px-4 py-4">
                  <p class="mb-3 text-sm text-gray-500">
                    Deciding without reading it first is your call, but the full report is one
                    click away under Read.
                  </p>
                  <ReportDecision :report-id="report.id" @decided="openReportId = null" />
                </td>
              </tr>
            </template>
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
