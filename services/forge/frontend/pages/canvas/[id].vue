<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { FOCUS, MONO_LABEL } from "@crescent/ui/utils/ui";
import type { DatasetResponse, GeneratedCode, Page, RunResponse, StepCatalog, WorkflowResponse } from "~/types/api";
import { formatStamp, statusOf } from "~/utils/upload";
import {
  KIND_OPTIONS,
  RUN_TONES,
  apiDetail,
  defaultParams,
  formatDuration,
  isSettled,
  orderSteps,
} from "~/utils/workflows";

definePageMeta({ middleware: "auth" });

const route = useRoute();
const api = useApi();
const queryClient = useQueryClient();
const { toast, show, clear } = useToast();

const workflowId = computed(() => Number(route.params.id));

// How often a queued run is asked about, and when to give up. Polling stops the moment
// the run settles either way; a page left open on a finished run must not keep asking.
const POLL_MS = 1500;
const POLL_LIMIT_MS = 5 * 60 * 1000;

const workflow = useQuery({
  queryKey: computed(() => ["workflows", workflowId.value]),
  queryFn: () => api.request<WorkflowResponse>(`/workflows/${workflowId.value}`),
});

const catalog = useQuery({
  queryKey: ["workflows", "steps"],
  queryFn: () => api.request<StepCatalog>("/workflows/steps"),
});

const dataset = useQuery({
  queryKey: computed(() => ["dataset", workflow.data.value?.dataset_id]),
  queryFn: () => api.request<DatasetResponse>(`/datasets/${workflow.data.value!.dataset_id}`),
  enabled: computed(() => Boolean(workflow.data.value?.dataset_id)),
});

const runs = useQuery({
  queryKey: computed(() => ["workflows", workflowId.value, "runs"]),
  queryFn: () => api.request<Page<RunResponse>>(`/workflows/${workflowId.value}/runs`, { query: { limit: 20 } }),
  enabled: computed(() => Number.isFinite(workflowId.value)),
});

// The steps being edited. Held locally so a half-finished change is not sent on every
// keystroke, and written back whenever the server's copy changes underneath.
interface DraftStep {
  kind: string;
  params: Record<string, unknown>;
}

const draft = ref<DraftStep[]>([]);
const savedJson = ref("");

watch(
  () => workflow.data.value,
  (data) => {
    if (!data) return;
    const steps = orderSteps(data.steps).map((step) => ({ kind: step.kind, params: { ...step.params } }));
    draft.value = steps;
    savedJson.value = JSON.stringify(steps);
  },
  { immediate: true },
);

const ordered = computed(() => orderSteps(draft.value));
const dirty = computed(() => JSON.stringify(draft.value) !== savedJson.value);
const columns = computed(() => dataset.data.value?.columns ?? []);
const kindMeta = computed(() => KIND_OPTIONS.find((option) => option.value === workflow.data.value?.kind));

const catalogByKind = computed(() => {
  const map: Record<string, { label: string; summary: string }> = {};
  for (const entry of catalog.data.value?.steps ?? []) map[entry.kind] = { label: entry.label, summary: entry.summary };
  return map;
});

const available = computed(() => {
  const kind = workflow.data.value?.kind;
  const allowed = kind ? catalog.data.value?.steps_by_workflow_kind?.[kind] ?? [] : [];
  const used = new Set(draft.value.map((step) => step.kind));
  // load_csv, the target and the model are one apiece; the server refuses a second one.
  return allowed.filter((step) => !used.has(step));
});

const activeKind = ref("");

function updateStep(index: number, params: Record<string, unknown>) {
  const target = ordered.value[index];
  const position = draft.value.indexOf(target!);
  if (position >= 0) draft.value[position] = { ...target!, params };
}

function removeStep(index: number) {
  const target = ordered.value[index];
  draft.value = draft.value.filter((step) => step !== target);
}

function addStep(kind: string) {
  if (!kind || !workflow.data.value) return;
  draft.value = [...draft.value, { kind, params: defaultParams(kind, workflow.data.value.kind) }];
}

const save = useMutation({
  mutationFn: () =>
    api.request<WorkflowResponse>(`/workflows/${workflowId.value}/steps`, {
      method: "PUT",
      body: { steps: ordered.value.map((step) => ({ kind: step.kind, params: step.params })) },
    }),
  onSuccess: (data) => {
    queryClient.setQueryData(["workflows", workflowId.value], data);
    code.refetch();
    show("Steps saved");
  },
  // steps.py writes its refusals for a learner, so the server's sentence is the one shown.
  onError: (err: unknown) => show(apiDetail(err, "The steps could not be saved."), "bad"),
});

const code = useQuery({
  queryKey: computed(() => ["workflows", workflowId.value, "code"]),
  queryFn: () => api.request<GeneratedCode>(`/workflows/${workflowId.value}/code`, { query: { fmt: "script" } }),
  enabled: computed(() => Number.isFinite(workflowId.value)),
  retry: false,
});

const activeRunId = ref<number | null>(null);
const pollTimer = ref<ReturnType<typeof setInterval> | null>(null);
const pollStartedAt = ref(0);
const pollNote = ref("");

const activeRun = computed(() => (runs.data.value?.items ?? []).find((run) => run.id === activeRunId.value) ?? null);
const latestRun = computed(() => activeRun.value ?? (runs.data.value?.items ?? [])[0] ?? null);

function stopPolling(note: string) {
  if (pollTimer.value) clearInterval(pollTimer.value);
  pollTimer.value = null;
  pollNote.value = note;
}

async function pollOnce() {
  if (activeRunId.value === null) return stopPolling("");
  if (Date.now() - pollStartedAt.value > POLL_LIMIT_MS) {
    return stopPolling("Still queued after five minutes. Reload the page to check again.");
  }
  try {
    const run = await api.request<RunResponse>(`/workflows/${workflowId.value}/runs/${activeRunId.value}`);
    queryClient.setQueryData(["workflows", workflowId.value, "runs"], (old: Page<RunResponse> | undefined) => {
      if (!old) return old;
      return { ...old, items: old.items.map((item) => (item.id === run.id ? run : item)) };
    });
    if (isSettled(run)) stopPolling("");
  } catch (err) {
    stopPolling(statusOf(err) === 404 ? "That run is gone." : "Lost contact with the run. Reload to check.");
  }
}

function startPolling(runId: number) {
  activeRunId.value = runId;
  pollStartedAt.value = Date.now();
  pollNote.value = "";
  if (pollTimer.value) clearInterval(pollTimer.value);
  pollTimer.value = setInterval(pollOnce, POLL_MS);
}

onBeforeUnmount(() => stopPolling(""));

const start = useMutation({
  mutationFn: async () => {
    if (dirty.value) await save.mutateAsync();
    return api.request<RunResponse>(`/workflows/${workflowId.value}/runs`, { method: "POST" });
  },
  onSuccess: async (run) => {
    await runs.refetch();
    startPolling(run.id);
  },
  onError: (err: unknown) => show(apiDetail(err, "The run could not be started."), "bad"),
});

const running = computed(() => start.isPending.value || (latestRun.value !== null && !isSettled(latestRun.value) && pollTimer.value !== null));

async function download(fmt: "script" | "notebook") {
  try {
    const body = await api.request<GeneratedCode>(`/workflows/${workflowId.value}/code`, { query: { fmt } });
    const url = URL.createObjectURL(new Blob([body.code], { type: "text/plain" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = body.filename;
    link.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    show(apiDetail(err, "The file could not be generated."), "bad");
  }
}

const compare = ref<number[]>([]);

function toggleCompare(runId: number) {
  compare.value = compare.value.includes(runId)
    ? compare.value.filter((id) => id !== runId)
    : [...compare.value, runId].slice(-2);
}

const comparedRuns = computed(() =>
  (runs.data.value?.items ?? []).filter((run) => compare.value.includes(run.id) && run.status === "succeeded"),
);

const comparedMetrics = computed(() => {
  const names = new Set<string>();
  for (const run of comparedRuns.value) for (const name of Object.keys(run.metrics ?? {})) names.add(name);
  return [...names];
});
</script>

<template>
  <div>
    <p v-if="workflow.isPending.value" class="text-[12.5px] text-ink-muted">Loading the workflow.</p>
    <p v-else-if="workflow.isError.value" class="text-[12.5px] text-ink-muted">
      {{ apiDetail(workflow.error.value, "That workflow could not be opened.") }}
    </p>

    <template v-else-if="workflow.data.value">
      <section>
        <Eyebrow>Forge · workflow canvas</Eyebrow>
        <div class="mt-3 flex flex-wrap items-baseline gap-x-4 gap-y-2">
          <h1 class="text-[clamp(1.5rem,2.2vw,1.9rem)] font-semibold tracking-[-0.035em]">
            {{ workflow.data.value.name }}
          </h1>
          <span :class="[MONO_LABEL, 'text-ink-muted']">{{ kindMeta?.label ?? workflow.data.value.kind }}</span>
          <NuxtLink :class="[FOCUS, 'mono ml-auto rounded text-[12px] text-ink-muted underline-offset-4 hover:underline']" to="/canvas">
            All workflows
          </NuxtLink>
        </div>
        <p class="mt-3 max-w-[64ch] text-[13px] leading-relaxed text-ink-muted">{{ kindMeta?.blurb }}</p>
        <p v-if="dataset.data.value" class="mono mt-2 text-[12px] text-ink-muted">
          {{ dataset.data.value.name }} · {{ dataset.data.value.row_count }} rows ·
          {{ dataset.data.value.columns.length }} columns
        </p>
      </section>

      <section class="mt-8 flex flex-wrap items-center gap-3 border-y border-line-subtle py-4">
        <Btn :busy="start.isPending.value" :disabled="running" @click="start.mutate()">
          {{ dirty ? "Save and run" : "Run workflow" }}
        </Btn>
        <Btn variant="secondary" :disabled="!dirty" :busy="save.isPending.value" @click="save.mutate()">
          Save steps
        </Btn>
        <span v-if="dirty" class="mono text-[12px] text-ink-muted">Unsaved changes</span>
        <span v-if="latestRun" class="ml-auto flex items-center gap-2">
          <StatusDot :tone="RUN_TONES[latestRun.status]" />
          <span class="mono text-[12px] text-ink-muted">
            run {{ latestRun.id }} · {{ latestRun.status }}
            <template v-if="latestRun.duration_ms"> · {{ formatDuration(latestRun.duration_ms) }}</template>
          </span>
        </span>
      </section>

      <p v-if="pollNote" class="mt-3 text-[12.5px] text-ink-muted">{{ pollNote }}</p>

      <div
        v-if="latestRun?.status === 'failed'"
        class="mt-6 rounded-md bg-bad-surface px-4 py-3 ring-1 ring-inset ring-line"
      >
        <p :class="[MONO_LABEL, 'text-bad']">Run failed</p>
        <p class="mt-1.5 max-w-[70ch] text-[12.5px] leading-relaxed text-ink">{{ latestRun.error }}</p>
        <p class="mt-1.5 text-[12px] leading-relaxed text-ink-muted">
          Nothing was saved from this run. Change the step the message names and run it again.
        </p>
      </div>

      <!-- The Week 7 bar: the steps and the script they generate, on screen together, each
           block labelled with the step it came from. Hovering either side lights up both. -->
      <section class="mt-10 grid gap-8 lg:grid-cols-2 lg:gap-10">
        <div>
          <h2 class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">The canvas</h2>
          <p class="mt-2 max-w-[58ch] text-[13px] leading-relaxed text-ink-muted">
            {{ ordered.length }} {{ ordered.length === 1 ? "step" : "steps" }}, numbered in the order
            they will run. A pipeline only works one way round, so the canvas sorts itself rather
            than trusting the order the steps were added in.
          </p>

          <ol class="mt-6 space-y-0">
            <StepCard
              v-for="(step, index) in ordered"
              :key="`${step.kind}-${index}`"
              :kind="step.kind"
              :params="step.params"
              :position="index + 1"
              :total="ordered.length"
              :label="catalogByKind[step.kind]?.label ?? step.kind"
              :summary="catalogByKind[step.kind]?.summary ?? ''"
              :workflow-kind="workflow.data.value.kind"
              :columns="columns"
              :removable="ordered.length > 1"
              :active="activeKind === step.kind"
              @update:params="updateStep(index, $event)"
              @remove="removeStep(index)"
              @focus="activeKind = step.kind"
            />
          </ol>

          <div v-if="available.length" class="mt-8 border-t border-line-subtle pt-5">
            <p :class="[MONO_LABEL, 'text-ink-faint']">Add a step</p>
            <div class="mt-3 flex flex-wrap gap-2">
              <button
                v-for="step in available"
                :key="step"
                type="button"
                :class="[FOCUS, 'mono rounded-md px-2.5 py-1.5 text-[12px] text-ink-muted ring-1 ring-inset ring-line transition-colors hover:bg-surface-hover hover:text-ink']"
                @click="addStep(step)"
              >
                + {{ catalogByKind[step]?.label ?? step }}
              </button>
            </div>
          </div>
        </div>

        <div>
          <div class="flex flex-wrap items-baseline justify-between gap-3">
            <h2 class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">The Python it becomes</h2>
            <span v-if="code.data.value" class="mono text-[12px] text-ink-muted">{{ code.data.value.filename }}</span>
          </div>
          <p class="mt-2 max-w-[58ch] text-[13px] leading-relaxed text-ink-muted">
            One block per step, in the same order and carrying the same numbers. Save the canvas to
            regenerate it, then download it and run it yourself.
          </p>

          <div class="mt-6 overflow-hidden rounded-lg bg-sunken ring-1 ring-inset ring-line">
            <CodeView
              v-if="code.data.value"
              :code="code.data.value.code"
              :active-kind="activeKind"
              @hover="activeKind = $event"
            />
            <p v-else-if="code.isError.value" class="px-4 py-6 text-[12.5px] leading-relaxed text-ink-muted">
              {{ apiDetail(code.error.value, "The script could not be generated from these steps yet.") }}
            </p>
            <p v-else class="px-4 py-6 text-[12.5px] text-ink-muted">Generating.</p>
          </div>

          <div class="mt-4 flex flex-wrap gap-2">
            <Btn size="sm" variant="secondary" :disabled="!code.data.value" @click="download('script')">
              Download .py
            </Btn>
            <Btn size="sm" variant="secondary" :disabled="!code.data.value" @click="download('notebook')">
              Download .ipynb
            </Btn>
          </div>
        </div>
      </section>

      <section v-if="latestRun?.status === 'succeeded'" class="mt-12 border-t border-line-subtle pt-8">
        <RunResults :run="latestRun" />
      </section>

      <section class="mt-12 border-t border-line-subtle pt-8">
        <div class="flex flex-wrap items-baseline justify-between gap-3">
          <h2 class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">Run history</h2>
          <span :class="[MONO_LABEL, 'text-ink-muted']">{{ runs.data.value?.total ?? 0 }} runs</span>
        </div>
        <p class="mt-2 max-w-[64ch] text-[12.5px] leading-relaxed text-ink-muted">
          Every run this workflow has had, newest first. Tick two finished runs to put their scores
          side by side.
        </p>

        <p v-if="!runs.data.value?.items?.length" class="mt-4 rounded-md bg-surface/40 px-5 py-8 text-[12.5px] text-ink-muted ring-1 ring-inset ring-line-subtle">
          No runs yet.
        </p>
        <!-- Status, id, time and duration are four unlabelled values in a row otherwise, and
             a run that carries an error message must not shift the columns of one that does
             not. Same shape as the dataset list on the overview. -->
        <table v-else class="mt-4 w-full border-collapse text-left">
          <caption class="sr-only">Runs of this workflow, newest first, with how each one ended and how long it took.</caption>
          <thead>
            <tr class="border-y border-line-subtle">
              <th scope="col" class="py-2 pr-3"><span class="sr-only">Compare</span></th>
              <th scope="col" :class="[MONO_LABEL, 'whitespace-nowrap py-2 pr-3 font-normal text-ink-faint']">Run</th>
              <th scope="col" :class="[MONO_LABEL, 'whitespace-nowrap px-3 py-2 font-normal text-ink-faint']">Outcome</th>
              <th scope="col" :class="[MONO_LABEL, 'hidden whitespace-nowrap px-3 py-2 font-normal text-ink-faint sm:table-cell']">Started</th>
              <th scope="col" :class="[MONO_LABEL, 'whitespace-nowrap px-3 py-2 text-right font-normal text-ink-faint']">Took</th>
              <th scope="col" :class="[MONO_LABEL, 'w-full py-2 pl-3 font-normal text-ink-faint']">Message</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="run in runs.data.value.items" :key="run.id" class="border-b border-line-subtle">
              <td class="py-3 pr-3">
                <input
                  :class="[FOCUS, 'h-4 w-4 rounded-sm accent-[color:var(--ink)]']"
                  type="checkbox"
                  :aria-label="`Compare run ${run.id}`"
                  :checked="compare.includes(run.id)"
                  :disabled="run.status !== 'succeeded'"
                  @change="toggleCompare(run.id)"
                >
              </td>
              <td class="whitespace-nowrap py-3 pr-3">
                <button
                  type="button"
                  :class="[FOCUS, 'mono rounded text-[12.5px] font-medium text-ink underline-offset-4 hover:underline']"
                  @click="activeRunId = run.id"
                >
                  run {{ run.id }}
                </button>
              </td>
              <td class="whitespace-nowrap px-3 py-3">
                <span class="flex items-center gap-2">
                  <StatusDot :tone="RUN_TONES[run.status]" />
                  <span class="mono text-[12px] text-ink-muted">{{ run.status }}</span>
                </span>
              </td>
              <td class="mono hidden whitespace-nowrap px-3 py-3 text-[12px] text-ink-muted sm:table-cell">
                {{ formatStamp(run.created_at) }}
              </td>
              <td class="mono whitespace-nowrap px-3 py-3 text-right text-[12px] tabular-nums text-ink-muted">
                {{ run.duration_ms ? formatDuration(run.duration_ms) : "" }}
              </td>
              <td class="max-w-0 py-3 pl-3">
                <span class="block truncate text-[12.5px] text-ink-muted">{{ run.error ?? "" }}</span>
              </td>
            </tr>
          </tbody>
        </table>

        <div v-if="comparedRuns.length === 2" class="mt-6 overflow-x-auto">
          <table class="w-full border-collapse text-left">
            <caption class="sr-only">Two runs compared</caption>
            <thead>
              <tr class="border-b border-line-subtle">
                <th scope="col" :class="[MONO_LABEL, 'px-3 py-2 font-medium text-ink-muted']">metric</th>
                <th v-for="run in comparedRuns" :key="run.id" scope="col" :class="[MONO_LABEL, 'px-3 py-2 font-medium text-ink-muted']">
                  run {{ run.id }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="name in comparedMetrics" :key="name" class="border-b border-line-subtle last:border-0">
                <td class="mono px-3 py-2 text-[12px] text-ink-muted">{{ name }}</td>
                <td v-for="run in comparedRuns" :key="run.id" class="mono px-3 py-2 text-[12px] text-ink">
                  {{ run.metrics?.[name] ?? "—" }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>

    <Toast v-if="toast" :message="toast.message" :tone="toast.tone" @dismiss="clear" />
  </div>
</template>
