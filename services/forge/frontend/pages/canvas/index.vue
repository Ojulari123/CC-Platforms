<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { FOCUS, MONO_LABEL } from "@crescent/ui/utils/ui";
import type { DatasetResponse, Page, WorkflowKind, WorkflowResponse } from "~/types/api";
import { formatStamp } from "~/utils/upload";
import { KIND_OPTIONS, apiDetail, starterSteps } from "~/utils/workflows";

definePageMeta({ middleware: "auth" });

const api = useApi();
const queryClient = useQueryClient();
const { toast, show, clear } = useToast();

const name = ref("");

// `?task=` lets the learning pages send someone to the task they were just reading about
// with it already picked. An unknown value falls back rather than throwing.
const route = useRoute();
const requested = KIND_OPTIONS.find((option) => option.value === route.query.task);

const kind = ref<WorkflowKind>(requested?.value ?? "tabular_classification");
const datasetId = ref("");

const chosen = computed(() => KIND_OPTIONS.find((option) => option.value === kind.value)!);

const workflows = useQuery({
  queryKey: ["workflows", "list"],
  queryFn: () => api.request<Page<WorkflowResponse>>("/workflows", { query: { limit: 50 } }),
});

const datasets = useQuery({
  queryKey: ["datasets", "for-workflows"],
  queryFn: () => api.request<Page<DatasetResponse>>("/datasets", { query: { limit: 100 } }),
});

const datasetOptions = computed(() =>
  (datasets.data.value?.items ?? []).map((d) => ({ value: String(d.id), label: `${d.name} · ${d.row_count} rows` })),
);

const columns = computed(() => (datasets.data.value?.items ?? []).find((d) => String(d.id) === datasetId.value)?.columns ?? []);

/* Asked for here rather than on the canvas because the server refuses a workflow whose
   target step has no column, so a canvas that opened without one could never be saved.
   The last column is the convention in a teaching CSV, so that is the starting guess. */
const column = ref("");

watch(columns, (next) => {
  if (!next.includes(column.value)) column.value = next[next.length - 1] ?? "";
});

const columnLabel = computed(() => (kind.value === "timeseries_forecast" ? "Column to forecast" : "Column to predict"));

// The playground has no dataset and no target, so the same field carries its first prompt.
const prompt = ref("");

const canCreate = computed(() =>
  name.value.trim().length > 0
  && (chosen.value.needsDataset
    ? datasetId.value !== "" && column.value !== ""
    : prompt.value.trim().length > 0),
);

const create = useMutation({
  mutationFn: () =>
    api.request<WorkflowResponse>("/workflows", {
      method: "POST",
      body: {
        name: name.value.trim(),
        kind: kind.value,
        dataset_id: chosen.value.needsDataset ? Number(datasetId.value) : null,
        steps: starterSteps(kind.value, chosen.value.needsDataset ? column.value : prompt.value.trim()),
      },
    }),
  onSuccess: (workflow) => {
    queryClient.invalidateQueries({ queryKey: ["workflows"] });
    navigateTo(`/canvas/${workflow.id}`);
  },
  onError: (err: unknown) => show(apiDetail(err, "The workflow could not be created."), "bad"),
});

const remove = useMutation({
  mutationFn: (workflow: WorkflowResponse) => api.request<void>(`/workflows/${workflow.id}`, { method: "DELETE" }),
  onSuccess: (_result, workflow) => {
    queryClient.invalidateQueries({ queryKey: ["workflows"] });
    show(`${workflow.name} deleted`);
  },
  onError: (err: unknown) => show(apiDetail(err, "Delete failed."), "bad"),
});

const items = computed(() => workflows.data.value?.items ?? []);

function kindLabel(value: string): string {
  return KIND_OPTIONS.find((option) => option.value === value)?.label ?? value;
}
</script>

<template>
  <div>
    <section>
      <Eyebrow>Forge · workflow canvas</Eyebrow>
      <h1 class="mt-3 max-w-[24ch] text-[clamp(1.5rem,2.2vw,1.9rem)] font-semibold tracking-[-0.035em]">
        Build a workflow, step by step
      </h1>
      <p class="mt-3 max-w-[64ch] text-[13px] leading-relaxed text-ink-muted">
        A workflow is an ordered list of steps: read the data, prepare it, hold some rows back,
        fit a model, score it. Every step stays on screen with its settings visible, so you can
        read down the canvas and know what will happen before you run anything.
      </p>
    </section>

    <section class="mt-10 border-t border-line-subtle pt-8">
      <h2 class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">Start a workflow</h2>
      <p class="mt-2 max-w-[64ch] text-[12.5px] leading-relaxed text-ink-muted">
        Pick what you are trying to predict. The canvas opens pre-filled with the shortest set of
        steps that will run, and you change it from there.
      </p>

      <fieldset class="mt-6">
        <legend :class="[MONO_LABEL, 'text-ink-muted']">Task</legend>
        <div class="mt-3 grid gap-3 sm:grid-cols-2">
          <label
            v-for="option in KIND_OPTIONS"
            :key="option.value"
            :class="[
              'cursor-pointer rounded-md bg-surface/40 px-4 py-3 ring-1 ring-inset transition-colors',
              kind === option.value ? 'ring-line-strong' : 'ring-line-subtle hover:bg-surface-hover',
            ]"
          >
            <span class="flex items-center gap-2.5">
              <input v-model="kind" :class="[FOCUS, 'h-4 w-4 accent-[color:var(--ink)]']" type="radio" :value="option.value" name="workflow-kind">
              <span class="text-[13.5px] font-medium text-ink">{{ option.label }}</span>
            </span>
            <span class="mt-1.5 block max-w-[52ch] text-[12.5px] leading-relaxed text-ink-muted">
              {{ option.blurb }}
            </span>
          </label>
        </div>
      </fieldset>

      <div class="mt-6 grid gap-5 sm:grid-cols-2">
        <div>
          <label :class="[MONO_LABEL, 'block text-ink-muted']" for="workflow-name">Name</label>
          <input
            id="workflow-name"
            v-model="name"
            :class="[FOCUS, 'mt-1.5 w-full rounded-md bg-sunken px-3 py-2.5 text-[12.5px] text-ink ring-1 ring-inset ring-line transition-colors placeholder:text-ink-faint hover:ring-line-strong']"
            type="text"
            placeholder="Titanic survival, first attempt"
          >
        </div>
        <div v-if="chosen.needsDataset">
          <p :class="[MONO_LABEL, 'text-ink-muted']">Dataset</p>
          <div class="mt-1.5">
            <Select
              v-model="datasetId"
              :options="datasetOptions"
              label="Dataset"
              placeholder="Choose a dataset"
            />
          </div>
          <p v-if="!datasetOptions.length" class="mt-1.5 text-[12px] text-ink-muted">
            No datasets yet. Upload a CSV under Datasets first.
          </p>
        </div>
        <div v-if="!chosen.needsDataset" class="sm:col-span-2">
          <label :class="[MONO_LABEL, 'block text-ink-muted']" for="workflow-prompt">First prompt</label>
          <textarea
            id="workflow-prompt"
            v-model="prompt"
            :class="[FOCUS, 'mt-1.5 w-full resize-y rounded-md bg-sunken px-3 py-2.5 text-[12.5px] leading-relaxed text-ink ring-1 ring-inset ring-line transition-colors placeholder:text-ink-faint hover:ring-line-strong']"
            rows="3"
            placeholder="Summarise this text in three bullet points."
          />
          <p class="mt-1.5 max-w-[52ch] text-[12px] leading-relaxed text-ink-muted">
            You can rewrite it on the canvas, and paste your own text there for the answer to draw on.
          </p>
        </div>
        <div v-if="chosen.needsDataset && columns.length">
          <p :class="[MONO_LABEL, 'text-ink-muted']">{{ columnLabel }}</p>
          <div class="mt-1.5">
            <Select
              v-model="column"
              :options="columns.map((c) => ({ value: c, label: c }))"
              :label="columnLabel"
              placeholder="Choose a column"
            />
          </div>
          <p class="mt-1.5 max-w-[52ch] text-[12px] leading-relaxed text-ink-muted">
            Everything else is a column the model may learn from. You can change this on the canvas.
          </p>
        </div>
      </div>

      <Btn class="mt-6" :disabled="!canCreate" :busy="create.isPending.value" @click="create.mutate()">
        Open the canvas
      </Btn>
    </section>

    <section class="mt-12 border-t border-line-subtle pt-8">
      <div class="flex flex-wrap items-baseline justify-between gap-3">
        <h2 class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">Your workflows</h2>
        <span :class="[MONO_LABEL, 'text-ink-muted']">{{ items.length }} saved</span>
      </div>

      <p v-if="workflows.isPending.value" class="mt-4 text-[12.5px] text-ink-muted">Loading.</p>
      <p v-else-if="!items.length" class="mt-4 rounded-md bg-surface/40 px-5 py-8 text-[12.5px] text-ink-muted ring-1 ring-inset ring-line-subtle">
        Nothing saved yet. The workflow you start above will be here when you come back.
      </p>
      <!-- A table rather than a row of spans. Name, task, step count and date read as four
           unlabelled values otherwise, and the columns have to line up between rows. Same
           shape as the dataset list on the overview. -->
      <table v-else class="mt-4 w-full border-collapse text-left">
        <caption class="sr-only">Workflows you have saved, with the task each one runs and when it was made.</caption>
        <thead>
          <tr class="border-y border-line-subtle">
            <th scope="col" :class="[MONO_LABEL, 'py-2 pr-3 font-normal text-ink-faint']">Workflow</th>
            <th scope="col" :class="[MONO_LABEL, 'whitespace-nowrap px-3 py-2 font-normal text-ink-faint']">Task</th>
            <th scope="col" :class="[MONO_LABEL, 'whitespace-nowrap px-3 py-2 text-right font-normal text-ink-faint']">Steps</th>
            <th scope="col" :class="[MONO_LABEL, 'hidden whitespace-nowrap px-3 py-2 font-normal text-ink-faint sm:table-cell']">Created</th>
            <th scope="col" class="py-2 pl-3"><span class="sr-only">Actions</span></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="workflow in items" :key="workflow.id" class="border-b border-line-subtle">
            <td class="w-full max-w-0 py-3.5 pr-3">
              <NuxtLink
                :to="`/canvas/${workflow.id}`"
                :class="[FOCUS, 'block truncate rounded text-[13.5px] font-medium text-ink underline-offset-4 hover:underline']"
              >
                {{ workflow.name }}
              </NuxtLink>
            </td>
            <td class="mono whitespace-nowrap px-3 py-3.5 text-[12px] text-ink-muted">{{ kindLabel(workflow.kind) }}</td>
            <td class="mono whitespace-nowrap px-3 py-3.5 text-right text-[12px] tabular-nums text-ink-muted">
              {{ workflow.steps.length }}
            </td>
            <td class="mono hidden whitespace-nowrap px-3 py-3.5 text-[12px] text-ink-muted sm:table-cell">
              {{ formatStamp(workflow.created_at) }}
            </td>
            <td class="whitespace-nowrap py-3.5 pl-3 text-right">
              <Btn variant="ghost" size="sm" :aria-label="`Delete ${workflow.name}`" @click="remove.mutate(workflow)">
                Delete
              </Btn>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <Toast v-if="toast" :message="toast.message" :tone="toast.tone" @dismiss="clear" />
  </div>
</template>
