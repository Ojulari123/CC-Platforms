<script setup lang="ts">
import { computed } from "vue";
import { initials } from "../utils/ui";

// aria-hidden: the name is always beside it, so reading the initials twice adds nothing.
const props = withDefaults(defineProps<{ name: string; size?: "sm" | "md" }>(), { size: "md" });

const box = computed(() => (props.size === "sm" ? "h-5 w-5" : "h-7 w-7"));
</script>

<template>
  <span
    :class="[
      'mono grid shrink-0 place-items-center rounded-full bg-surface text-[11px] uppercase tracking-wide text-ink-muted ring-1 ring-inset ring-line-subtle',
      box,
    ]"
    aria-hidden="true"
  >
    {{ initials(name) }}
  </span>
</template>
