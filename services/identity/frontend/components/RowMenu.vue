<script lang="ts">
export interface RowMenuItem {
  id: string;
  label: string;
  tone?: "default" | "bad";
  separatorBefore?: boolean;
}
</script>

<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { FOCUS } from "@crescent/ui/utils/ui";

/* The per-row ⋯ menu. Controlled from the table so only one row can be open at a time. */
const props = defineProps<{ open: boolean; label: string; items: RowMenuItem[] }>();

const emit = defineEmits<{ "update:open": [value: boolean]; select: [id: string] }>();

const box = ref<HTMLElement | null>(null);
const trigger = ref<HTMLButtonElement | null>(null);

function away(event: MouseEvent) {
  if (box.value && !box.value.contains(event.target as Node)) emit("update:open", false);
}

function esc(event: KeyboardEvent) {
  if (event.key !== "Escape") return;
  event.stopPropagation();
  emit("update:open", false);
  trigger.value?.focus();
}

function detach() {
  document.removeEventListener("mousedown", away);
  document.removeEventListener("keydown", esc);
}

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) {
      document.addEventListener("mousedown", away);
      document.addEventListener("keydown", esc);
    } else {
      detach();
    }
  },
  { immediate: true },
);

onBeforeUnmount(detach);

function choose(id: string) {
  emit("update:open", false);
  emit("select", id);
}
</script>

<template>
  <span ref="box" class="relative inline-block">
    <button
      ref="trigger"
      type="button"
      aria-haspopup="menu"
      :aria-expanded="open"
      :aria-label="label"
      :class="[
        FOCUS,
        'rounded p-1 text-ink-faint transition-[opacity,color,background-color] hover:bg-surface-hover hover:text-ink focus-visible:opacity-100 group-hover/row:opacity-100 [@media(hover:none)]:opacity-100',
        open ? 'opacity-100' : 'opacity-0',
      ]"
      @click="emit('update:open', !open)"
    >
      <span aria-hidden="true" class="block text-[13px] leading-none">⋯</span>
    </button>

    <span
      v-if="open"
      role="menu"
      :aria-label="label"
      class="xfade absolute right-0 top-full z-30 mt-1 block w-[196px] overflow-hidden rounded-md bg-surface p-1 text-left shadow-2xl ring-1 ring-line"
    >
      <template v-for="item in items" :key="item.id">
        <span v-if="item.separatorBefore" class="my-1 block h-px bg-line-subtle" aria-hidden="true" />
        <button
          type="button"
          role="menuitem"
          :class="[
            FOCUS,
            'block w-full rounded px-2.5 py-1.5 text-left text-[12px] transition-colors',
            item.tone === 'bad' ? 'text-bad hover:bg-bad-surface' : 'text-ink hover:bg-surface-hover',
          ]"
          @click="choose(item.id)"
        >
          {{ item.label }}
        </button>
      </template>
    </span>
  </span>
</template>
