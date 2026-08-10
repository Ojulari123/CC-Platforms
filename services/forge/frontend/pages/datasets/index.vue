<script setup lang="ts">
import { keepPreviousData, useQuery } from "@tanstack/vue-query";
import type { DatasetResponse, Page } from "~/types/api";

definePageMeta({ middleware: "auth" });

const api = useApi();

const PAGE_SIZE = 50;
const offset = ref(0);

// keepPreviousData holds the current rows on screen while the next page loads,
// so paging doesn't flash.
const { data, isPending, isError, error } = useQuery({
  queryKey: ["datasets", offset],
  queryFn: () =>
    api.request<Page<DatasetResponse>>("/datasets", {
      query: { limit: PAGE_SIZE, offset: offset.value },
    }),
  placeholderData: keepPreviousData,
});

const total = computed(() => data.value?.total ?? 0);
const rangeStart = computed(() => (total.value === 0 ? 0 : offset.value + 1));
const rangeEnd = computed(() => Math.min(offset.value + PAGE_SIZE, total.value));
const hasPrev = computed(() => offset.value > 0);
const hasNext = computed(() => rangeEnd.value < total.value);

function prevPage() {
  offset.value = Math.max(0, offset.value - PAGE_SIZE);
}

function nextPage() {
  if (hasNext.value) offset.value += PAGE_SIZE;
}
</script>

<template>
  <div class="mx-auto max-w-4xl px-4 py-8">
    <header class="mb-8">
      <h1 class="text-xl font-semibold">Datasets</h1>
      <p class="text-sm text-gray-500">
        Your uploads plus the shared samples everyone can open.
      </p>
    </header>

    <DatasetUpload />

    <p v-if="isPending" class="text-sm text-gray-500">Loading datasets…</p>

    <p v-else-if="isError" class="text-sm text-red-600">
      Could not load datasets: {{ (error as Error)?.message ?? "unknown error" }}
    </p>

    <p v-else-if="!data || data.items.length === 0" class="text-sm text-gray-500">
      No datasets yet.
    </p>

    <template v-else>
      <div class="overflow-hidden rounded-lg border border-gray-200 bg-white">
        <table class="w-full text-left text-sm">
          <thead class="border-b border-gray-200 bg-gray-50 text-gray-600">
            <tr>
              <th class="px-4 py-2 font-medium">Name</th>
              <th class="px-4 py-2 font-medium">Columns</th>
              <th class="px-4 py-2 font-medium">Rows</th>
              <th class="px-4 py-2 font-medium"></th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="ds in data.items"
              :key="ds.id"
              class="border-b border-gray-100 last:border-0 hover:bg-gray-50"
            >
              <td class="px-4 py-2 font-medium">
                <NuxtLink
                  :to="`/datasets/${ds.id}`"
                  class="text-gray-900 hover:underline"
                >
                  {{ ds.name }}
                </NuxtLink>
              </td>
              <td class="px-4 py-2 text-gray-600">{{ ds.columns.length }}</td>
              <td class="px-4 py-2 text-gray-600">{{ ds.row_count }}</td>
              <td class="px-4 py-2">
                <span
                  v-if="ds.is_sample"
                  class="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700"
                >
                  sample
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="mt-4 flex items-center justify-between">
        <p class="text-sm text-gray-500">
          Showing {{ rangeStart }}–{{ rangeEnd }} of {{ total }}
        </p>
        <div class="flex gap-2">
          <button
            type="button"
            :disabled="!hasPrev"
            class="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium hover:bg-gray-50 disabled:opacity-50"
            @click="prevPage"
          >
            Previous
          </button>
          <button
            type="button"
            :disabled="!hasNext"
            class="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium hover:bg-gray-50 disabled:opacity-50"
            @click="nextPage"
          >
            Next
          </button>
        </div>
      </div>
    </template>
  </div>
</template>
