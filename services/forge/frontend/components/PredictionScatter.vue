<script setup lang="ts">
import { computed } from "vue";
import { MONO_LABEL } from "@crescent/ui/utils/ui";

/* Actual against predicted for the sample of held-back rows the run kept. A number for
   R² says how well the model did; this says where it went wrong. Points on the diagonal
   are exact, points above it are over-predictions. Plain SVG, no chart library. */
const props = defineProps<{ points: { actual: number; predicted: number }[]; target: string }>();

const SIZE = 240;
const PAD = 28;

const bounds = computed(() => {
  const values = props.points.flatMap((p) => [p.actual, p.predicted]);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo || 1;
  return { lo: lo - span * 0.05, hi: hi + span * 0.05 };
});

function x(value: number): number {
  const { lo, hi } = bounds.value;
  return PAD + ((value - lo) / (hi - lo)) * (SIZE - PAD * 2);
}

function y(value: number): number {
  return SIZE - PAD - ((value - bounds.value.lo) / (bounds.value.hi - bounds.value.lo)) * (SIZE - PAD * 2);
}

const ticks = computed(() => [bounds.value.lo, (bounds.value.lo + bounds.value.hi) / 2, bounds.value.hi]);

function tick(value: number): string {
  return Math.abs(value) >= 1000 ? value.toFixed(0) : value.toFixed(2);
}
</script>

<template>
  <figure>
    <figcaption class="text-[12.5px] leading-relaxed text-ink-muted">
      {{ points.length }} held-back rows: what {{ target }} really was, against what the model said.
      A point on the line is an exact prediction.
    </figcaption>
    <svg
      :viewBox="`0 0 ${SIZE} ${SIZE}`"
      class="mt-3 h-auto w-full max-w-[320px] text-ink-faint"
      role="img"
      :aria-label="`Predicted against actual ${target} for ${points.length} held-back rows`"
    >
      <line :x1="PAD" :y1="SIZE - PAD" :x2="SIZE - PAD" :y2="SIZE - PAD" stroke="currentColor" stroke-width="1" />
      <line :x1="PAD" :y1="PAD" :x2="PAD" :y2="SIZE - PAD" stroke="currentColor" stroke-width="1" />
      <line
        :x1="x(bounds.lo)"
        :y1="y(bounds.lo)"
        :x2="x(bounds.hi)"
        :y2="y(bounds.hi)"
        stroke="currentColor"
        stroke-width="1"
        stroke-dasharray="3 3"
      />
      <circle
        v-for="(point, i) in points"
        :key="i"
        :cx="x(point.actual)"
        :cy="y(point.predicted)"
        r="3.5"
        class="text-accent-ink"
        fill="currentColor"
        fill-opacity="0.75"
      />
      <text
        v-for="value in ticks"
        :key="`x${value}`"
        :x="x(value)"
        :y="SIZE - PAD + 14"
        text-anchor="middle"
        class="mono"
        font-size="12"
        fill="currentColor"
      >
        {{ tick(value) }}
      </text>
    </svg>
    <p :class="[MONO_LABEL, 'mt-1 text-ink-faint']">x actual · y predicted</p>
  </figure>
</template>
