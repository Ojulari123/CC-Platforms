<script setup lang="ts">
import { computed, onMounted, onUpdated, ref } from "vue";
import { FOCUS, FOCUSABLE } from "../utils/ui";

// `focusable` is deliberately tri-state, so it needs an explicit `undefined` default:
// Vue casts an absent boolean prop with no default to `false`, which would read as
// "the caller forced it out of the tab order" and silently strand an empty panel.
const props = withDefaults(
  defineProps<{
    /** Must match the `id` given to <Tabs>. */
    id: string;
    tab: string;
    /** Force the panel in or out of the tab order. Left alone, the panel takes a tab stop
        only when it holds nothing focusable of its own — the only case where a keyboard
        user would otherwise be unable to reach its content. */
    focusable?: boolean;
  }>(),
  { focusable: undefined },
);

const root = ref<HTMLElement | null>(null);
const empty = ref(false);

function check() {
  if (props.focusable !== undefined) return;
  if (root.value) empty.value = !root.value.querySelector(FOCUSABLE);
}

onMounted(check);
onUpdated(check);

const stop = computed(() => props.focusable ?? empty.value);
</script>

<template>
  <div
    :id="`${id}-panel-${tab}`"
    ref="root"
    role="tabpanel"
    :aria-labelledby="`${id}-tab-${tab}`"
    :tabindex="stop ? 0 : -1"
    :class="[FOCUS, 'outline-none']"
  >
    <slot />
  </div>
</template>
