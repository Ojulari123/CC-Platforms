<script setup lang="ts">
import { z } from "zod";
import { useMutation, useQueryClient } from "@tanstack/vue-query";
import type { DatasetResponse } from "~/types/api";

const api = useApi();
const queryClient = useQueryClient();

const uploadSchema = z.object({
  file: z.instanceof(File, { message: "Choose a CSV file to upload" }),
  name: z.string().optional(),
});

const fileInput = ref<HTMLInputElement | null>(null);
const selectedFile = ref<File | null>(null);
const name = ref("");
const validationError = ref<string | null>(null);

function onFileChange(event: Event) {
  const target = event.target as HTMLInputElement;
  selectedFile.value = target.files?.[0] ?? null;
  validationError.value = null;
}

const mutation = useMutation({
  mutationFn: (form: FormData) =>
    api.request<DatasetResponse>("/datasets", { method: "POST", body: form }),
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: ["datasets"] });
    selectedFile.value = null;
    name.value = "";
    if (fileInput.value) fileInput.value.value = "";
  },
});

const errorMessage = computed(() => {
  if (validationError.value) return validationError.value;
  if (!mutation.isError.value) return null;
  const status = (mutation.error.value as { statusCode?: number; status?: number })
    ?.statusCode
    ?? (mutation.error.value as { status?: number })?.status;
  if (status === 413) return "That file is too large. Please upload a smaller CSV.";
  if (status === 400) return "That doesn't look like a valid CSV file.";
  return "Upload failed. Please try again.";
});

function onSubmit() {
  validationError.value = null;
  const parsed = uploadSchema.safeParse({
    file: selectedFile.value ?? undefined,
    name: name.value.trim() || undefined,
  });
  if (!parsed.success) {
    validationError.value = parsed.error.issues[0]?.message ?? "Invalid input";
    return;
  }

  const form = new FormData();
  form.append("file", parsed.data.file);
  if (parsed.data.name) form.append("name", parsed.data.name);
  mutation.mutate(form);
}
</script>

<template>
  <div class="mb-8 rounded-lg border border-gray-200 bg-white p-5">
    <h2 class="mb-4 text-sm font-semibold text-gray-800">Upload a dataset</h2>

    <form class="space-y-4" @submit.prevent="onSubmit">
      <div>
        <label for="file" class="mb-1 block text-sm font-medium">CSV file</label>
        <input
          id="file"
          ref="fileInput"
          type="file"
          accept=".csv"
          class="block w-full text-sm text-gray-600 file:mr-3 file:rounded-md file:border file:border-gray-300 file:bg-gray-50 file:px-3 file:py-1.5 file:text-sm file:font-medium hover:file:bg-gray-100"
          @change="onFileChange"
        />
      </div>

      <div>
        <label for="name" class="mb-1 block text-sm font-medium">
          Name <span class="font-normal text-gray-400">(optional)</span>
        </label>
        <input
          id="name"
          v-model="name"
          type="text"
          class="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-gray-500 focus:outline-none"
          placeholder="Defaults to the file name"
        />
      </div>

      <p v-if="errorMessage" class="text-sm text-red-600">{{ errorMessage }}</p>

      <p v-if="mutation.isSuccess.value" class="text-sm text-green-600">
        Dataset uploaded.
      </p>

      <button
        type="submit"
        :disabled="mutation.isPending.value"
        class="rounded-md bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-60"
      >
        {{ mutation.isPending.value ? "Uploading…" : "Upload" }}
      </button>
    </form>
  </div>
</template>
