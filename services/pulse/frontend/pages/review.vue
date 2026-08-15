<script setup lang="ts">
// The review queue became the second tab of /reports. This route stays so links and
// bookmarks that already point at it keep working.
definePageMeta({
  middleware: [
    () => navigateTo({ path: "/reports", query: { scope: "queue" } }, { replace: true }),
  ],
});
</script>

<template>
  <p class="p-8 text-[12.5px] text-ink-muted">Taking you to the review queue…</p>
</template>
