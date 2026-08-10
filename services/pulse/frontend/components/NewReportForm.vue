<script setup lang="ts">
import { useMutation, useQueryClient } from "@tanstack/vue-query";
import type { ReportResponse } from "~/types/api";

const api = useApi();
const router = useRouter();
const queryClient = useQueryClient();
const { repositories } = useRepositories();

const open = ref(false);
const repoId = ref<number | null>(null);
const weekStart = ref(mondayOf(new Date()));
const errorMessage = ref<string | null>(null);

const canonicalWeek = computed(() => mondayOf(new Date(`${weekStart.value}T00:00:00`)));

const create = useMutation({
  mutationFn: (mode: "blank" | "generate") =>
    api.request<ReportResponse>(mode === "generate" ? "/reports/generate" : "/reports", {
      method: "POST",
      body: { repo_id: repoId.value, week_start: canonicalWeek.value },
    }),
  onSuccess: (report) => {
    queryClient.invalidateQueries({ queryKey: ["reports"] });
    router.push(`/reports/${report.id}`);
  },
  onError: (err) => {
    errorMessage.value = apiMessage(err, "Could not create the report.");
  },
});

const unreviewable = computed(() => {
  const repo = repositories.value.find((r) => r.id === repoId.value);
  if (!repo) return false;
  return repo.dept_id === null && repo.lead_user_id === null && repo.deputy_user_id === null;
});

function start(mode: "blank" | "generate") {
  errorMessage.value = null;
  if (!repoId.value) {
    errorMessage.value = "Pick a repository first.";
    return;
  }
  create.mutate(mode);
}
</script>

<template>
  <div class="mb-6 rounded-lg border border-gray-200 bg-white p-5">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 class="text-sm font-semibold">Start a weekly report</h2>
        <p class="mt-0.5 text-sm text-gray-500">
          One report per repository per week. Draft it yourself, or have it written from
          your synced activity.
        </p>
      </div>
      <button
        class="rounded-md border border-gray-300 px-3 py-2 text-sm font-medium hover:bg-gray-100"
        @click="open = !open"
      >
        {{ open ? "Cancel" : "New report" }}
      </button>
    </div>

    <div v-if="open" class="mt-5 flex flex-wrap items-end gap-4">
      <div>
        <label for="new-repo" class="mb-1 block text-xs font-medium text-gray-600">
          Repository
        </label>
        <select
          id="new-repo"
          v-model="repoId"
          class="w-64 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm"
        >
          <option :value="null">Choose a repository…</option>
          <option v-for="repo in repositories" :key="repo.id" :value="repo.id">
            {{ repo.full_name }}
          </option>
        </select>
      </div>

      <div>
        <label for="new-week" class="mb-1 block text-xs font-medium text-gray-600">
          Week beginning
        </label>
        <input
          id="new-week"
          v-model="weekStart"
          type="date"
          class="rounded-md border border-gray-300 px-3 py-2 text-sm"
        />
        <p class="mt-1 text-xs text-gray-500">Week of {{ formatDate(canonicalWeek) }}</p>
      </div>

      <div class="flex gap-2">
        <button
          :disabled="create.isPending.value"
          class="rounded-md bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-60"
          @click="start('generate')"
        >
          {{ create.isPending.value ? "Working…" : "Draft with AI" }}
        </button>
        <button
          :disabled="create.isPending.value"
          class="rounded-md border border-gray-300 px-3 py-2 text-sm font-medium hover:bg-gray-100 disabled:opacity-60"
          @click="start('blank')"
        >
          Blank draft
        </button>
      </div>
    </div>

    <p
      v-if="open && unreviewable"
      class="mt-4 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"
    >
      This repository has no department and no named lead or deputy, so nobody can
      approve a report about it yet. You can still write one — ask an admin to file it
      under a department on the
      <NuxtLink to="/repositories" class="underline">Repositories</NuxtLink> page and it
      becomes reviewable.
    </p>

    <p v-if="errorMessage" class="mt-3 text-sm text-red-600">{{ errorMessage }}</p>
  </div>
</template>
