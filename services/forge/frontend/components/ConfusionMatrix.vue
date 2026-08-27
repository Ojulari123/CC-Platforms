<script setup lang="ts">
import { computed } from "vue";
import { MONO_LABEL } from "@crescent/ui/utils/ui";

/* Four numbers in a row tell you nothing. A grid tells you which class the model keeps
   confusing for which, which is the thing worth learning from a classification run.
   Rows are what the row really was, columns are what the model said. */
const props = defineProps<{ labels: string[]; matrix: number[][] }>();

const total = computed(() => props.matrix.flat().reduce((sum, n) => sum + n, 0));
const peak = computed(() => Math.max(1, ...props.matrix.flat()));

// Shading is an opacity on an ink fill rather than a class per bucket: Tailwind only
// generates the classes it can see in the source, and a computed class name is invisible.
function shade(value: number): number {
  return value === 0 ? 0 : 0.08 + 0.42 * (value / peak.value);
}

function share(value: number): string {
  return total.value ? `${Math.round((100 * value) / total.value)}%` : "0%";
}
</script>

<template>
  <figure>
    <figcaption class="text-[12.5px] leading-relaxed text-ink-muted">
      Every held-back row, counted by what it was against what the model said. The diagonal is
      the rows it got right.
    </figcaption>
    <div class="relative mt-3 overflow-x-auto">
      <table class="border-collapse text-left">
        <caption class="sr-only">Confusion matrix</caption>
        <thead>
          <tr>
            <th scope="col" :class="[MONO_LABEL, 'px-3 py-2 text-ink-faint']">actual \ predicted</th>
            <th
              v-for="label in labels"
              :key="label"
              scope="col"
              :class="[MONO_LABEL, 'px-3 py-2 font-medium text-ink-muted']"
            >
              {{ label }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, r) in matrix" :key="labels[r] ?? r">
            <th scope="row" :class="[MONO_LABEL, 'whitespace-nowrap px-3 py-2 font-medium text-ink-muted']">
              {{ labels[r] }}
            </th>
            <td v-for="(value, c) in row" :key="c" class="p-1">
              <div class="relative min-w-[4.5rem] rounded-sm px-3 py-2.5 ring-1 ring-inset ring-line-subtle">
                <div
                  class="pointer-events-none absolute inset-0 rounded-sm bg-ink"
                  :style="{ opacity: shade(value) }"
                  aria-hidden="true"
                />
                <span class="relative mono text-[13px] font-medium text-ink">{{ value }}</span>
                <span class="relative mono ml-1.5 text-[12px] text-ink-muted">{{ share(value) }}</span>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </figure>
</template>
