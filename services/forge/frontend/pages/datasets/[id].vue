<script setup lang="ts">
import { useQuery, useMutation, useQueryClient } from "@tanstack/vue-query";
import type { DatasetResponse, DatasetPreview } from "~/types/api";

definePageMeta({ middleware: "auth" });

const route = useRoute();
const router = useRouter();
const api = useApi();
const queryClient = useQueryClient();

const id = computed(() => route.params.id as string);

const {
  data: dataset,
  isPending: metaPending,
  isError: metaError,
  error: metaErr,
} = useQuery({
  queryKey: computed(() => ["dataset", id.value]),
  queryFn: () => api.request<DatasetResponse>(`/datasets/${id.value}`),
});

const {
  data: preview,
  isPending: previewPending,
  isError: previewError,
  error: previewErr,
} = useQuery({
  queryKey: computed(() => ["dataset", id.value, "preview"]),
  queryFn: () => api.request<DatasetPreview>(`/datasets/${id.value}/preview`),
});

function statusOf(err: unknown): number | undefined {
  return (err as { statusCode?: number; status?: number })?.statusCode
    ?? (err as { status?: number })?.status;
}

const notFound = computed(() => {
  const s = statusOf(metaErr.value) ?? statusOf(previewErr.value);
  return s === 403 || s === 404;
});

const confirming = ref(false);

const deleteMutation = useMutation({
  mutationFn: () =>
    api.request<void>(`/datasets/${id.value}`, { method: "DELETE" }),
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: ["datasets"] });
    router.push("/datasets");
  },
});
</script>

<template>
  <div class="mx-auto max-w-5xl px-4 py-8">
    <header class="mb-6">
      <NuxtLink to="/datasets" class="text-sm text-gray-500 hover:underline">
        &larr; Back to datasets
      </NuxtLink>
    </header>

    <p v-if="metaPending" class="text-sm text-gray-500">Loading dataset…</p>

    <p v-else-if="notFound" class="text-sm text-gray-600">
      Dataset not found, or it isn't yours.
    </p>

    <p v-else-if="metaError" class="text-sm text-red-600">
      Could not load dataset: {{ (metaErr as Error)?.message ?? "unknown error" }}
    </p>

    <div v-else-if="dataset">
      <div class="mb-6 flex items-start justify-between gap-4">
        <div>
          <div class="flex items-center gap-2">
            <h1 class="text-xl font-semibold">{{ dataset.name }}</h1>
            <span
              v-if="dataset.is_sample"
              class="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700"
            >
              sample
            </span>
          </div>
          <p class="mt-1 text-sm text-gray-500">
            {{ dataset.columns.length }} columns · {{ dataset.row_count }} rows
            <template v-if="dataset.original_filename">
              · {{ dataset.original_filename }}
            </template>
          </p>
        </div>

        <div v-if="!dataset.is_sample" class="shrink-0">
          <div v-if="!confirming">
            <button
              class="rounded-md border border-red-300 px-3 py-2 text-sm font-medium text-red-700 hover:bg-red-50"
              @click="confirming = true"
            >
              Delete
            </button>
          </div>
          <div v-else class="flex items-center gap-2">
            <span class="text-sm text-gray-600">Are you sure?</span>
            <button
              :disabled="deleteMutation.isPending.value"
              class="rounded-md bg-red-600 px-3 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-60"
              @click="deleteMutation.mutate()"
            >
              {{ deleteMutation.isPending.value ? "Deleting…" : "Confirm delete" }}
            </button>
            <button
              class="rounded-md border border-gray-300 px-3 py-2 text-sm font-medium hover:bg-gray-100"
              @click="confirming = false"
            >
              Cancel
            </button>
          </div>
        </div>
      </div>

      <p v-if="deleteMutation.isError.value" class="mb-4 text-sm text-red-600">
        Could not delete this dataset.
      </p>

      <p v-if="previewPending" class="text-sm text-gray-500">Loading preview…</p>

      <p v-else-if="previewError && !notFound" class="text-sm text-red-600">
        Could not load preview.
      </p>

      <div v-else-if="preview">
        <p
          v-if="preview.truncated"
          class="mb-2 text-xs text-gray-500"
        >
          Showing first {{ preview.rows.length }} of {{ preview.row_count }} rows (truncated).
        </p>

        <div class="overflow-x-auto rounded-lg border border-gray-200 bg-white">
          <table class="w-full text-left text-sm">
            <thead class="border-b border-gray-200 bg-gray-50 text-gray-600">
              <tr>
                <th
                  v-for="col in preview.columns"
                  :key="col"
                  class="whitespace-nowrap px-4 py-2 font-medium"
                >
                  {{ col }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(row, rowIndex) in preview.rows"
                :key="rowIndex"
                class="border-b border-gray-100 last:border-0"
              >
                <td
                  v-for="(cell, cellIndex) in row"
                  :key="cellIndex"
                  class="whitespace-nowrap px-4 py-2 text-gray-700"
                >
                  {{ cell }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>
