<script setup lang="ts">
const props = defineProps<{ open: boolean; title: string; description?: string }>();
const emit = defineEmits<{ close: [] }>();

// Escape closes, and the body doesn't scroll behind an open dialog.
function onKey(event: KeyboardEvent) {
  if (event.key === "Escape" && props.open) emit("close");
}

onMounted(() => window.addEventListener("keydown", onKey));
onUnmounted(() => {
  window.removeEventListener("keydown", onKey);
  document.body.style.removeProperty("overflow");
});

watch(
  () => props.open,
  (open) => {
    if (!import.meta.client) return;
    if (open) document.body.style.setProperty("overflow", "hidden");
    else document.body.style.removeProperty("overflow");
  },
);
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto p-4 sm:p-6">
      <div class="fixed inset-0 bg-slate-900/40" @click="emit('close')" />
      <div
        class="relative z-10 mt-8 w-full max-w-lg rounded-xl bg-white p-6 shadow-xl ring-1 ring-slate-900/5"
        role="dialog"
        aria-modal="true"
      >
        <h2 class="text-lg font-semibold">{{ title }}</h2>
        <p v-if="description" class="mt-1 text-sm text-slate-500">{{ description }}</p>
        <div class="mt-5">
          <slot />
        </div>
      </div>
    </div>
  </Teleport>
</template>
