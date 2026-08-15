<script setup lang="ts">
// Ticks running down a vertical rule, so the rule reads as measured. Absolutely
// positioned: the caller supplies the `relative` ancestor.
const stops = [0.08, 0.2, 0.32, 0.44, 0.56, 0.68, 0.8, 0.92];
</script>

<template>
  <div class="pointer-events-none absolute inset-y-0 left-0 hidden lg:block" aria-hidden="true">
    <span
      v-for="(stop, i) in stops"
      :key="stop"
      :class="['absolute h-px', i % 2 === 0 ? 'w-2.5 bg-line-strong' : 'w-1.5 bg-line-subtle']"
      :style="{ top: `${stop * 100}%` }"
    />
  </div>
</template>
