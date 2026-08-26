<script setup lang="ts">
defineProps<{ title: string; hint?: string }>();
</script>

<template>
  <div class="rounded-xl border border-dashed border-slate-300 bg-white px-6 py-12 text-center">
    <p class="text-sm font-medium text-slate-900">{{ title }}</p>
    <p v-if="hint" class="mx-auto mt-1 max-w-md text-sm text-slate-500">{{ hint }}</p>
    <div class="mt-4 flex justify-center">
      <slot />
    </div>
  </div>
</template>
