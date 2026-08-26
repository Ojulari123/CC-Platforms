<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, useId, watch } from "vue";
import Icon from "./Icon.vue";
import { FIELD, FOCUS, FOCUSABLE, TAP } from "../utils/ui";

/* Real dialog behaviour: focus moves in, is trapped, and comes back out.
   Focus restoration and the scroll lock are tied to the logical close, not the unmount
   — waiting for the exit animation makes focus visibly lag the user's own decision. */
const props = withDefaults(
  defineProps<{
    open: boolean;
    title: string;
    description?: string;
    /** Where focus should land on open. Defaults to the first form field. */
    initialFocus?: HTMLElement | null;
    /** Off for a dialog whose backdrop must not be a way out (a destructive confirm). */
    closeOnBackdrop?: boolean;
  }>(),
  { closeOnBackdrop: true },
);

const emit = defineEmits<{ close: [] }>();

const descId = `modal-desc-${useId()}`;
const panel = ref<HTMLElement | null>(null);
const restore = ref<HTMLElement | null>(null);
const trapped = ref(false);

// Skips a control inside a collapsed panel, which is still in the DOM and would
// otherwise take a tab stop. `offsetParent` would be the obvious test but it reads 0 in
// a headless DOM, which would empty the trap under test rather than in the browser.
function visible(el: HTMLElement): boolean {
  if (el.hasAttribute("hidden") || el.getAttribute("aria-hidden") === "true") return false;
  const style = typeof getComputedStyle === "function" ? getComputedStyle(el) : null;
  return !style || (style.display !== "none" && style.visibility !== "hidden");
}

function onKey(event: KeyboardEvent) {
  if (event.key === "Escape") {
    // An open listbox inside the dialog gets first refusal on Escape.
    if ((document.activeElement as HTMLElement | null)?.closest('[data-overlay-open="true"]')) return;
    event.stopPropagation();
    emit("close");
    return;
  }
  if (event.key !== "Tab" || !panel.value) return;

  const items = Array.from(panel.value.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(visible);
  if (items.length === 0) {
    event.preventDefault();
    return;
  }
  const first = items[0]!;
  const last = items[items.length - 1]!;
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function release() {
  if (!trapped.value) return;
  trapped.value = false;
  document.removeEventListener("keydown", onKey, true);
  document.body.style.removeProperty("overflow");
}

watch(
  () => props.open,
  async (isOpen) => {
    if (isOpen) {
      if (trapped.value) return;
      trapped.value = true;
      // Captured once per opening, or the restore target drifts to an element inside.
      restore.value = document.activeElement as HTMLElement | null;
      document.addEventListener("keydown", onKey, true);
      document.body.style.setProperty("overflow", "hidden");
      await nextTick();
      const items = panel.value ? Array.from(panel.value.querySelectorAll<HTMLElement>(FOCUSABLE)) : [];
      // Not simply the first focusable: that is the × in the header, and landing on it
      // means the first keystroke goes nowhere.
      const field = items.find((el) => el.matches(FIELD));
      const notClose = items.find((el) => !el.hasAttribute("data-modal-close"));
      (props.initialFocus ?? field ?? notClose ?? panel.value)?.focus();
      return;
    }
    if (!trapped.value) return;
    release();
    restore.value?.focus?.();
    restore.value = null;
  },
  { immediate: true },
);

onBeforeUnmount(release);
</script>

<template>
  <Teleport to="body">
    <Transition name="cc-modal">
      <div v-if="open" class="fixed inset-0 z-50 flex items-start justify-center p-4 sm:p-8">
        <div
          class="fixed inset-0 bg-app/80 backdrop-blur-sm"
          aria-hidden="true"
          @click="closeOnBackdrop && emit('close')"
        />
        <div
          ref="panel"
          role="dialog"
          aria-modal="true"
          :aria-label="title"
          :aria-describedby="description ? descId : undefined"
          tabindex="-1"
          class="cc-modal-panel relative z-10 mt-[8vh] w-full max-w-[440px] overflow-hidden overscroll-contain rounded-md bg-surface shadow-overlay outline-none ring-1 ring-line"
        >
          <div class="flex items-start justify-between gap-4 border-b border-line-subtle px-5 py-4">
            <div>
              <h2 class="text-[14px] font-medium tracking-tight">{{ title }}</h2>
              <p v-if="description" :id="descId" class="mt-1.5 max-w-[42ch] text-[12px] leading-relaxed text-ink-muted">
                {{ description }}
              </p>
            </div>
            <button
              type="button"
              aria-label="Close"
              data-modal-close=""
              :class="[FOCUS, TAP, '-mr-1 -mt-1 grid place-items-center rounded-md p-1.5 text-ink-faint transition-colors hover:bg-surface-hover hover:text-ink']"
              @click="emit('close')"
            >
              <Icon name="x" class="h-4 w-4" />
            </button>
          </div>

          <div v-if="$slots.default" class="px-5 py-4">
            <slot />
          </div>

          <div
            v-if="$slots.footer"
            class="flex flex-wrap items-center justify-end gap-2 border-t border-line-subtle px-5 py-3.5"
          >
            <slot name="footer" />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
