<script setup lang="ts">
import { computed } from "vue";
import Icon from "./Icon.vue";

// The logo: a square frame with the meridian glyph — a circle cut by its own bisector
// — inside it. The square is the frame and the frame is a rule, not a fill.
const props = withDefaults(defineProps<{ size?: "sm" | "md" | "lg" }>(), { size: "md" });

const box = computed(() =>
  props.size === "sm" ? "h-6 w-6 rounded" : props.size === "lg" ? "h-9 w-9 rounded-md" : "h-7 w-7 rounded-md",
);
const glyph = computed(() =>
  props.size === "sm" ? "h-3 w-3" : props.size === "lg" ? "h-[18px] w-[18px]" : "h-3.5 w-3.5",
);
</script>

<template>
  <span :class="['grid place-items-center text-ink ring-1 ring-inset ring-line-strong', box]">
    <Icon name="meridian" :class="glyph" />
  </span>
</template>
