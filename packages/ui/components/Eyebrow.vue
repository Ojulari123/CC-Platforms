<script setup lang="ts">
import { MONO_LABEL } from "../utils/ui";

// The one place `ink-faint` is unambiguously correct: a label, never a value.
</script>

<template>
  <p :class="[MONO_LABEL, 'text-ink-faint']">
    <slot />
  </p>
</template>
