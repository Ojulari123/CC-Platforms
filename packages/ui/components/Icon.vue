<script setup lang="ts">
import { computed, useAttrs } from "vue";
import type { IconName } from "../types/ui";
import { ICON_PATHS } from "../utils/ui";

// inheritAttrs off so a caller's `class` replaces the default size rather than
// stacking two conflicting `h-*` utilities on the same element.
defineOptions({ inheritAttrs: false });

const props = defineProps<{ name: IconName }>();

const attrs = useAttrs();
const size = computed(() => attrs.class ?? "h-4 w-4");
const paths = computed(() => ICON_PATHS[props.name] ?? []);
</script>

<template>
  <svg
    :class="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.75"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path v-for="d in paths" :key="d" :d="d" />
  </svg>
</template>
