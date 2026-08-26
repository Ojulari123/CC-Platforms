<script setup lang="ts">
import { computed } from "vue";
import Icon from "./Icon.vue";
import type { BtnSize, BtnVariant } from "../types/ui";
import { DISABLED, FOCUS, TAP } from "../utils/ui";

const SIZE: Record<BtnSize, string> = {
  sm: "px-3 py-1.5 text-[13px]",
  md: "px-4 py-2.5 text-[13.5px]",
  lg: "px-5 py-3 text-[14px]",
};

/* Press feedback on every variant, not just primary: inconsistent feedback reads as
   broken rather than as restraint. `secondary` uses `ring-line-strong` (5.80:1 on the
   page) rather than `ring-line` (4.57:1) because that ring is the button's only
   boundary and it should sit clear of the 3:1 floor, not on it.

   Disabled hands the boundary back to `ring-line` and dims only the label — see
   `DISABLED` in utils/ui.ts for why the old `disabled:opacity-60` was the wrong tool.
   The disabled fill is `--surface`, not `--surface-active`: the latter is an interaction
   fill, which is the wrong thing to say about a control that cannot be interacted with,
   and `--ink-disabled` only measures 3.57:1 on it against 4.54:1 on `--surface`. */
const VARIANT: Record<BtnVariant, string> = {
  primary: "bg-ink font-medium text-app enabled:hover:brightness-90 active:scale-[0.98] disabled:bg-surface disabled:ring-1 disabled:ring-inset disabled:ring-line",
  secondary: "font-medium text-ink ring-1 ring-inset ring-line-strong enabled:hover:bg-surface-hover enabled:hover:ring-ink-faint active:scale-[0.98] disabled:ring-line",
  ghost: "font-medium text-ink-muted enabled:hover:text-ink active:scale-[0.98]",
  destructive: "font-medium text-bad ring-1 ring-inset ring-bad/65 enabled:hover:bg-bad-surface enabled:hover:ring-bad active:scale-[0.98] disabled:ring-line",
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
      DISABLED,
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
