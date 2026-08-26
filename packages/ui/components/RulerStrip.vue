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
      <!-- A min-width, not a width. At 11px a 20-character readout fitted 150px exactly.
           At 12px it wraps, and the strip is a fixed h-9. The ruler beside it is
           `flex-1 overflow-hidden`, so giving the readout its natural width costs ticks
           rather than a second line. -->
      <span :class="['min-w-[150px] shrink-0 whitespace-nowrap text-right text-ink-muted', MONO_LABEL]">{{ readout }}</span>
    </div>
  </div>
</template>
