<script setup lang="ts">
import { computed } from "vue";
import Icon from "./Icon.vue";
import type { BtnSize, BtnVariant } from "../types/ui";
import { FOCUS, TAP } from "../utils/ui";

const SIZE: Record<BtnSize, string> = {
  sm: "px-3 py-1.5 text-[13px]",
  md: "px-4 py-2.5 text-[13.5px]",
  lg: "px-5 py-3 text-[14px]",
};

/* Press feedback on every variant, not just primary: inconsistent feedback reads as
   broken rather than as restraint. `secondary` uses `ring-line-strong` because that ring
   is the button's only boundary and `line` is 1.64:1 against the page. */
const VARIANT: Record<BtnVariant, string> = {
  primary: "bg-ink font-medium text-app hover:brightness-90 active:scale-[0.98] disabled:opacity-60",
  secondary: "font-medium text-ink ring-1 ring-inset ring-line-strong hover:bg-surface-hover hover:ring-ink-faint active:scale-[0.98] disabled:opacity-60",
  ghost: "font-medium text-ink-muted hover:text-ink active:scale-[0.98] disabled:opacity-60",
  destructive: "font-medium text-bad ring-1 ring-inset ring-bad/65 hover:bg-bad-surface hover:ring-bad active:scale-[0.98] disabled:opacity-60",
};

const props = withDefaults(
  defineProps<{
    size?: BtnSize;
    variant?: BtnVariant;
    type?: "button" | "submit" | "reset";
    disabled?: boolean;
    // Work in flight. Applies the sweeping hairline and disables the control.
    busy?: boolean;
    arrow?: boolean;
    full?: boolean;
  }>(),
  { size: "md", variant: "primary", type: "button", disabled: false, busy: false, arrow: false, full: false },
);

const emit = defineEmits<{ click: [event: MouseEvent] }>();

const blocked = computed(() => props.disabled || props.busy);

function onClick(event: MouseEvent) {
  if (blocked.value) return;
  emit("click", event);
}
</script>

<template>
  <button
    :type="type"
    :disabled="blocked"
    :aria-busy="busy || undefined"
    :class="[
      FOCUS,
      TAP,
      'group/btn relative inline-flex items-center justify-center gap-2 rounded-md transition-[transform,filter,color,background-color,box-shadow] duration-100 ease-out',
      SIZE[size],
      VARIANT[variant],
      full && 'w-full',
      busy && 'btn-busy',
    ]"
    @click="onClick"
  >
    <slot />
    <!-- Stays mounted while busy so the button does not resize mid-wait. -->
    <Icon
      v-if="arrow"
      name="arrow"
      :class="['h-4 w-4 transition-transform group-hover/btn:translate-x-0.5', busy && 'opacity-0']"
    />
  </button>
</template>
