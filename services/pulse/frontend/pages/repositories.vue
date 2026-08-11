<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import type {
  ApproverCandidateList,
  DepartmentResponse,
  Page,
  RepositoryResponse,
  UserMeResponse,
} from "~/types/api";

definePageMeta({ middleware: "auth" });

const api = useApi();
const identity = useIdentityApi();
const auth = useAuth();
const queryClient = useQueryClient();
const { repositories, isPending, isError, error } = useRepositories();

const canFile = computed(() => {
  const me = auth.user.value as UserMeResponse | null;
  if (!me) return false;
  return me.is_platform_admin || (me.memberships ?? []).some((m) => m.role === "admin");
});

const { data: unfiled } = useQuery({
  queryKey: ["repositories", "unfiled"],
  enabled: canFile,
  queryFn: () =>
    api.request<Page<RepositoryResponse>>("/github/repositories/unfiled", {
      query: { limit: 200 },
    }),
});

// Departments come from identity; Pulse holds no copy of them, only the ids.
const { data: departments } = useQuery({
  queryKey: ["departments"],
  queryFn: () => identity.request<DepartmentResponse[]>("/departments"),
});

const deptName = computed(() => {
  const map = new Map<number, string>();
  for (const dept of departments.value ?? []) map.set(dept.id, dept.name);
  return map;
});

const needsFiling = computed(() => unfiled.value?.items ?? []);
const filed = computed(() => repositories.value.filter((repo) => repo.dept_id !== null));

const selected = ref<number[]>([]);
const targetDeptId = ref<number | null>(null);
const fileError = ref<string | null>(null);
const filedCount = ref(0);

watch(needsFiling, (rows) => {
  const live = new Set(rows.map((repo) => repo.id));
  selected.value = selected.value.filter((id) => live.has(id));
});

function toggle(repoId: number) {
  selected.value = selected.value.includes(repoId)
    ? selected.value.filter((id) => id !== repoId)
    : [...selected.value, repoId];
}

const file = useMutation({
  mutationFn: (deptId: number) =>
    api.request<RepositoryResponse[]>(`/github/repositories/department/${deptId}`, {
      method: "PUT",
      body: { repo_ids: selected.value },
    }),
  onSuccess: (rows) => {
    filedCount.value = rows.length;
    selected.value = [];
    queryClient.invalidateQueries({ queryKey: ["repositories"] });
    // Reports carry a denormalised dept_id, so filing a repo restamps them.
    queryClient.invalidateQueries({ queryKey: ["reports"] });
    queryClient.invalidateQueries({ queryKey: ["review-queue"] });
  },
  onError: (err) => {
    fileError.value = apiMessage(err, "Could not file those repositories.");
  },
});

function fileSelected() {
  fileError.value = null;
  filedCount.value = 0;
  if (!targetDeptId.value) {
    fileError.value = "Pick a department first.";
    return;
  }
  if (!selected.value.length) {
    fileError.value = "Tick at least one repository.";
    return;
  }
  file.mutate(targetDeptId.value);
}

function repoCount(n: number): string {
  return `${n} ${n === 1 ? "repository" : "repositories"}`;
}

function approverLabel(repo: RepositoryResponse): string {
  const names: string[] = [];
  if (repo.lead_user_id !== null) names.push(`${personName(repo.lead, repo.lead_user_id)} (lead)`);
  if (repo.deputy_user_id !== null) {
    names.push(`${personName(repo.deputy, repo.deputy_user_id)} (deputy)`);
  }
  return names.length ? names.join(", ") : "Nobody named";
}

// Mirrors _require_can_admin_repo. Getting it wrong only shows or hides the button; the
// API is what actually decides.
function canAdminRepo(repo: RepositoryResponse): boolean {
  const me = auth.user.value as UserMeResponse | null;
  if (!me) return false;
  if (me.is_platform_admin) return true;
  return (
    repo.dept_id !== null &&
    (me.memberships ?? []).some((m) => m.dept_id === repo.dept_id && m.role === "admin")
  );
}

const editingRepoId = ref<number | null>(null);
const leadChoice = ref<number | null>(null);
const deputyChoice = ref<number | null>(null);
const approverError = ref<string | null>(null);

const { data: candidates, isPending: candidatesPending } = useQuery({
  queryKey: computed(() => ["repositories", editingRepoId.value, "approver-candidates"]),
  enabled: computed(() => editingRepoId.value !== null),
  queryFn: () =>
    api.request<ApproverCandidateList>(
      `/github/repositories/${editingRepoId.value}/approver-candidates`,
    ),
});

function startEditing(repo: RepositoryResponse) {
  editingRepoId.value = repo.id;
  leadChoice.value = repo.lead_user_id;
  deputyChoice.value = repo.deputy_user_id;
  approverError.value = null;
}

function candidateLabel(user_id: number): string {
  const match = (candidates.value?.items ?? []).find((c) => c.user_id === user_id);
  const name = personName(match?.person ?? null, user_id);
  return match?.has_activity ? name : `${name} (no activity here)`;
}

const saveApprovers = useMutation({
  mutationFn: async (repo: RepositoryResponse) => {
    const base = `/github/repositories/${repo.id}`;
    const lead = leadChoice.value;
    const deputy = deputyChoice.value;

    // The API rejects one person holding both posts, so a straight swap has to vacate the
    // clashing post before claiming it, or the first call 400s on the old value.
    if (lead !== null && lead === repo.deputy_user_id) {
      await api.request<RepositoryResponse>(`${base}/deputy`, { method: "DELETE" });
    }
    if (deputy !== null && deputy === repo.lead_user_id) {
      await api.request<RepositoryResponse>(`${base}/lead`, { method: "DELETE" });
    }
    if (lead !== repo.lead_user_id) {
      await (lead === null
        ? api.request<RepositoryResponse>(`${base}/lead`, { method: "DELETE" })
        : api.request<RepositoryResponse>(`${base}/lead/${lead}`, { method: "PUT" }));
    }
    if (deputy !== repo.deputy_user_id) {
      await (deputy === null
        ? api.request<RepositoryResponse>(`${base}/deputy`, { method: "DELETE" })
        : api.request<RepositoryResponse>(`${base}/deputy/${deputy}`, { method: "PUT" }));
    }
  },
  onSuccess: () => {
    editingRepoId.value = null;
    queryClient.invalidateQueries({ queryKey: ["repositories"] });
    // Who can approve just changed, so both queues can be stale.
    queryClient.invalidateQueries({ queryKey: ["review-queue"] });
    queryClient.invalidateQueries({ queryKey: ["reports"] });
  },
  onError: (err) => {
    approverError.value = apiMessage(err, "Could not change the approvers.");
  },
});

function submitApprovers(repo: RepositoryResponse) {
  approverError.value = null;
  if (leadChoice.value !== null && leadChoice.value === deputyChoice.value) {
    approverError.value = "The lead and deputy have to be two different people.";
    return;
  }
  saveApprovers.mutate(repo);
}
</script>

<template>
  <div class="mx-auto max-w-6xl px-4 py-8">
    <header class="mb-6">
      <h1 class="text-2xl font-semibold">Repositories</h1>
      <p class="mt-1 text-sm text-gray-500">
        A repository arrives from GitHub with no department. Until it has one, reports
        written about it belong to no department either, and only the repository's own
        lead or deputy (or a platform admin) can approve them.
      </p>
    </header>

    <section
      v-if="canFile"
      class="mb-8 rounded-lg border p-5"
      :class="needsFiling.length ? 'border-amber-200 bg-amber-50' : 'border-gray-200 bg-white'"
    >
      <h2 class="text-base font-semibold">
        {{
          needsFiling.length
            ? `${repoCount(needsFiling.length)} without a department`
            : "Every repository has a department"
        }}
      </h2>

      <p v-if="!needsFiling.length" class="mt-1 text-sm text-gray-500">
        Nothing to file. New repositories will appear here after the next sync.
      </p>

      <template v-else>
        <p class="mt-1 text-sm text-gray-700">
          File each one under the department that owns it. Reports already written about
          it move with it, so a stranded report becomes reviewable straight away.
        </p>

        <ul class="mt-4 divide-y divide-amber-200 border-y border-amber-200">
          <li v-for="repo in needsFiling" :key="repo.id" class="flex items-start gap-3 py-3">
            <input
              :id="`file-${repo.id}`"
              type="checkbox"
              class="mt-1"
              :checked="selected.includes(repo.id)"
              @change="toggle(repo.id)"
            />
            <label :for="`file-${repo.id}`" class="cursor-pointer">
              <span class="block text-sm font-medium">{{ repo.full_name }}</span>
              <span class="mt-0.5 block text-xs text-gray-600">
                Approvers: {{ approverLabel(repo) }}
                <template v-if="repo.lead_user_id === null && repo.deputy_user_id === null">
                  (no report about this repository can be approved until it is filed).
                </template>
              </span>
            </label>
          </li>
        </ul>

        <div class="mt-4 flex flex-wrap items-end gap-3">
          <div>
            <label for="target-dept" class="mb-1 block text-xs font-medium text-gray-600">
              Department
            </label>
            <select
              id="target-dept"
              v-model="targetDeptId"
              class="w-56 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm"
            >
              <option :value="null">Choose a department…</option>
              <option v-for="dept in departments ?? []" :key="dept.id" :value="dept.id">
                {{ dept.name }}
              </option>
            </select>
          </div>
          <button
            :disabled="file.isPending.value"
            class="rounded-md bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-60"
            @click="fileSelected"
          >
            {{ file.isPending.value ? "Filing…" : `File ${repoCount(selected.length)}` }}
          </button>
        </div>
      </template>

      <p v-if="fileError" class="mt-3 text-sm text-red-600">{{ fileError }}</p>
      <p v-else-if="filedCount" class="mt-3 text-sm text-green-700">
        Filed {{ repoCount(filedCount) }}. Any reports about them moved to that
        department too.
      </p>
    </section>

    <p v-if="isPending" class="text-sm text-gray-500">Loading repositories…</p>

    <p v-else-if="isError" class="text-sm text-red-600">
      {{ apiMessage(error, "Could not load repositories.") }}
    </p>

    <div v-else-if="!filed.length" class="rounded-lg border border-gray-200 bg-white p-6">
      <p class="text-sm font-medium">No filed repositories to show.</p>
      <p class="mt-1 text-sm text-gray-500">
        You see a repository once you've worked in it, lead or deputise it, or administer
        the department it belongs to.
      </p>
    </div>

    <div v-else class="overflow-hidden rounded-lg border border-gray-200 bg-white">
      <table class="w-full text-left text-sm">
        <thead class="border-b border-gray-200 bg-gray-50 text-gray-600">
          <tr>
            <th class="px-4 py-2 font-medium">Repository</th>
            <th class="px-4 py-2 font-medium">Department</th>
            <th class="px-4 py-2 font-medium">Approvers</th>
            <th class="px-4 py-2 font-medium">Last synced</th>
            <th class="px-4 py-2" />
          </tr>
        </thead>
        <tbody>
          <template v-for="repo in filed" :key="repo.id">
            <tr class="border-b border-gray-100">
              <td class="px-4 py-2 font-medium">{{ repo.full_name }}</td>
              <td class="px-4 py-2 text-gray-600">
                {{ deptName.get(repo.dept_id!) ?? `Department #${repo.dept_id}` }}
              </td>
              <td class="px-4 py-2 text-gray-600">{{ approverLabel(repo) }}</td>
              <td class="whitespace-nowrap px-4 py-2 text-gray-600">
                {{ formatDateTime(repo.last_synced_at) }}
              </td>
              <td class="whitespace-nowrap px-4 py-2 text-right">
                <button
                  v-if="canAdminRepo(repo)"
                  class="text-xs font-medium text-gray-600 hover:underline"
                  @click="editingRepoId === repo.id ? (editingRepoId = null) : startEditing(repo)"
                >
                  {{ editingRepoId === repo.id ? "Close" : "Change approvers" }}
                </button>
              </td>
            </tr>

            <tr v-if="editingRepoId === repo.id" class="border-b border-gray-100 bg-gray-50">
              <td colspan="5" class="px-4 py-4">
                <p v-if="candidatesPending" class="text-sm text-gray-500">Loading people…</p>
                <template v-else>
                  <p class="mb-3 text-xs text-gray-600">
                    Anyone whose commits, pull requests, reviews or issues appear in this
                    repository, plus whoever holds a post today. Both a lead and a deputy can
                    approve; they have to be different people.
                  </p>
                  <div class="flex flex-wrap items-end gap-3">
                    <div>
                      <label
                        :for="`lead-${repo.id}`"
                        class="mb-1 block text-xs font-medium text-gray-600"
                      >
                        Lead
                      </label>
                      <select
                        :id="`lead-${repo.id}`"
                        v-model="leadChoice"
                        class="w-64 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm"
                      >
                        <option :value="null">Nobody</option>
                        <option
                          v-for="person in candidates?.items ?? []"
                          :key="person.user_id"
                          :value="person.user_id"
                        >
                          {{ candidateLabel(person.user_id) }}
                        </option>
                      </select>
                    </div>
                    <div>
                      <label
                        :for="`deputy-${repo.id}`"
                        class="mb-1 block text-xs font-medium text-gray-600"
                      >
                        Deputy
                      </label>
                      <select
                        :id="`deputy-${repo.id}`"
                        v-model="deputyChoice"
                        class="w-64 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm"
                      >
                        <option :value="null">Nobody</option>
                        <option
                          v-for="person in candidates?.items ?? []"
                          :key="person.user_id"
                          :value="person.user_id"
                        >
                          {{ candidateLabel(person.user_id) }}
                        </option>
                      </select>
                    </div>
                    <button
                      :disabled="saveApprovers.isPending.value"
                      class="rounded-md bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-60"
                      @click="submitApprovers(repo)"
                    >
                      {{ saveApprovers.isPending.value ? "Saving…" : "Save approvers" }}
                    </button>
                  </div>
                  <p v-if="!(candidates?.items ?? []).length" class="mt-3 text-xs text-gray-500">
                    Nobody has activity in this repository yet, so there's nobody to name here.
                    A lead can still be set by user id through the API.
                  </p>
                  <p v-if="approverError" class="mt-3 text-sm text-red-600">{{ approverError }}</p>
                </template>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
  </div>
</template>
