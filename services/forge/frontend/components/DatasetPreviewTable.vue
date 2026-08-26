<script setup lang="ts">
import { computed } from "vue";
import { PREVIEW_ROW_CAP, detectTextColumn } from "~/utils/upload";

/* The header row is the dataset's own column names. It is never A/B/C/D — a spreadsheet
   ruler tells you where a cell is, and nobody uploading a CSV needs to be told that. */
const props = withDefaults(
  defineProps<{
    columns: string[];
    rows: string[][];
    /** Total data rows in the dataset, not just the ones on screen. */
    rowCount: number;
    /** Total columns in the dataset. Defaults to the number shown. */
    totalColumns?: number;
    label: string;
    cap?: number;
  }>(),
  { cap: PREVIEW_ROW_CAP, totalColumns: undefined },
);

const shown = computed(() => props.rows.slice(0, props.cap));
const textCol = computed(() => detectTextColumn(props.columns, shown.value));
const width = computed(() => props.totalColumns ?? props.columns.length);
</script>

<template>
  <div>
    <!-- `relative`: the sr-only caption is position:absolute and without a positioned
         ancestor it escapes to the initial containing block, dragging a scrollbar with it. -->
    <div class="relative overflow-x-auto">
      <table class="w-full min-w-[560px] border-collapse text-left">
        <caption class="sr-only">First {{ shown.length }} rows of {{ label }}</caption>
        <thead>
          <tr class="border-b border-line-subtle bg-sunken/60">
            <th scope="col" class="mono w-10 px-3 py-2 text-[12px] font-normal text-ink-faint">#</th>
            <th
              v-for="(col, i) in columns"
              :key="col"
              scope="col"
              class="mono whitespace-nowrap px-3 py-2 text-[12px] font-medium text-ink-muted"
            >
              {{ col }}
              <span v-if="i === textCol" class="mono ml-1.5 text-[12px] font-normal lowercase text-ink-faint">
                text
              </span>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(row, r) in shown"
            :key="r"
            class="border-b border-line-subtle/60 transition-colors last:border-0 hover:bg-surface-hover/50"
          >
            <td class="mono px-3 py-[7px] text-[12px] text-ink-faint">{{ r + 1 }}</td>
            <!-- The values are the feature. They used to sit dimmer and smaller than
                 their own column headers. -->
            <td
              v-for="(cell, c) in row"
              :key="c"
              class="mono whitespace-nowrap px-3 py-[7px] text-[12px] text-ink"
            >
              <span v-if="c === textCol" class="rounded bg-surface-active px-1.5 py-0.5 text-[12px] text-ink">
                {{ cell }}
              </span>
              <template v-else>{{ cell }}</template>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div
      class="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line-subtle bg-sunken/40 px-3 py-2 sm:px-4"
    >
      <p class="mono text-[12px] text-ink-muted">
        first {{ shown.length }} of {{ rowCount.toLocaleString() }} rows · {{ columns.length }} of
        {{ width }} columns shown
      </p>
      <p class="mono ml-auto text-[12px] text-ink-faint">header row → column names</p>
    </div>
  </div>
</template>
