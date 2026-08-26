<script setup lang="ts">
// The name of the dependency in the API that actually refuses the request. A label, not
// a value somebody acts on, so ink-faint is legitimate here.
defineProps<{ name: string }>();
</script>

<template>
  <span class="mono shrink-0 rounded bg-sunken px-1.5 py-0.5 text-[12px] text-ink-faint">{{ name }}</span>
</template>
