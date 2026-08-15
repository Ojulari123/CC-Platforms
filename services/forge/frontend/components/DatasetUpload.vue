<script setup lang="ts">
import { useMutation, useQueryClient } from "@tanstack/vue-query";
import type { DatasetResponse } from "~/types/api";

/* The request half of the upload. DropZone holds the drag state and the refusals a
   browser can decide on its own; everything past that is the server's answer, shown in
   the same alert region so a file is never refused in two different places. */
const emit = defineEmits<{ uploaded: [dataset: DatasetResponse] }>();

const api = useApi();
const queryClient = useQueryClient();

const serverError = ref<string | null>(null);

const mutation = useMutation({
  mutationFn: (form: FormData) =>
    api.request<DatasetResponse>("/datasets", { method: "POST", body: form }),
  onSuccess: (dataset) => {
    serverError.value = null;
    queryClient.invalidateQueries({ queryKey: ["datasets"] });
    emit("uploaded", dataset);
  },
  onError: (err: unknown) => {
    const status = statusOf(err);
    const detail = (err as { data?: { detail?: unknown } })?.data?.detail;
    if (status === 413) {
      serverError.value = REJECTIONS.find((r) => r.key === "size")?.message ?? "File is too large.";
    } else if (status === 400) {
      // The service names the cause — not valid UTF-8, empty, no header row, malformed
      // CSV — so pass its own words through rather than flattening them to "invalid".
      serverError.value = typeof detail === "string" ? detail : "That file could not be read as CSV.";
    } else if (status === 429) {
      serverError.value = "Too many uploads in a row. Wait a minute and try again.";
    } else {
      serverError.value = "Upload failed. Check that the Forge service is reachable and try again.";
    }
  },
});

function onAccept(file: File) {
  serverError.value = null;
  const form = new FormData();
  form.append("file", file);
  mutation.mutate(form);
}
</script>

<template>
  <DropZone
    :busy="mutation.isPending.value"
    :server-error="serverError"
    @accept="onAccept"
    @reject="serverError = null"
  />
</template>
