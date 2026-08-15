<script setup lang="ts">
const props = defineProps<{ role: string; title?: boolean }>();
</script>

<template>
  <span
    class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset"
    :class="roleClass(props.role)"
    :title="props.title === false ? undefined : roleBlurb(props.role)"
  >
    {{ props.role }}
  </span>
</template>
