<script setup lang="ts">
import { computed, ref } from "vue";
import Btn from "@crescent/ui/components/Btn.vue";
import Eyebrow from "@crescent/ui/components/Eyebrow.vue";
import { DISABLED, FOCUS } from "@crescent/ui/utils/ui";

// Presentational on purpose: the queue row and the report page both own their own
// mutation and their own cache invalidation, and this only has to collect the note and
// say which of the three the user pressed.
export type Decision = "approve" | "request-changes" | "reject";

const props = withDefaults(
  defineProps<{
    reportId: number;
    /** Mirrors _can_approve. False disables the three buttons and shows `reason`. */
    allowed: boolean;
    reason?: string | null;
    authorName?: string;
    busy?: boolean;
    /** Off while a collapsed panel is clipped: clipped controls are still tabbable. */
    active?: boolean;
  }>(),
  { reason: null, authorName: "the author", busy: false, active: true },
);

const emit = defineEmits<{ decide: [decision: Decision, note: string] }>();

const note = ref("");
const errorMessage = ref<string | null>(null);

const blocked = computed(() => !props.allowed || props.busy || !props.active);

// The API accepts a decision with no note. Asking for one on the two that send work
// back is ours, not its: "changes requested" with no words is a dead end for the author.
function submit(decision: Decision) {
  errorMessage.value = null;
  if (decision !== "approve" && !note.value.trim()) {
    errorMessage.value = "Say what needs to change: a note is required to reject or send back.";
    return;
  }
  emit("decide", decision, note.value.trim());
  note.value = "";
}
</script>

<template>
  <div class="min-w-0 rounded-md bg-sunken p-3.5 ring-1 ring-inset ring-line-subtle">
    <Eyebrow>Your decision</Eyebrow>

    <p v-if="!allowed && reason" class="mt-2.5 max-w-[54ch] text-[12px] leading-relaxed text-ink-muted">
      {{ reason }}
    </p>

    <label class="mt-2.5 block">
      <span class="block text-[12px] text-ink-muted">Note to {{ authorName }}</span>
      <textarea
        :id="`decision-note-${reportId}`"
        v-model="note"
        :disabled="blocked"
        rows="3"
        placeholder="What should change, or why this is fine as it stands."
        :class="[
          FOCUS,
          DISABLED,
          // `ring-line`, not `ring-line-subtle`, for the same reason <Select>'s trigger uses it:
          // an inset ring is this field's only boundary, and 1.4.11 asks 3:1 of one. Against its
          // own fill `--line-subtle` measures 2.26 (light) / 2.32 (dark) and `--line` 4.04 / 4.22.
          // Hover moves up a weight rather than onto `--line`, so the resting and hovered rings
          // stay two different things — and `disabled:ring-line` no longer out-draws the live one.
          'mt-1.5 w-full resize-y rounded-md bg-app px-2.5 py-2 text-[12.5px] leading-relaxed text-ink ring-1 ring-inset ring-line transition-[box-shadow] placeholder:text-ink-faint enabled:hover:ring-line-strong disabled:ring-line',
        ]"
      />
    </label>

    <!-- Three on one line: "Request changes" wrapped "Reject" onto its own row, which
         is the worst possible place for a layout accident. -->
    <div class="mt-2.5 flex flex-wrap gap-1.5">
      <Btn size="sm" :disabled="blocked" @click="submit('approve')">Approve</Btn>
      <Btn size="sm" variant="secondary" :disabled="blocked" @click="submit('request-changes')">
        Changes
      </Btn>
      <Btn size="sm" variant="destructive" :disabled="blocked" @click="submit('reject')">
        Reject
      </Btn>
    </div>

    <p v-if="errorMessage" role="alert" class="mt-2.5 text-[12px] leading-relaxed text-bad">
      {{ errorMessage }}
    </p>

    <p v-else class="mt-2.5 text-[12px] leading-relaxed text-ink-muted">
      Deciding takes the report out of your queue and emails {{ authorName }}.
    </p>
  </div>
</template>
