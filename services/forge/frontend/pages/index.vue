<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import type { DatasetSummary } from "~/types/api";
import { LEARNING_PATHS } from "~/constants/learningPaths";

definePageMeta({ middleware: "auth" });

const auth = useAuth();
const api = useApi();

// /datasets/summary answers both counts and the recent rows in one call. The
// paginated list can't: its `total` blends owned datasets and samples, so
// counting them apart there means walking every page.
const RECENT_COUNT = 5;

const { data, isPending, isError } = useQuery({
  queryKey: ["datasets", "summary"],
  queryFn: () =>
    api.request<DatasetSummary>("/datasets/summary", { query: { recent: RECENT_COUNT } }),
});

const firstName = computed(() => auth.user.value?.first_name ?? null);
const ownedCount = computed(() => data.value?.owned_count ?? 0);
const sampleCount = computed(() => data.value?.sample_count ?? 0);
const recent = computed(() => data.value?.recent ?? []);

const isFirstRun = computed(() => !isPending.value && !isError.value && ownedCount.value === 0);
const firstSample = computed(() => recent.value.find((ds) => ds.is_sample) ?? null);
</script>

<template>
  <div class="mx-auto max-w-5xl px-4 py-8">
    <header class="mb-8">
      <h1 class="text-2xl font-semibold">
        {{ firstName ? `Welcome, ${firstName}` : "Welcome to Forge" }}
      </h1>
      <p class="mt-1 text-sm text-gray-500">
        Load a CSV, look at it, and build a workflow on top of it. No code needed.
      </p>
    </header>

    <p v-if="isPending" class="text-sm text-gray-500">Loading your workspace…</p>

    <p v-else-if="isError" class="text-sm text-red-600">
      Could not reach the Forge API. Check that the service is running.
    </p>

    <template v-else>
      <section v-if="isFirstRun" class="mb-8 rounded-lg border border-gray-200 bg-white p-6">
        <h2 class="text-base font-semibold">Start here</h2>
        <p class="mt-1 text-sm text-gray-500">
          You haven't added any data yet. Either of these gets you to a table of real
          numbers in one click.
        </p>

        <ol class="mt-5 space-y-5">
          <li class="flex gap-3">
            <span
              class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-gray-900 text-xs font-medium text-white"
            >
              1
            </span>
            <div>
              <p class="text-sm font-medium">Open a sample dataset</p>
              <p class="mt-0.5 text-sm text-gray-500">
                We've loaded a couple for you, so there's something to look at right now.
              </p>
              <NuxtLink
                v-if="firstSample"
                :to="`/datasets/${firstSample.id}`"
                class="mt-2 inline-block rounded-md bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-800"
              >
                Open {{ firstSample.name }}
              </NuxtLink>
              <p v-else class="mt-2 text-sm text-gray-500">
                No samples are loaded on this server.
              </p>
            </div>
          </li>

          <li class="flex gap-3">
            <span
              class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-gray-900 text-xs font-medium text-white"
            >
              2
            </span>
            <div class="w-full">
              <p class="text-sm font-medium">Or bring your own CSV</p>
              <p class="mt-0.5 mb-3 text-sm text-gray-500">
                First row is treated as the column headers.
              </p>
              <DatasetUpload />
            </div>
          </li>

          <li class="flex gap-3">
            <span
              class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-gray-900 text-xs font-medium text-white"
            >
              3
            </span>
            <div>
              <p class="text-sm font-medium">Pick a learning path</p>
              <p class="mt-0.5 text-sm text-gray-500">
                Guided routes from a dataset to a result.
                <NuxtLink to="/learning" class="font-medium text-gray-900 hover:underline">
                  See the four paths
                </NuxtLink>
                (they open for real in Week 6).
              </p>
            </div>
          </li>
        </ol>
      </section>

      <section class="mb-8 grid gap-4 sm:grid-cols-3">
        <div class="rounded-lg border border-gray-200 bg-white p-5">
          <p class="text-sm text-gray-500">Your datasets</p>
          <p class="mt-1 text-2xl font-semibold">{{ ownedCount }}</p>
        </div>
        <div class="rounded-lg border border-gray-200 bg-white p-5">
          <p class="text-sm text-gray-500">Shared samples</p>
          <p class="mt-1 text-2xl font-semibold">{{ sampleCount }}</p>
        </div>
        <div class="rounded-lg border border-gray-200 bg-white p-5">
          <p class="text-sm text-gray-500">Learning paths</p>
          <p class="mt-1 text-2xl font-semibold">{{ LEARNING_PATHS.length }}</p>
        </div>
      </section>

      <section v-if="recent.length" class="mb-8">
        <div class="mb-3 flex items-baseline justify-between">
          <h2 class="text-base font-semibold">Recent datasets</h2>
          <NuxtLink to="/datasets" class="text-sm text-gray-500 hover:underline">
            View all
          </NuxtLink>
        </div>

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
                v-for="ds in recent"
                :key="ds.id"
                class="border-b border-gray-100 last:border-0 hover:bg-gray-50"
              >
                <td class="px-4 py-2 font-medium">
                  <NuxtLink :to="`/datasets/${ds.id}`" class="text-gray-900 hover:underline">
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
      </section>

      <section class="grid gap-4 sm:grid-cols-3">
        <NuxtLink
          to="/datasets"
          class="rounded-lg border border-gray-200 bg-white p-5 hover:border-gray-400"
        >
          <p class="text-sm font-medium">Upload a dataset</p>
          <p class="mt-1 text-sm text-gray-500">Drop in a CSV and preview it immediately.</p>
        </NuxtLink>
        <NuxtLink
          to="/learning"
          class="rounded-lg border border-gray-200 bg-white p-5 hover:border-gray-400"
        >
          <p class="text-sm font-medium">Browse learning paths</p>
          <p class="mt-1 text-sm text-gray-500">Classification, regression, time series, LLM.</p>
        </NuxtLink>
        <NuxtLink
          to="/canvas"
          class="rounded-lg border border-gray-200 bg-white p-5 hover:border-gray-400"
        >
          <p class="text-sm font-medium">Preview the canvas</p>
          <p class="mt-1 text-sm text-gray-500">Where workflows get built. Sketch only for now.</p>
        </NuxtLink>
      </section>
    </template>
  </div>
</template>
