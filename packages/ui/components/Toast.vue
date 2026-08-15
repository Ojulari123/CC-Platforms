<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import Icon from "./Icon.vue";
import type { Tone } from "../types/ui";
import { DOT_BG, FOCUS, TAP } from "../utils/ui";
import { announce } from "../composables/useAnnounce";

/* Transitions, not a keyframe. The node's identity is stable, so a second toast fired
   over the first has to retarget from wherever it currently is — a keyframe would
   replay nothing, which is the bug this shape exists to prevent.
   Announced politely through the shared live region: a toast is a confirmation, not an
   interruption, and the node itself carries no role. */
const props = withDefaults(
  defineProps<{ message: string; tone?: Tone; duration?: number }>(),
  { tone: "muted", duration: 3600 },
);

const emit = defineEmits<{ dismiss: [] }>();

const shown = ref(false);
const leaving = ref(false);
const exitTimer = ref<ReturnType<typeof setTimeout> | null>(null);
const autoTimer = ref<ReturnType<typeof setTimeout> | null>(null);

const settled = computed(() => shown.value && !leaving.value);

function beginExit() {
  if (exitTimer.value !== null) return;
  leaving.value = true;
  exitTimer.value = setTimeout(() => emit("dismiss"), 200);
}

function restart() {
  if (exitTimer.value !== null) {
    clearTimeout(exitTimer.value);
    exitTimer.value = null;
  }
  if (autoTimer.value !== null) clearTimeout(autoTimer.value);
  leaving.value = false;
  announce(props.message);
  autoTimer.value = setTimeout(beginExit, props.duration);
}

onMounted(() => {
  requestAnimationFrame(() => {
    shown.value = true;
  });
  restart();
});

watch(() => props.message, restart);

onBeforeUnmount(() => {
  if (exitTimer.value !== null) clearTimeout(exitTimer.value);
  if (autoTimer.value !== null) clearTimeout(autoTimer.value);
});
</script>

<template>
  <div class="pointer-events-none fixed inset-x-0 bottom-6 z-50 flex justify-center px-4">
    <div
      data-toast
      :data-settled="settled ? 'true' : 'false'"
      :class="[
        'pointer-events-auto flex max-w-[520px] items-center gap-3 rounded-md bg-surface px-4 py-2.5 shadow-2xl ring-1 ring-line transition-[opacity,transform] ease-[cubic-bezier(0.23,1,0.32,1)]',
        leaving ? 'duration-200' : 'duration-[250ms]',
        settled ? 'translate-y-0 opacity-100' : 'translate-y-2 opacity-0',
      ]"
    >
      <span :class="['h-1.5 w-1.5 shrink-0 rounded-full', DOT_BG[tone]]" aria-hidden="true" />
      <span class="text-[12.5px] text-ink">{{ message }}</span>
      <button
        type="button"
        aria-label="Dismiss"
        :class="[FOCUS, TAP, '-mr-1.5 grid place-items-center rounded p-1 text-ink-faint transition-colors hover:text-ink']"
        @click="beginExit"
      >
        <Icon name="x" class="h-3.5 w-3.5" />
      </button>
    </div>
  </div>
</template>
