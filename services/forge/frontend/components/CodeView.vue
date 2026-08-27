<script setup lang="ts">
import { computed } from "vue";
import { FOCUS, MONO_LABEL } from "@crescent/ui/utils/ui";
import { parseCodeBlocks } from "~/utils/workflows";

/* The generated script, split back into the blocks codegen.py wrote it in. Each block
   carries the step it came from in its own heading comment, so the mapping from canvas to
   code is the server's statement and not a guess made in the browser.

   Rendered as text nodes into <pre>, never v-html: this string is generated from values a
   person typed, and one prompt containing a tag would be the whole argument for escaping. */
const props = withDefaults(
  defineProps<{
    code: string;
    /** Step kind to light up, so hovering a canvas step marks its block. */
    activeKind?: string;
  }>(),
  { activeKind: "" },
);

const emit = defineEmits<{ hover: [kind: string] }>();

const blocks = computed(() => parseCodeBlocks(props.code).filter((block) => block.lines.length));
</script>

<template>
  <div class="divide-y divide-line-subtle">
    <section
      v-for="(block, i) in blocks"
      :key="i"
      :class="[
        'transition-colors',
        block.kind && block.kind === activeKind ? 'bg-surface-active' : '',
      ]"
      @mouseenter="emit('hover', block.kind)"
    >
      <div class="flex flex-wrap items-baseline gap-x-2 gap-y-1 px-4 pt-3">
        <span v-if="block.position" :class="[MONO_LABEL, 'text-ink-faint']">step {{ block.position }}</span>
        <span v-if="block.kind" class="mono text-[12px] font-medium text-ink">{{ block.kind }}</span>
        <span class="mono text-[12px] text-ink-muted">{{ block.heading }}</span>
      </div>
      <pre
        class="mono overflow-x-auto whitespace-pre px-4 pb-3 pt-2 text-[12.5px] leading-relaxed text-ink"
      ><code>{{ block.lines.join("\n") }}</code></pre>
    </section>
    <p v-if="!blocks.length" class="px-4 py-6 text-[12.5px] text-ink-muted">
      Nothing to generate yet. Add the steps a run needs and the script appears here.
    </p>
  </div>
</template>
