<script setup lang="ts">
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { MONO_LABEL } from "@crescent/ui/utils/ui";
import type { DatasetResponse, Page } from "~/types/api";
import { statusOf } from "~/utils/upload";

definePageMeta({ middleware: "auth" });

const PAGE_SIZE = 50;

const auth = useAuth();
const api = useApi();
const queryClient = useQueryClient();
const { toast, show, clear } = useToast();

const offset = ref(0);

// keepPreviousData holds the current rows on screen while the next page loads, so
// paging does not flash an empty table.
const list = useQuery({
  queryKey: computed(() => ["datasets", "list", offset.value]),
  queryFn: () =>
    api.request<Page<DatasetResponse>>("/datasets", { query: { limit: PAGE_SIZE, offset: offset.value } }),
  placeholderData: keepPreviousData,
});

const datasets = computed(() => list.data.value?.items ?? []);
const total = computed(() => list.data.value?.total ?? 0);
const rangeStart = computed(() => (total.value === 0 ? 0 : offset.value + 1));
const rangeEnd = computed(() => Math.min(offset.value + PAGE_SIZE, total.value));
const hasPrev = computed(() => offset.value > 0);
const hasNext = computed(() => rangeEnd.value < total.value);
const userId = computed(() => auth.user.value?.id ?? null);

const remove = useMutation({
  mutationFn: (ds: DatasetResponse) => api.request<void>(`/datasets/${ds.id}`, { method: "DELETE" }),
  onSuccess: (_result, ds) => {
    queryClient.invalidateQueries({ queryKey: ["datasets"] });
    show(`${ds.name} deleted · dataset_id ${ds.id}`);
  },
  onError: (err: unknown) => {
    const code = statusOf(err);
    if (code === 403) show("Only the owner can delete that dataset", "bad");
    else if (code === 404) show("That dataset is already gone", "bad");
    else show("Delete failed · the dataset is still there", "bad");
  },
});
</script>

<template>
  <div>
    <section>
      <Eyebrow>Forge · datasets</Eyebrow>
      <h1 class="mt-3 max-w-[24ch] text-[clamp(1.5rem,2.2vw,1.9rem)] font-semibold tracking-[-0.035em]">
        Everything you can open
      </h1>
      <p class="mt-3 max-w-[64ch] text-[13px] leading-relaxed text-ink-muted">
        Your uploads plus the shared samples. A sample belongs to nobody, so it can be read and
        previewed but never deleted.
      </p>

      <DatasetUpload @uploaded="offset = 0" />
    </section>

    <section class="mt-12 border-t border-line-subtle pt-8">
      <div class="flex flex-wrap items-baseline justify-between gap-3">
        <h2 class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">All datasets</h2>
        <span :class="[MONO_LABEL, 'text-ink-muted']">
          <template v-if="total">{{ rangeStart }}–{{ rangeEnd }} of {{ total }}</template>
          <template v-else>0 of 0</template>
        </span>
      </div>

      <p v-if="list.isPending.value" :class="[MONO_LABEL, 'mt-6 text-ink-muted']">loading datasets…</p>

      <div
        v-else-if="list.isError.value"
        role="alert"
        class="mt-6 flex flex-wrap items-start gap-x-4 gap-y-3 rounded-md bg-bad-surface px-4 py-3.5 ring-1 ring-inset ring-bad/25"
      >
        <div class="min-w-0 flex-1">
          <p :class="[MONO_LABEL, 'text-bad']">datasets unavailable</p>
          <p class="mt-1 text-[12.5px] leading-relaxed text-ink-muted">
            The Forge API did not answer. The list could not be read; nothing was changed.
          </p>
        </div>
        <Btn variant="secondary" size="sm" :busy="list.isFetching.value" @click="list.refetch()">
          Try again
        </Btn>
      </div>

      <DatasetList
        v-else
        :datasets="datasets"
        :current-user-id="userId"
        :busy="remove.isPending.value"
        @confirm="remove.mutate($event)"
      />

      <div v-if="hasPrev || hasNext" class="mt-6 flex items-center justify-end gap-2">
        <Btn variant="secondary" size="sm" :disabled="!hasPrev" @click="offset = Math.max(0, offset - PAGE_SIZE)">
          Previous
        </Btn>
        <Btn variant="secondary" size="sm" :disabled="!hasNext" @click="offset += PAGE_SIZE">Next</Btn>
      </div>
    </section>

    <Toast v-if="toast" :message="toast.message" :tone="toast.tone" @dismiss="clear" />
  </div>
</template>
