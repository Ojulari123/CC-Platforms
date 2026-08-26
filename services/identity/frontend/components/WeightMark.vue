<script setup lang="ts">
// What it costs if it is wrong: 1 routine, 2 changes access, 3 irreversible.
const RAMP = ["bg-line-subtle", "bg-line", "bg-line-strong", "bg-ink"];
const WORD: Record<number, string> = { 1: "routine", 2: "changes access", 3: "irreversible" };

defineProps<{ weight: 1 | 2 | 3 }>();
</script>

<template>
  <span class="inline-flex items-center gap-1.5">
    <span class="inline-flex items-end gap-[2px]" aria-hidden="true">
      <span
        v-for="i in [1, 2, 3]"
        :key="i"
        :class="['w-[3px] rounded-[1px]', i <= weight ? RAMP[weight] : 'bg-line-subtle']"
        :style="{ height: `${3 + i * 2}px` }"
      />
    </span>
    <span class="mono text-[12px] uppercase tracking-[0.08em] text-ink-faint">{{ WORD[weight] }}</span>
  </span>
</template>
