<script setup lang="ts">
// How far a capability reaches: 0 their own work, 1 repos they lead, 2 their department,
// 3 the whole workspace. Monochrome on purpose — a darker step means further, and none of
// this is a status, so none of it is coloured. aria-hidden: the words are beside it.
const RAMP = ["bg-line-subtle", "bg-line", "bg-line-strong", "bg-ink"];

defineProps<{ scope: 0 | 1 | 2 | 3 }>();
</script>

<template>
  <span class="inline-flex items-center gap-[3px]" aria-hidden="true">
    <span
      v-for="i in [0, 1, 2, 3]"
      :key="i"
      :class="['h-1.5 w-1.5 rounded-[1px]', i <= scope ? RAMP[scope] : 'ring-1 ring-inset ring-line-subtle']"
    />
  </span>
</template>
