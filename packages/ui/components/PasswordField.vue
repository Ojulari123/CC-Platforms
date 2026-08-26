<script setup lang="ts">
import { ref } from "vue";
import Icon from "./Icon.vue";
import { DISABLED, FOCUS, MONO_LABEL, TAP } from "../utils/ui";

/* Every password on the platform is typed into this, so the reveal behaves the same way
   everywhere. Three things it gets right that this control usually gets wrong:

   - The toggle is a <button type="button">. A bare <button> inside a form submits it,
     which is the common way a reveal ships broken.
   - It says what it does. aria-pressed carries the state, the label flips between "Show
     password" and "Hide password", and aria-controls names the input it acts on — an icon
     on its own tells a screen reader nothing.
   - The input stays a real <input> keeping its id, name and autocomplete, so password
     managers still fill it. Revealing moves `type` and nothing else. */

withDefaults(
  defineProps<{
    modelValue: string;
    id: string;
    name: string;
    label?: string;
    autocomplete?: string;
    // Matches the form it drops into: the recovery screens label their fields `faint`,
    // Forge's screens `muted`.
    tone?: "muted" | "faint";
    invalid?: boolean;
    describedby?: string;
    disabled?: boolean;
    // Work in flight on the surrounding form. Marks the input aria-busy; the reveal stays
    // usable, because reading back what you typed is exactly what a slow submit invites.
    busy?: boolean;
  }>(),
  {
    label: "Password",
    autocomplete: "current-password",
    tone: "muted",
    invalid: false,
    describedby: undefined,
    disabled: false,
    busy: false,
  },
);

const emit = defineEmits<{ "update:modelValue": [value: string]; blur: [event: FocusEvent] }>();

// Hidden on every mount. Nothing about a revealed password is remembered across a page
// load — the next person at the machine starts from dots.
const revealed = ref(false);
const field = ref<HTMLInputElement | null>(null);

// So a page can still put the cursor here on mount, as it could with a raw input.
defineExpose({ focus: () => field.value?.focus() });
</script>

<template>
  <div>
    <!-- `for` binds the label to the input; the toggle sits outside it, so clicking the
         label still lands in the field rather than flipping the password open. -->
    <div v-if="label || $slots.action" class="mb-1.5 flex items-baseline justify-between gap-3">
      <label :for="id" :class="[MONO_LABEL, tone === 'faint' ? 'text-ink-faint' : 'text-ink-muted']">{{ label }}</label>
      <slot name="action" />
    </div>

    <div class="relative">
      <input
        :id="id"
        ref="field"
        :name="name"
        :type="revealed ? 'text' : 'password'"
        :value="modelValue"
        :autocomplete="autocomplete"
        :disabled="disabled"
        :aria-busy="busy || undefined"
        :aria-invalid="invalid ? true : undefined"
        :aria-describedby="describedby"
        spellcheck="false"
        :class="[
          'mono',
          FOCUS,
          TAP,
          DISABLED,
          'w-full rounded-md bg-app py-2.5 pl-3 pr-11 text-[13px] text-ink ring-1 ring-inset transition-colors enabled:hover:ring-line-strong disabled:ring-line',
          invalid ? 'ring-bad' : 'ring-line',
        ]"
        @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
        @blur="emit('blur', $event)"
      />
      <button
        type="button"
        :aria-pressed="revealed"
        :aria-label="revealed ? 'Hide password' : 'Show password'"
        :aria-controls="id"
        :disabled="disabled"
        :class="[
          FOCUS,
          TAP,
          DISABLED,
          'absolute right-1 top-1/2 inline-flex -translate-y-1/2 items-center justify-center rounded-md p-2 text-ink-muted transition-colors enabled:hover:text-ink',
        ]"
        @click="revealed = !revealed"
      >
        <Icon :name="revealed ? 'eyeOff' : 'eye'" class="h-4 w-4" />
      </button>
    </div>
  </div>
</template>
