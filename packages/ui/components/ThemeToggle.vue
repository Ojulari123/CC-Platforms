<script setup lang="ts">
import { ref } from "vue";
import Icon from "./Icon.vue";
import type { IconName } from "../types/ui";
import type { ThemeChoice } from "../utils/theme";
import { FOCUS, TAP } from "../utils/ui";
import { useTheme } from "../composables/useTheme";
import { announce } from "../composables/useAnnounce";

/* A radiogroup, not a toggle. There are three states and `aria-pressed` can only say two,
   so a button that cycles through them would have to lie about one. Each option carries
   its own icon and the chosen one is filled, so the current mode is readable without
   opening anything. */

const OPTIONS: { value: ThemeChoice; label: string; icon: IconName }[] = [
  { value: "system", label: "System", icon: "monitor" },
  { value: "light", label: "Light", icon: "sun" },
  { value: "dark", label: "Dark", icon: "moon" },
];

const { theme, resolved, setTheme } = useTheme();

const group = ref<HTMLElement | null>(null);

function choose(next: ThemeChoice): void {
  setTheme(next);
  // "System" alone does not tell anyone what they are now looking at.
  announce(next === "system" ? `Theme: system, currently ${resolved.value}` : `Theme: ${next}`);
}

/* Roving tabindex: a radiogroup is one stop on the Tab ring and the arrows move inside
   it. Without this all three buttons are Tab stops, which is the pattern for a toolbar,
   not for a set of mutually exclusive choices. */
function onKeydown(event: KeyboardEvent, index: number): void {
  const step = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 0;
  if (!step) return;
  event.preventDefault();
  const next = OPTIONS[(index + step + OPTIONS.length) % OPTIONS.length]!;
  choose(next.value);
  group.value?.querySelectorAll<HTMLElement>("button")[(index + step + OPTIONS.length) % OPTIONS.length]?.focus();
}
</script>

<template>
  <div
    ref="group"
    role="radiogroup"
    aria-label="Colour theme"
    :class="[TAP, 'flex items-center gap-0.5 rounded-md p-0.5 ring-1 ring-inset ring-line-subtle']"
  >
    <button
      v-for="(option, index) in OPTIONS"
      :key="option.value"
      type="button"
      role="radio"
      :aria-checked="theme === option.value"
      :aria-label="option.value === 'system' ? `System theme, currently ${resolved}` : `${option.label} theme`"
      :tabindex="theme === option.value ? 0 : -1"
      :class="[
        FOCUS,
        'inline-flex h-7 w-7 items-center justify-center rounded transition-colors',
        theme === option.value ? 'bg-surface-active text-ink' : 'text-ink-faint hover:bg-surface-hover hover:text-ink-muted',
      ]"
      @click="choose(option.value)"
      @keydown="onKeydown($event, index)"
    >
      <Icon :name="option.icon" class="h-3.5 w-3.5" />
    </button>
  </div>
</template>
