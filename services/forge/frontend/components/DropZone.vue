<script setup lang="ts">
import { computed, ref } from "vue";
import Btn from "@crescent/ui/components/Btn.vue";
import Icon from "@crescent/ui/components/Icon.vue";
import { FOCUS, MONO_LABEL } from "@crescent/ui/utils/ui";
import { checkFile, formatBytes } from "~/utils/upload";

/* The drop half of the upload. It holds the drag state and the client-side refusals and
   nothing else — the request itself belongs to DatasetUpload, so the same zone can sit
   on the workspace and on /datasets without either one owning a mutation. */
const props = withDefaults(
  defineProps<{
    busy?: boolean;
    /** A refusal that came back from the server, shown in the same alert region. */
    serverError?: string | null;
  }>(),
  { busy: false, serverError: null },
);

const emit = defineEmits<{ accept: [file: File]; reject: [key: string | undefined] }>();

const input = ref<HTMLInputElement | null>(null);
const dragging = ref(false);
const localError = ref<string | null>(null);
const accepted = ref<{ name: string; size: number } | null>(null);

const error = computed(() => localError.value ?? props.serverError);

function take(file: File) {
  const verdict = checkFile(file);
  if (!verdict.ok) {
    accepted.value = null;
    localError.value = verdict.message ?? "File refused.";
    emit("reject", verdict.key);
    return;
  }
  localError.value = null;
  accepted.value = { name: file.name, size: file.size };
  emit("accept", file);
}

function onPick(event: Event) {
  const el = event.target as HTMLInputElement;
  const file = el.files?.[0];
  if (file) take(file);
  // Cleared so picking the same file twice still fires a change event.
  el.value = "";
}

function onDrop(event: DragEvent) {
  dragging.value = false;
  const file = event.dataTransfer?.files?.[0];
  if (file) take(file);
}

defineExpose({ clear: () => { accepted.value = null; localError.value = null; } });
</script>

<template>
  <div
    data-drop-zone
    :data-dragging="dragging ? 'true' : 'false'"
    :class="[
      'mt-8 rounded-md border px-5 py-8 transition-colors focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-[color:var(--accent-ink)]',
      dragging ? 'border-line-strong bg-surface-hover/60' : 'border-line-subtle bg-surface/25',
    ]"
    @dragenter.prevent="dragging = true"
    @dragover.prevent="dragging = true"
    @dragleave="dragging = false"
    @drop.prevent="onDrop"
  >
    <div class="flex flex-wrap items-center gap-x-5 gap-y-4">
      <span class="grid h-10 w-10 shrink-0 place-items-center rounded-md border border-line text-ink-faint">
        <Icon name="plus" class="h-4 w-4" />
      </span>
      <div class="min-w-0 flex-1">
        <p class="text-[13.5px] font-medium">
          {{ dragging ? "Release to check the file" : "Drop a CSV here" }}
        </p>
        <p :class="[MONO_LABEL, 'mt-1 text-ink-muted']">.csv · max 5 MB · first row = column names</p>
      </div>
      <Btn variant="secondary" size="sm" :busy="busy" @click="input?.click()">
        {{ busy ? "Uploading" : "Choose a file" }}
      </Btn>
      <!-- Reachable by keyboard in its own right; the zone wears the focus ring for it. -->
      <input
        id="dataset-file"
        ref="input"
        type="file"
        accept=".csv,text/csv"
        aria-label="Choose a CSV file to upload"
        :class="[FOCUS, 'sr-only']"
        :disabled="busy"
        @change="onPick"
      />
    </div>

    <div
      v-if="error"
      role="alert"
      class="mt-5 flex items-start gap-2.5 rounded-md bg-bad-surface px-3.5 py-3 ring-1 ring-inset ring-bad/25"
    >
      <span class="mt-[1px] shrink-0 text-bad"><Icon name="alert" class="h-4 w-4" /></span>
      <div class="min-w-0">
        <p :class="[MONO_LABEL, 'text-bad']">upload rejected</p>
        <p class="mono mt-1 break-words text-[12px] leading-relaxed text-ink-muted">{{ error }}</p>
      </div>
    </div>

    <div
      v-if="accepted"
      class="mt-5 flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-line-subtle pt-4"
    >
      <span class="mono text-[12.5px] text-ink">{{ accepted.name }}</span>
      <span class="mono text-[12px] text-ink-muted">{{ formatBytes(accepted.size) }}</span>
      <span class="mono text-[12px] text-ink-muted">{{ accepted.size.toLocaleString() }} bytes</span>
      <span :class="[MONO_LABEL, 'ml-auto text-ink-faint']">
        name, extension and size checked · parsing happens server side
      </span>
    </div>
  </div>
</template>
