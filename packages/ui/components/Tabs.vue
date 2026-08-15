<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import type { TabItem } from "../types/ui";
import { FOCUS, TAP } from "../utils/ui";

/* Real tabs: roving tabindex, arrow keys, and panels wired by id.
   One indicator that travels, not one that unmounts here and mounts there. Because it
   moves on a transition, mashing tabs retargets from the live position instead of
   restarting a wipe from the destination's left edge. */
const props = withDefaults(
  defineProps<{
    /** Prefix for the generated tab and panel ids. Must match the <TabPanel> `id`. */
    id: string;
    items: TabItem[];
    modelValue: string;
    /** Accessible name for the tablist. */
    label: string;
    variant?: "underline" | "mono";
    /** Set when the screen renders a <TabPanel> for the selected tab. Off by default: a
        rail used purely as a filter has no panels, and pointing `aria-controls` at an id
        that was never rendered is worse than omitting it. */
    hasPanel?: boolean;
  }>(),
  { variant: "underline", hasPanel: false },
);

const emit = defineEmits<{ "update:modelValue": [value: string] }>();

const rail = ref<HTMLElement | null>(null);
const indicator = ref<{ x: number; w: number; move: boolean } | null>(null);
let observer: ResizeObserver | null = null;

function tabId(id: string) {
  return `${props.id}-tab-${id}`;
}

// Looked up by dataset rather than by a built selector: a tab id is caller-supplied and
// CSS.escape is not available in every environment this runs in.
function tabEl(id: string): HTMLElement | undefined {
  const all = rail.value ? Array.from(rail.value.querySelectorAll<HTMLElement>("[data-tab-id]")) : [];
  return all.find((el) => el.dataset.tabId === id);
}

function measure() {
  const el = tabEl(props.modelValue);
  if (!el) {
    indicator.value = null;
    return;
  }
  const x = el.offsetLeft;
  const w = el.offsetWidth;
  const prev = indicator.value;
  if (prev && prev.x === x && prev.w === w) return;
  indicator.value = { x, w, move: prev !== null };
}

const indicatorStyle = computed(() => ({
  width: `${indicator.value?.w ?? 0}px`,
  opacity: indicator.value ? "1" : "0",
  transform: `translateX(${indicator.value?.x ?? 0}px)`,
  transition: indicator.value?.move
    ? "transform 220ms cubic-bezier(0.23,1,0.32,1), width 220ms cubic-bezier(0.23,1,0.32,1)"
    : "none",
}));

onMounted(() => {
  measure();
  if (typeof ResizeObserver === "undefined" || !rail.value) return;
  observer = new ResizeObserver(measure);
  observer.observe(rail.value);
});

onBeforeUnmount(() => observer?.disconnect());

watch(
  [() => props.modelValue, () => props.items.map((t) => t.id).join("|")],
  async () => {
    await nextTick();
    measure();
  },
);

function onKeydown(event: KeyboardEvent) {
  const i = props.items.findIndex((t) => t.id === props.modelValue);
  if (i < 0) return;
  let next = -1;
  if (event.key === "ArrowRight") next = (i + 1) % props.items.length;
  if (event.key === "ArrowLeft") next = (i - 1 + props.items.length) % props.items.length;
  if (event.key === "Home") next = 0;
  if (event.key === "End") next = props.items.length - 1;
  if (next < 0) return;
  event.preventDefault();
  const target = props.items[next]!;
  emit("update:modelValue", target.id);
  nextTick(() => tabEl(target.id)?.focus());
}

// Only claim a panel that is actually in the document.
function wired(item: TabItem): boolean {
  return item.hasPanel ?? (props.hasPanel && item.id === props.modelValue);
}
</script>

<template>
  <div
    ref="rail"
    role="tablist"
    :aria-label="label"
    class="relative flex items-center gap-4 border-b border-line-subtle"
    @keydown="onKeydown"
  >
    <span
      aria-hidden="true"
      class="pointer-events-none absolute -bottom-px left-0 h-px bg-ink"
      :style="indicatorStyle"
    />
    <button
      v-for="item in items"
      :id="tabId(item.id)"
      :key="item.id"
      :data-tab-id="item.id"
      type="button"
      role="tab"
      :aria-selected="item.id === modelValue"
      :aria-controls="wired(item) ? `${id}-panel-${item.id}` : undefined"
      :tabindex="item.id === modelValue ? 0 : -1"
      :class="[
        FOCUS,
        TAP,
        'relative -mb-px pb-2.5 transition-colors',
        variant === 'mono' ? 'mono text-[12px] uppercase tracking-[0.12em]' : 'text-[12.5px]',
        item.id === modelValue ? 'font-medium text-ink' : 'text-ink-faint hover:text-ink-muted',
      ]"
      @click="emit('update:modelValue', item.id)"
    >
      {{ item.label }}
      <span v-if="item.hint" class="mono ml-1.5 text-[11px] text-ink-muted">{{ item.hint }}</span>
    </button>
    <div v-if="$slots.default" class="ml-auto pb-2.5">
      <slot />
    </div>
  </div>
</template>
