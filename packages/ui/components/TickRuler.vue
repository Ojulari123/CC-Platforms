<script setup lang="ts">
import { computed } from "vue";

// The graticule: a ruler of hairline ticks. Every fifth is longer, every tenth longer
// still, so the eye reads it as a scale rather than as texture.
const props = withDefaults(defineProps<{ count?: number }>(), { count: 140 });

const ticks = computed(() =>
  Array.from({ length: props.count }, (_, i) => ({
    key: i,
    height: i % 10 === 0 ? 13 : i % 5 === 0 ? 8 : 4,
    tone: i % 10 === 0 ? "bg-line-strong" : "bg-line-subtle",
  })),
);
</script>

<template>
  <div class="flex min-w-0 flex-1 items-start gap-[10px] overflow-hidden" aria-hidden="true">
    <span
      v-for="tick in ticks"
      :key="tick.key"
      :class="['w-px shrink-0', tick.tone]"
      :style="{ height: `${tick.height}px` }"
    />
  </div>
</template>
