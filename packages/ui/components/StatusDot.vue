<script setup lang="ts">
import { computed } from "vue";
import type { Tone } from "../types/ui";
import { DOT_BG, DOT_TEXT } from "../utils/ui";

/* `quiet` colours the dot and leaves the label `ink-muted`. Measured on the page
   background, `--ok` is 8.78:1 and `--warn` 10.15:1 against `--ink-muted`'s 7.64:1 —
   a coloured status word in every row is brighter than the data it annotates. Quiet is
   the default choice inside a table; full colour is for single, non-repeating places. */
const props = withDefaults(defineProps<{ tone: Tone; quiet?: boolean }>(), { quiet: false });

const label = computed(() => (props.quiet ? "text-ink-muted" : DOT_TEXT[props.tone]));
</script>

<template>
  <span :class="['inline-flex items-center gap-1.5 text-[12px]', label]">
    <span :class="['h-1.5 w-1.5 shrink-0 rounded-full', DOT_BG[tone]]" />
    <slot />
  </span>
</template>
