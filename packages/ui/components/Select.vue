<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, useId, watch } from "vue";
import Icon from "./Icon.vue";
import type { SelectOption } from "../types/ui";
import { DISABLED, FOCUS, TAP } from "../utils/ui";

/* A listbox, not a native <select>: the OS control brings its own chevron and its own
   font metrics, and was the only element on the site that looked borrowed. Focus stays
   on the trigger and the active option is announced through aria-activedescendant,
   which is what a combobox is supposed to do.

   The listbox is teleported to <body> and positioned `fixed` from the trigger's own
   viewport rect. As an absolute child it inherited whatever containing block happened to
   be above it — a transformed ancestor, a table's `overflow-x-auto` scroller, a collapsed
   row panel — and landed off-screen or clipped, and every screen that used it had to
   grow padding to compensate. Fixed coordinates read off the trigger have no ancestors to
   get wrong, so it also works inside a Modal, which teleports to <body> itself. */
const props = withDefaults(
  defineProps<{
    modelValue: string;
    options: SelectOption[];
    /** Accessible name for the control. */
    label: string;
    placeholder?: string;
    disabled?: boolean;
  }>(),
  { placeholder: "Select", disabled: false },
);

const emit = defineEmits<{ "update:modelValue": [value: string] }>();

const uid = `sel-${useId()}`;
const open = ref(false);
const active = ref(-1);
const box = ref<HTMLElement | null>(null);
const list = ref<HTMLElement | null>(null);
const trigger = ref<HTMLButtonElement | null>(null);

const selected = computed(() => props.options.findIndex((o) => o.value === props.modelValue));
const current = computed(() => (selected.value >= 0 ? props.options[selected.value] : undefined));

/* Popup geometry, in viewport coordinates. `bottom` rather than `top` when it flips up,
   so the popup does not need its own height measured to sit against the trigger. */
const MAX_HEIGHT = 264;
const GAP = 4;
const EDGE = 8;
const MIN_WIDTH = 160;
const place = ref({ left: 0, width: MIN_WIDTH, top: 0, bottom: 0, maxHeight: MAX_HEIGHT, up: false });

const popupStyle = computed(() => ({
  left: `${place.value.left}px`,
  width: `${place.value.width}px`,
  maxHeight: `${place.value.maxHeight}px`,
  ...(place.value.up ? { bottom: `${place.value.bottom}px` } : { top: `${place.value.top}px` }),
}));

function measure(height?: number) {
  const anchor = trigger.value;
  if (!anchor) return;
  const rect = anchor.getBoundingClientRect();
  const vw = document.documentElement.clientWidth;
  const vh = document.documentElement.clientHeight;
  // Before the first render the natural height is unknown, so it is estimated from the
  // option count and corrected on the next tick from the real scrollHeight. A zero
  // reading means unmeasured, not empty, so it falls back to the estimate.
  const wanted = Math.min(MAX_HEIGHT, height && height > 0 ? height : props.options.length * 36 + 8);
  const below = vh - rect.bottom - GAP - EDGE;
  const above = rect.top - GAP - EDGE;
  const up = below < wanted && above > below;
  const width = Math.max(rect.width, MIN_WIDTH);

  place.value = {
    left: Math.max(EDGE, Math.min(rect.left, vw - width - EDGE)),
    width,
    top: rect.bottom + GAP,
    bottom: vh - rect.top + GAP,
    maxHeight: Math.max(96, Math.min(MAX_HEIGHT, up ? above : below)),
    up,
  };
}

function away(event: MouseEvent) {
  const target = event.target as Node;
  if (box.value?.contains(target) || list.value?.contains(target)) return;
  open.value = false;
}

// Capture, so a scroll inside any ancestor scroller moves the popup with its trigger.
function follow() {
  measure(list.value?.scrollHeight);
}

watch(open, async (isOpen) => {
  if (isOpen) {
    measure();
    document.addEventListener("mousedown", away);
    window.addEventListener("scroll", follow, true);
    window.addEventListener("resize", follow);
    await nextTick();
    measure(list.value?.scrollHeight);
  } else {
    document.removeEventListener("mousedown", away);
    window.removeEventListener("scroll", follow, true);
    window.removeEventListener("resize", follow);
  }
});

watch([open, active], async () => {
  if (!open.value) return;
  await nextTick();
  list.value?.querySelector<HTMLElement>('[data-active="true"]')?.scrollIntoView({ block: "nearest" });
});

onBeforeUnmount(() => {
  document.removeEventListener("mousedown", away);
  window.removeEventListener("scroll", follow, true);
  window.removeEventListener("resize", follow);
});

function close(restoreFocus = true) {
  open.value = false;
  if (restoreFocus) trigger.value?.focus();
}

function commit(index: number) {
  const option = props.options[index];
  if (option) emit("update:modelValue", option.value);
  close();
}

function toggle() {
  if (props.disabled) return;
  active.value = selected.value;
  open.value = !open.value;
}

function onKeydown(event: KeyboardEvent) {
  if (props.disabled) return;
  const at = active.value >= 0 ? active.value : selected.value;

  if (!open.value) {
    if (["ArrowDown", "ArrowUp", "Enter", " "].includes(event.key)) {
      event.preventDefault();
      active.value = at >= 0 ? at : 0;
      open.value = true;
    }
    return;
  }

  if (event.key === "Escape") {
    event.preventDefault();
    // A parent Modal reads `data-overlay-open` and yields Escape to this listbox.
    event.stopPropagation();
    close();
    return;
  }
  if (event.key === "Tab") {
    close(false);
    return;
  }
  if (props.options.length === 0) return;

  let next = -1;
  if (event.key === "ArrowDown") next = at < 0 ? 0 : (at + 1) % props.options.length;
  if (event.key === "ArrowUp") next = at < 0 ? props.options.length - 1 : (at - 1 + props.options.length) % props.options.length;
  if (event.key === "Home") next = 0;
  if (event.key === "End") next = props.options.length - 1;
  if (next >= 0) {
    event.preventDefault();
    active.value = next;
    return;
  }

  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    commit(at >= 0 ? at : 0);
  }
}
</script>

<template>
  <div
    ref="box"
    class="relative"
    :data-overlay-open="open ? 'true' : undefined"
    @keydown="onKeydown"
  >
    <button
      ref="trigger"
      type="button"
      role="combobox"
      aria-haspopup="listbox"
      :aria-controls="`${uid}-list`"
      :aria-expanded="open"
      :aria-label="label"
      :aria-activedescendant="open && active >= 0 ? `${uid}-opt-${active}` : undefined"
      :disabled="disabled"
      :class="[
        FOCUS,
        DISABLED,
        'flex w-full items-center gap-2 rounded-md bg-sunken px-2.5 py-2 text-[12.5px] ring-1 ring-inset transition-colors disabled:ring-line',
        // `ring-line`, not `ring-line-subtle`: this ring is the control's only boundary, and
        // WCAG 1.4.11 wants 3:1 for that. Against its own `bg-sunken` fill `--line-subtle`
        // measures 1.32:1 and `--line` 3.75:1. The dividers keep the subtle line.
        open ? 'text-ink ring-line' : 'text-ink-muted ring-line hover:text-ink',
      ]"
      @click="toggle"
    >
      <span :class="['min-w-0 flex-1 truncate text-left', current ? 'text-ink' : 'text-ink-faint']">
        {{ current?.label ?? placeholder }}
      </span>
      <Icon
        name="chevronDown"
        :class="['h-3.5 w-3.5 shrink-0 text-ink-faint transition-transform duration-150', open && 'rotate-180']"
      />
    </button>

    <!-- Above the Modal's z-50, so a listbox opened inside a dialog is not buried by it. -->
    <Teleport to="body">
      <div
        v-if="open"
        :id="`${uid}-list`"
        ref="list"
        role="listbox"
        :aria-label="label"
        tabindex="-1"
        :style="popupStyle"
        class="xfade fixed z-[60] overflow-y-auto rounded-md bg-surface p-1 shadow-overlay outline-none ring-1 ring-line"
      >
        <div
          v-for="(option, i) in options"
          :id="`${uid}-opt-${i}`"
          :key="option.value"
          role="option"
          :aria-selected="option.value === modelValue"
          :data-active="i === active ? 'true' : undefined"
          :class="[
            TAP,
            'flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-2 text-[12.5px] transition-colors',
            option.value === modelValue
              ? 'bg-surface-active text-ink'
              : i === active
                ? 'bg-surface-hover text-ink'
                : 'text-ink-muted',
          ]"
          @mouseenter="active = i"
          @click="commit(i)"
        >
          <span class="min-w-0 flex-1 truncate">{{ option.label }}</span>
          <Icon v-if="option.value === modelValue" name="check" class="h-3.5 w-3.5 shrink-0 text-ink" />
        </div>
      </div>
    </Teleport>
  </div>
</template>
