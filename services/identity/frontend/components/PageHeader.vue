<script setup lang="ts">
defineProps<{
  title: string;
  description?: string;
  back?: { to: string; label: string };
}>();
</script>

<template>
  <header class="mb-8">
    <NuxtLink
      v-if="back"
      :to="back.to"
      class="mb-3 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-900"
    >
      <span aria-hidden="true">&larr;</span> {{ back.label }}
    </NuxtLink>
    <div class="flex flex-wrap items-start justify-between gap-4">
      <div class="min-w-0">
        <h1 class="text-2xl font-semibold tracking-tight">{{ title }}</h1>
        <p v-if="description" class="mt-1 max-w-2xl text-sm text-slate-500">{{ description }}</p>
      </div>
      <div class="flex shrink-0 items-center gap-2">
        <slot name="actions" />
      </div>
    </div>
  </header>
</template>
