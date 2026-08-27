<script setup lang="ts">
import { computed } from "vue";
import { MONO_LABEL } from "@crescent/ui/utils/ui";
import type { RunResponse } from "~/types/api";
import { METRIC_LABELS, METRIC_MEANS, barFraction, formatDuration, formatMetric, humanise } from "~/utils/workflows";

/* What the run actually produced. Numbers first, then the shape of the mistakes, then the
   rows themselves, because a score you cannot see the working of teaches nothing. */
const props = defineProps<{ run: RunResponse }>();

const metrics = computed(() => Object.entries(props.run.metrics ?? {}).filter(([, v]) => typeof v === "number") as [string, number][]);
const result = computed(() => props.run.result ?? {});
const matrix = computed(() => result.value.confusion_matrix ?? null);
const labels = computed(() => result.value.class_labels ?? []);
const sample = computed(() => result.value.predictions_sample ?? []);

// A scatter needs numbers. A classification sample is class names, and those get the grid.
const numericPoints = computed(() =>
  sample.value
    .map((row) => ({ actual: Number(row.actual), predicted: Number(row.predicted) }))
    .filter((p) => Number.isFinite(p.actual) && Number.isFinite(p.predicted)),
);
const showScatter = computed(() => !matrix.value && numericPoints.value.length > 1);
</script>

<template>
  <div>
    <div class="flex flex-wrap items-baseline gap-x-4 gap-y-1">
      <h3 class="text-[16px] font-semibold leading-tight tracking-[-0.02em] text-ink">Results</h3>
      <p :class="[MONO_LABEL, 'text-ink-muted']">
        run {{ run.id }} · {{ formatDuration(run.duration_ms) }}
      </p>
    </div>

    <dl v-if="metrics.length" class="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <div v-for="[name, value] in metrics" :key="name" class="rounded-md bg-surface/40 px-4 py-3 ring-1 ring-inset ring-line-subtle">
        <dt :class="[MONO_LABEL, 'text-ink-muted']">{{ METRIC_LABELS[name] ?? humanise(name) }}</dt>
        <dd class="mono mt-1 text-[20px] font-semibold tracking-[-0.02em] text-ink">
          {{ formatMetric(name, value) }}
        </dd>
        <div
          v-if="barFraction(name, value) !== null"
          class="mt-2 h-1 rounded-full bg-line-subtle"
          aria-hidden="true"
        >
          <div class="h-1 rounded-full bg-ink" :style="{ width: `${(barFraction(name, value) ?? 0) * 100}%` }" />
        </div>
        <p class="mt-2 text-[12px] leading-relaxed text-ink-muted">{{ METRIC_MEANS[name] ?? "" }}</p>
      </div>
    </dl>

    <div v-if="result.reply" class="mt-6">
      <h4 :class="[MONO_LABEL, 'text-ink-muted']">What came back</h4>
      <!-- Model output as a text node. Never v-html. -->
      <pre class="mono mt-2 max-h-[26rem] overflow-auto whitespace-pre-wrap rounded-md bg-sunken px-4 py-3 text-[12.5px] leading-relaxed text-ink ring-1 ring-inset ring-line-subtle">{{ result.reply }}</pre>
      <p class="mono mt-2 text-[12px] text-ink-muted">
        model {{ result.model }} · {{ result.grounded ? "answered from your text only" : "answered from the prompt alone" }}
      </p>
    </div>

    <div v-if="matrix" class="mt-6">
      <ConfusionMatrix :labels="labels" :matrix="matrix" />
    </div>

    <div v-if="showScatter" class="mt-6">
      <PredictionScatter :points="numericPoints" :target="result.target ?? 'the target'" />
    </div>

    <div v-if="sample.length" class="mt-6">
      <h4 :class="[MONO_LABEL, 'text-ink-muted']">First {{ sample.length }} held-back rows</h4>
      <div class="relative mt-2 max-h-[18rem] overflow-auto rounded-md ring-1 ring-inset ring-line-subtle">
        <table class="w-full border-collapse text-left">
          <caption class="sr-only">Actual against predicted for the first held-back rows</caption>
          <thead>
            <tr class="border-b border-line-subtle bg-sunken/60">
              <th scope="col" :class="[MONO_LABEL, 'px-3 py-2 font-medium text-ink-muted']">actual</th>
              <th scope="col" :class="[MONO_LABEL, 'px-3 py-2 font-medium text-ink-muted']">predicted</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, i) in sample" :key="i" class="border-b border-line-subtle last:border-0">
              <td class="mono px-3 py-[7px] text-[12px] text-ink">{{ row.actual }}</td>
              <td class="mono px-3 py-[7px] text-[12px] text-ink">{{ row.predicted }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <dl v-if="result.algorithm || result.rows_used" class="mt-6 grid gap-x-6 gap-y-2 sm:grid-cols-2">
      <div v-if="result.algorithm" class="flex gap-2">
        <dt :class="[MONO_LABEL, 'text-ink-muted']">algorithm</dt>
        <dd class="mono text-[12px] text-ink">{{ result.algorithm }}</dd>
      </div>
      <div v-if="result.target" class="flex gap-2">
        <dt :class="[MONO_LABEL, 'text-ink-muted']">target</dt>
        <dd class="mono text-[12px] text-ink">{{ result.target }}</dd>
      </div>
      <div v-if="result.rows_used" class="flex gap-2">
        <dt :class="[MONO_LABEL, 'text-ink-muted']">rows</dt>
        <dd class="mono text-[12px] text-ink">
          {{ result.rows_used }} used · {{ result.train_rows }} train · {{ result.test_rows }} test
        </dd>
      </div>
      <div v-if="result.features?.length" class="flex gap-2">
        <dt :class="[MONO_LABEL, 'shrink-0 text-ink-muted']">features</dt>
        <dd class="mono text-[12px] text-ink">{{ result.features.join(", ") }}</dd>
      </div>
    </dl>
  </div>
</template>
