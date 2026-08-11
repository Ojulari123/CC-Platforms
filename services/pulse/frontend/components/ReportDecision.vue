<script setup lang="ts">
import { useMutation, useQueryClient } from "@tanstack/vue-query";
import type { ReportResponse } from "~/types/api";

const props = defineProps<{ reportId: number }>();
const emit = defineEmits<{ decided: [] }>();

const api = useApi();
const queryClient = useQueryClient();

const note = ref("");
const errorMessage = ref<string | null>(null);

type Decision = "approve" | "reject" | "request-changes";

const decide = useMutation({
  mutationFn: (decision: Decision) =>
    api.request<ReportResponse>(`/reports/${props.reportId}/${decision}`, {
      method: "POST",
      body: { note: note.value.trim() || null },
    }),
  onSuccess: () => {
    note.value = "";
    queryClient.invalidateQueries({ queryKey: ["reports"] });
    queryClient.invalidateQueries({ queryKey: ["review-queue"] });
    queryClient.invalidateQueries({ queryKey: ["report", String(props.reportId)] });
    emit("decided");
  },
  onError: (err) => {
    errorMessage.value = apiMessage(err, "Could not record that decision.");
  },
});

// The API accepts a decision with no note; the requirement is ours, not its.
function submit(decision: Decision) {
  errorMessage.value = null;
  if (decision !== "approve" && !note.value.trim()) {
    errorMessage.value = "Say what needs to change: a note is required to reject or send back.";
    return;
  }
  decide.mutate(decision);
}
</script>

<template>
  <div>
    <label :for="`note-${reportId}`" class="mb-1 block text-xs font-medium text-gray-600">
      Note to the author
    </label>
    <textarea
      :id="`note-${reportId}`"
      v-model="note"
      rows="3"
      class="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-gray-500 focus:outline-none"
      placeholder="Optional when approving, required when rejecting or asking for changes."
    />

    <div class="mt-3 flex flex-wrap gap-2">
      <button
        :disabled="decide.isPending.value"
        class="rounded-md bg-green-700 px-3 py-2 text-sm font-medium text-white hover:bg-green-800 disabled:opacity-60"
        @click="submit('approve')"
      >
        Approve
      </button>
      <button
        :disabled="decide.isPending.value"
        class="rounded-md border border-gray-300 px-3 py-2 text-sm font-medium hover:bg-gray-100 disabled:opacity-60"
        @click="submit('request-changes')"
      >
        Request changes
      </button>
      <button
        :disabled="decide.isPending.value"
        class="rounded-md border border-red-300 px-3 py-2 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-60"
        @click="submit('reject')"
      >
        Reject
      </button>
    </div>

    <p v-if="errorMessage" class="mt-2 text-sm text-red-600">{{ errorMessage }}</p>
  </div>
</template>
