<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { FOCUS, MONO_LABEL } from "@crescent/ui/utils/ui";
import type { DatasetPreview, DatasetResponse, DatasetSummary, Page } from "~/types/api";
import { PREVIEW_ROW_CAP, REJECTIONS, statusOf } from "~/utils/upload";

/* The Forge workspace. One rule carries over from the entry page: the part that works
   and the part that does not are never allowed to blur together. Upload, preview and
   delete are real controls against the real datasets API; the guided paths and the
   canvas are a written specification, and they sit below the tool behind a disclosure
   that opens closed. A signed-in workspace opens on the thing that works. */
definePageMeta({ middleware: "auth" });

const LIST_LIMIT = 50;

const auth = useAuth();
const api = useApi();
const queryClient = useQueryClient();
const { toast, show, clear } = useToast();

const list = useQuery({
  queryKey: ["datasets", "list"],
  queryFn: () => api.request<Page<DatasetResponse>>("/datasets", { query: { limit: LIST_LIMIT, offset: 0 } }),
});

// Two cheap counts. The paged list cannot answer them: its `total` blends the datasets
// you own with the shared samples.
const summary = useQuery({
  queryKey: ["datasets", "summary"],
  queryFn: () => api.request<DatasetSummary>("/datasets/summary", { query: { recent: 0 } }),
});

const datasets = computed(() => list.data.value?.items ?? []);
const total = computed(() => list.data.value?.total ?? 0);
const userId = computed(() => auth.user.value?.id ?? null);

const activeId = ref("");

// Keeps the selection pointed at something real as rows arrive and leave.
watch(
  datasets,
  (rows) => {
    if (rows.some((d) => String(d.id) === activeId.value)) return;
    activeId.value = rows[0] ? String(rows[0].id) : "";
  },
  { immediate: true },
);

const active = computed(() => datasets.value.find((d) => String(d.id) === activeId.value) ?? null);

const tabs = computed(() =>
  datasets.value.map((d) => ({
    id: String(d.id),
    label: d.name,
    hint: `${d.row_count.toLocaleString()} rows`,
  })),
);

const preview = useQuery({
  queryKey: computed(() => ["dataset", activeId.value, "preview"]),
  queryFn: () =>
    api.request<DatasetPreview>(`/datasets/${activeId.value}/preview`, { query: { rows: PREVIEW_ROW_CAP } }),
  enabled: computed(() => activeId.value !== ""),
});

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

function onUploaded(ds: DatasetResponse) {
  activeId.value = String(ds.id);
  show(`${ds.name} uploaded · ${ds.row_count.toLocaleString()} rows, ${ds.columns.length} columns`, "ok");
}

const rejection = ref(REJECTIONS[0]!.key);
const shownRejection = computed(() => REJECTIONS.find((r) => r.key === rejection.value) ?? REJECTIONS[0]!);

const hour = new Date().getHours();
const greeting = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
const firstName = computed(() => auth.user.value?.first_name ?? null);

const counts = computed(() => {
  const s = summary.data.value;
  if (!s) return null;
  return `${s.owned_count} yours · ${s.sample_count} shared`;
});
</script>

<template>
  <div>
    <section>
      <Eyebrow>Forge · workspace</Eyebrow>
      <h1 class="sec mt-3 max-w-[20ch] text-[clamp(1.7rem,3.4vw,2.4rem)] font-semibold leading-[1.04] tracking-[-0.035em]">
        {{ firstName ? `${greeting}, ${firstName}.` : `${greeting}.` }}
        <br />
        <span class="text-ink-muted">Start with the part that works.</span>
      </h1>
      <p
        class="mono mt-5 flex flex-wrap items-center gap-x-3 gap-y-1.5 border-y border-line-subtle py-3 text-[12px] uppercase tracking-[0.08em] text-ink-muted"
      >
        <span class="text-ink">live today</span>
        <span aria-hidden="true">·</span>
        <span>csv upload ≤ 5 MB</span>
        <span aria-hidden="true">·</span>
        <span>header row → column names</span>
        <span aria-hidden="true">·</span>
        <span>first {{ PREVIEW_ROW_CAP }} rows</span>
        <span aria-hidden="true">·</span>
        <span>delete your own</span>
      </p>
      <p class="mt-5 max-w-[54ch] text-[13.5px] leading-relaxed text-ink-muted">
        Bring a CSV and you see it immediately: columns, row count, real rows. The guided paths
        and the workflow canvas are described further down but do not run yet — they land in
        week 6, and this page says so everywhere they appear.
      </p>
    </section>

    <section class="mt-10 border-t border-line-subtle pt-10">
      <Eyebrow>Working today</Eyebrow>
      <h2 class="mt-2.5 max-w-[46ch] text-[clamp(1.35rem,2.4vw,1.75rem)] font-semibold leading-[1.15] tracking-[-0.025em]">
        Upload a CSV, see it before you commit to anything
      </h2>
      <p class="mt-3 max-w-[64ch] text-[13px] leading-relaxed text-ink-muted">
        This is the whole of Forge as it stands: a dataset you own, parsed and shown back to
        you, plus the shared datasets so an empty account still has something to open.
      </p>

      <DatasetUpload @uploaded="onUploaded" />

      <!-- preview -->
      <div class="mt-8">
        <p v-if="list.isPending.value" :class="[MONO_LABEL, 'text-ink-muted']">loading datasets…</p>

        <div
          v-else-if="list.isError.value"
          role="alert"
          class="flex flex-wrap items-start gap-x-4 gap-y-3 rounded-md bg-bad-surface px-4 py-3.5 ring-1 ring-inset ring-bad/25"
        >
          <div class="min-w-0 flex-1">
            <p :class="[MONO_LABEL, 'text-bad']">datasets unavailable</p>
            <p class="mt-1 text-[12.5px] leading-relaxed text-ink-muted">
              The Forge API did not answer. Nothing has been lost — the list could not be read.
            </p>
          </div>
          <Btn variant="secondary" size="sm" :busy="list.isFetching.value" @click="list.refetch()">
            Try again
          </Btn>
        </div>

        <div
          v-else-if="datasets.length === 0"
          class="rounded-md border border-line-subtle px-5 py-10"
        >
          <p class="text-[13px] text-ink-muted">Nothing to preview yet.</p>
          <p :class="[MONO_LABEL, 'mt-1.5 text-ink-muted']">
            drop a csv above · the first row becomes the column names
          </p>
        </div>

        <div v-else-if="active" class="overflow-hidden rounded-md bg-surface/40 ring-1 ring-line-subtle">
          <div class="flex flex-wrap items-center gap-x-6 gap-y-2 px-3 pt-2.5 sm:px-4">
            <Tabs
              id="ds"
              v-model="activeId"
              label="Dataset preview"
              variant="mono"
              has-panel
              :items="tabs"
              class="min-w-0 flex-1 border-b-0"
            />
            <span :class="[MONO_LABEL, 'shrink-0 pb-2.5 text-ink-muted']">
              dataset_id {{ active.id }} · {{ active.columns.length }} cols ·
              {{ active.row_count.toLocaleString() }} rows
            </span>
          </div>

          <TabPanel id="ds" :tab="activeId" class="border-t border-line-subtle">
            <p v-if="preview.isPending.value" :class="[MONO_LABEL, 'px-4 py-6 text-ink-muted']">
              loading preview…
            </p>
            <div v-else-if="preview.isError.value" role="alert" class="px-4 py-5">
              <p :class="[MONO_LABEL, 'text-bad']">preview unavailable</p>
              <p class="mt-1.5 text-[12.5px] leading-relaxed text-ink-muted">
                {{
                  statusOf(preview.error.value) === 404
                    ? "That dataset no longer exists."
                    : statusOf(preview.error.value) === 403
                      ? "That dataset is not yours."
                      : "The rows could not be read back. The dataset itself is untouched."
                }}
              </p>
              <Btn variant="secondary" size="sm" class="mt-3" @click="preview.refetch()">Try again</Btn>
            </div>
            <DatasetPreviewTable
              v-else-if="preview.data.value"
              :columns="preview.data.value.columns"
              :rows="preview.data.value.rows"
              :row-count="preview.data.value.row_count"
              :total-columns="active.columns.length"
              :label="active.name"
            />
          </TabPanel>
        </div>
      </div>

      <!-- dataset list -->
      <div class="mt-12 border-t border-line-subtle pt-8">
        <div class="flex flex-wrap items-baseline justify-between gap-3">
          <h2 class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">Datasets</h2>
          <span :class="[MONO_LABEL, 'text-ink-muted']">
            {{ datasets.length }} of {{ total }}<template v-if="counts"> · {{ counts }}</template>
          </span>
        </div>

        <p v-if="list.isPending.value" :class="[MONO_LABEL, 'mt-6 text-ink-muted']">loading…</p>
        <p v-else-if="list.isError.value" :class="[MONO_LABEL, 'mt-6 text-ink-muted']">
          list unavailable · see the message above
        </p>
        <DatasetList
          v-else
          :datasets="datasets"
          :current-user-id="userId"
          :busy="remove.isPending.value"
          @confirm="remove.mutate($event)"
        />

        <p class="mt-3 text-[12.5px] leading-relaxed text-ink-muted">
          You can delete what you uploaded. The shared samples belong to nobody, so the service
          refuses a delete on them and no control is offered.
        </p>
      </div>

      <!-- rejections -->
      <div class="mt-12 grid gap-8 border-t border-line-subtle pt-8 lg:grid-cols-12 lg:gap-12">
        <div class="lg:col-span-4">
          <h2 class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">A bad file gets told why</h2>
          <p class="mt-2.5 text-[13px] leading-relaxed text-ink-muted">
            Five refusals are implemented and each one names the cause. Nothing is silently
            dropped and no half-parsed dataset is ever stored.
          </p>
        </div>
        <div class="lg:col-span-8">
          <div class="flex flex-wrap gap-1.5">
            <button
              v-for="r in REJECTIONS"
              :key="r.key"
              type="button"
              :aria-pressed="rejection === r.key"
              :class="[
                FOCUS,
                'mono rounded px-2.5 py-1.5 text-[12px] ring-1 ring-inset transition-colors',
                rejection === r.key
                  ? 'bg-surface-active text-ink ring-line-strong'
                  : 'bg-surface/40 text-ink-muted ring-line-subtle hover:bg-surface-hover',
              ]"
              @click="rejection = r.key"
            >
              {{ r.chip }}
            </button>
          </div>
          <div class="mt-3 flex items-start gap-2.5 rounded-md bg-bad-surface px-3.5 py-3 ring-1 ring-inset ring-bad/25">
            <span class="mt-[1px] shrink-0 text-bad"><Icon name="alert" class="h-4 w-4" /></span>
            <div>
              <p :class="[MONO_LABEL, 'text-bad']">upload rejected</p>
              <p class="mt-1 text-[12.5px] leading-relaxed text-ink-muted">{{ shownRejection.message }}</p>
            </div>
          </div>
        </div>
      </div>
    </section>

    <RoadmapPanel />

    <Toast v-if="toast" :message="toast.message" :tone="toast.tone" @dismiss="clear" />
  </div>
</template>
