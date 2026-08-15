<script setup lang="ts">
import TickRuler from "./TickRuler.vue";
import { CONTENT, MONO_LABEL, ORIGIN } from "../utils/ui";

// The strip under the top bar on every screen. `readout` is the one part a screen sets:
// `11 reports`, `next run 9h 55m`, `user_id 1042 · 2 live`. It is a value slot, not a
// label — hence ink-muted below, where the ticks and the chrome around it stay faint.
withDefaults(defineProps<{ readout?: string }>(), { readout: ORIGIN });
</script>

<template>
  <div class="border-b border-line-subtle">
    <div :class="['flex h-9 items-center gap-5', CONTENT]">
      <TickRuler />
      <span :class="['w-[150px] shrink-0 text-right text-ink-muted', MONO_LABEL]">{{ readout }}</span>
    </div>
  </div>
</template>
