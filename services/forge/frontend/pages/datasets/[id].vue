<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { MONO_LABEL } from "@crescent/ui/utils/ui";
import type { DatasetPreview, DatasetResponse } from "~/types/api";
import { PREVIEW_ROW_CAP, formatStamp, statusOf } from "~/utils/upload";

definePageMeta({ middleware: "auth" });

const route = useRoute();
const router = useRouter();
const auth = useAuth();
const api = useApi();
const queryClient = useQueryClient();
const { toast, show, clear } = useToast();

const id = computed(() => route.params.id as string);

const meta = useQuery({
  queryKey: computed(() => ["dataset", id.value]),
  queryFn: () => api.request<DatasetResponse>(`/datasets/${id.value}`),
});

const preview = useQuery({
  queryKey: computed(() => ["dataset", id.value, "preview"]),
  queryFn: () =>
    api.request<DatasetPreview>(`/datasets/${id.value}/preview`, { query: { rows: PREVIEW_ROW_CAP } }),
});

const dataset = computed(() => meta.data.value ?? null);
const gone = computed(() => {
  const code = statusOf(meta.error.value);
  return code === 403 || code === 404;
});

const deletable = computed(() => {
  const ds = dataset.value;
  const me = auth.user.value?.id ?? null;
  return !!ds && !ds.is_sample && me !== null && ds.owner_user_id === me;
});

const confirming = ref(false);

const remove = useMutation({
  mutationFn: () => api.request<void>(`/datasets/${id.value}`, { method: "DELETE" }),
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: ["datasets"] });
    router.push("/datasets");
  },
  onError: (err: unknown) => {
    confirming.value = false;
    const code = statusOf(err);
    if (code === 403) show("Only the owner can delete that dataset", "bad");
    else if (code === 404) show("That dataset is already gone", "bad");
    else show("Delete failed · the dataset is still there", "bad");
  },
});
</script>

<template>
  <div>
    <NuxtLink
      to="/datasets"
      class="mono inline-flex items-center gap-1.5 rounded text-[11px] uppercase tracking-[0.08em] text-ink-muted outline-none transition-colors hover:text-ink focus-visible:ring-2 focus-visible:ring-[var(--accent-ink)] focus-visible:ring-offset-2 focus-visible:ring-offset-app"
    >
      <Icon name="arrowLeft" class="h-3.5 w-3.5" />
      All datasets
    </NuxtLink>

    <p v-if="meta.isPending.value" :class="[MONO_LABEL, 'mt-8 text-ink-muted']">loading dataset…</p>

    <section v-else-if="gone" class="mt-8">
      <h1 class="text-[clamp(1.5rem,2.2vw,1.9rem)] font-semibold tracking-[-0.035em]">
        No dataset here
      </h1>
      <p class="mt-3 max-w-[54ch] text-[13px] leading-relaxed text-ink-muted">
        dataset_id {{ id }} either does not exist or belongs to someone else. Forge shows you your
        own uploads and the shared samples, nothing further.
      </p>
    </section>

    <section
      v-else-if="meta.isError.value"
      role="alert"
      class="mt-8 flex flex-wrap items-start gap-x-4 gap-y-3 rounded-md bg-bad-surface px-4 py-3.5 ring-1 ring-inset ring-bad/25"
    >
      <div class="min-w-0 flex-1">
        <h1 :class="[MONO_LABEL, 'text-bad']">dataset unavailable</h1>
        <p class="mt-1 text-[12.5px] leading-relaxed text-ink-muted">
          The Forge API did not answer for dataset_id {{ id }}.
        </p>
      </div>
      <Btn variant="secondary" size="sm" :busy="meta.isFetching.value" @click="meta.refetch()">
        Try again
      </Btn>
    </section>

    <template v-else-if="dataset">
      <section class="mt-6">
        <Eyebrow>Forge · dataset</Eyebrow>
        <div class="mt-3 flex flex-wrap items-start justify-between gap-x-6 gap-y-4">
          <div class="min-w-0">
            <h1 class="max-w-[24ch] break-words text-[clamp(1.5rem,2.2vw,1.9rem)] font-semibold tracking-[-0.035em]">
              {{ dataset.name }}
            </h1>
            <p class="mono mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[11px] text-ink-muted">
              <span>dataset_id {{ dataset.id }}</span>
              <span aria-hidden="true">·</span>
              <span>{{ dataset.columns.length }} cols</span>
              <span aria-hidden="true">·</span>
              <span>{{ dataset.row_count.toLocaleString() }} rows</span>
              <span aria-hidden="true">·</span>
              <span>{{ formatStamp(dataset.created_at) }}</span>
              <template v-if="dataset.original_filename">
                <span aria-hidden="true">·</span>
                <span>{{ dataset.original_filename }}</span>
              </template>
              <template v-if="dataset.is_sample">
                <span aria-hidden="true">·</span>
                <span>shared sample</span>
              </template>
            </p>
          </div>
          <Btn v-if="deletable" variant="destructive" size="sm" @click="confirming = true">Delete</Btn>
        </div>
      </section>

      <section class="mt-10 border-t border-line-subtle pt-8">
        <div class="flex flex-wrap items-baseline justify-between gap-3">
          <h2 class="text-[15px] font-semibold tracking-[-0.015em]">First rows</h2>
          <span :class="[MONO_LABEL, 'text-ink-muted']">header row → column names</span>
        </div>

        <p v-if="preview.isPending.value" :class="[MONO_LABEL, 'mt-6 text-ink-muted']">loading preview…</p>

        <div
          v-else-if="preview.isError.value"
          role="alert"
          class="mt-6 flex flex-wrap items-start gap-x-4 gap-y-3 rounded-md bg-bad-surface px-4 py-3.5 ring-1 ring-inset ring-bad/25"
        >
          <div class="min-w-0 flex-1">
            <p :class="[MONO_LABEL, 'text-bad']">preview unavailable</p>
            <p class="mt-1 text-[12.5px] leading-relaxed text-ink-muted">
              The rows could not be read back. The dataset itself is untouched.
            </p>
          </div>
          <Btn variant="secondary" size="sm" @click="preview.refetch()">Try again</Btn>
        </div>

        <p
          v-else-if="preview.data.value && preview.data.value.rows.length === 0"
          :class="[MONO_LABEL, 'mt-6 text-ink-muted']"
        >
          header row only · no data rows to show
        </p>

        <div v-else-if="preview.data.value" class="mt-6 overflow-hidden rounded-md bg-surface/40 ring-1 ring-line-subtle">
          <DatasetPreviewTable
            :columns="preview.data.value.columns"
            :rows="preview.data.value.rows"
            :row-count="preview.data.value.row_count"
            :total-columns="dataset.columns.length"
            :label="dataset.name"
          />
        </div>
      </section>

      <Modal
        :open="confirming"
        title="Delete this dataset?"
        :description="`${dataset.name} — ${dataset.row_count.toLocaleString()} rows, ${dataset.columns.length} columns. The file and its parsed rows go; nothing else references it.`"
        :close-on-backdrop="false"
        @close="confirming = false"
      >
        <p :class="[MONO_LABEL, 'text-ink-muted']">
          dataset_id {{ dataset.id }} · uploaded {{ formatStamp(dataset.created_at) }}
        </p>
        <template #footer>
          <Btn variant="secondary" size="sm" @click="confirming = false">Keep it</Btn>
          <Btn variant="destructive" size="sm" :busy="remove.isPending.value" @click="remove.mutate()">
            Delete dataset
          </Btn>
        </template>
      </Modal>
    </template>

    <Toast v-if="toast" :message="toast.message" :tone="toast.tone" @dismiss="clear" />
  </div>
</template>
