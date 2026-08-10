<script setup lang="ts">
import { useQuery, useMutation, useQueryClient } from "@tanstack/vue-query";
import type {
  ApprovalResponse,
  CommentResponse,
  Page,
  ReportResponse,
  UserMeResponse,
} from "~/types/api";

definePageMeta({ middleware: "auth" });

const route = useRoute();
const auth = useAuth();
const api = useApi();
const config = useRuntimeConfig();
const queryClient = useQueryClient();
const { repositories, repoName } = useRepositories();

const id = computed(() => route.params.id as string);

const {
  data: report,
  isPending,
  isError,
  error,
} = useQuery({
  queryKey: computed(() => ["report", id.value]),
  queryFn: () => api.request<ReportResponse>(`/reports/${id.value}`),
  retry: false,
});

const { data: approvals } = useQuery({
  queryKey: computed(() => ["report", id.value, "approvals"]),
  enabled: computed(() => !!report.value),
  queryFn: () => api.request<Page<ApprovalResponse>>(`/reports/${id.value}/approvals`, {
    query: { limit: 100 },
  }),
});

const { data: comments } = useQuery({
  queryKey: computed(() => ["report", id.value, "comments"]),
  enabled: computed(() => !!report.value),
  queryFn: () => api.request<Page<CommentResponse>>(`/reports/${id.value}/comments`, {
    query: { limit: 100 },
  }),
});

const notFound = computed(() => {
  const status = httpStatus(error.value);
  return status === 403 || status === 404;
});

const me = computed(() => auth.user.value as UserMeResponse | null);
const isAuthor = computed(() => !!report.value && report.value.author_user_id === me.value?.id);
const isEditable = computed(
  () => !!report.value && ["draft", "changes_requested"].includes(report.value.status),
);
const repo = computed(() =>
  repositories.value.find((r) => r.id === report.value?.repo_id) ?? null,
);

// Mirrors the API's _can_approve: platform admin, the repo's lead or deputy, or an
// admin of the report's department. Getting it wrong only shows or hides buttons —
// the API decides.
const canApprove = computed(() => {
  const r = report.value;
  const user = me.value;
  if (!r || !user) return false;
  if (user.is_platform_admin) return true;
  if (repo.value && (repo.value.lead_user_id === user.id || repo.value.deputy_user_id === user.id)) {
    return true;
  }
  return (
    r.dept_id !== null &&
    (user.memberships ?? []).some((m) => m.dept_id === r.dept_id && m.role === "admin")
  );
});

const editing = ref(false);
const draft = reactive({ summary_manager: "", summary_exec: "", next_week_goals: "" });
const actionError = ref<string | null>(null);

function seedDraft() {
  const r = report.value;
  if (!r) return;
  draft.summary_manager = r.summary_manager ?? "";
  draft.summary_exec = r.summary_exec ?? "";
  draft.next_week_goals = r.next_week_goals ?? "";
}

watch(report, seedDraft, { immediate: true });

const save = useMutation({
  mutationFn: () =>
    api.request<ReportResponse>(`/reports/${id.value}`, { method: "PATCH", body: { ...draft } }),
  onSuccess: (updated) => {
    queryClient.setQueryData(["report", id.value], updated);
    queryClient.invalidateQueries({ queryKey: ["reports"] });
    editing.value = false;
  },
  onError: (err) => {
    actionError.value = apiMessage(err, "Could not save your changes.");
  },
});

const submit = useMutation({
  mutationFn: async () => {
    // Submitting with unsaved text in the boxes would quietly send the old version.
    if (editing.value) {
      await api.request<ReportResponse>(`/reports/${id.value}`, {
        method: "PATCH",
        body: { ...draft },
      });
    }
    return api.request<ReportResponse>(`/reports/${id.value}/submit`, { method: "POST" });
  },
  onSuccess: (updated) => {
    queryClient.setQueryData(["report", id.value], updated);
    queryClient.invalidateQueries({ queryKey: ["reports"] });
    queryClient.invalidateQueries({ queryKey: ["report", id.value, "approvals"] });
    queryClient.invalidateQueries({ queryKey: ["review-queue"] });
    editing.value = false;
  },
  onError: (err) => {
    actionError.value = apiMessage(err, "Could not submit this report.");
  },
});

const newComment = ref("");
const commentError = ref<string | null>(null);

const addComment = useMutation({
  mutationFn: () =>
    api.request<CommentResponse>(`/reports/${id.value}/comments`, {
      method: "POST",
      body: { body: newComment.value.trim() },
    }),
  onSuccess: () => {
    newComment.value = "";
    queryClient.invalidateQueries({ queryKey: ["report", id.value, "comments"] });
  },
  onError: (err) => {
    commentError.value = apiMessage(err, "Could not post that comment.");
  },
});

const editingCommentId = ref<number | null>(null);
const editingCommentBody = ref("");

const updateComment = useMutation({
  mutationFn: (commentId: number) =>
    api.request<CommentResponse>(`/reports/${id.value}/comments/${commentId}`, {
      method: "PATCH",
      body: { body: editingCommentBody.value.trim() },
    }),
  onSuccess: () => {
    editingCommentId.value = null;
    queryClient.invalidateQueries({ queryKey: ["report", id.value, "comments"] });
  },
  onError: (err) => {
    commentError.value = apiMessage(err, "Could not save that comment.");
  },
});

const removeComment = useMutation({
  mutationFn: (commentId: number) =>
    api.request<void>(`/reports/${id.value}/comments/${commentId}`, { method: "DELETE" }),
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: ["report", id.value, "comments"] });
  },
  onError: (err) => {
    commentError.value = apiMessage(err, "Could not delete that comment.");
  },
});

function startCommentEdit(comment: CommentResponse) {
  editingCommentId.value = comment.id;
  editingCommentBody.value = comment.body;
  commentError.value = null;
}

const pdfError = ref<string | null>(null);
const pdfLoading = ref(false);

// The PDF endpoint needs the bearer token, so it can't be a plain <a href>.
async function openPdf() {
  pdfError.value = null;
  pdfLoading.value = true;
  try {
    const blob = await $fetch<Blob>(`${config.public.pulseUrl}/reports/${id.value}/pdf`, {
      responseType: "blob",
      headers: { Authorization: `Bearer ${auth.accessToken.value}` },
    });
    window.open(URL.createObjectURL(blob), "_blank", "noopener");
  } catch (err: unknown) {
    pdfError.value = apiMessage(err, "Could not build the PDF.");
  } finally {
    pdfLoading.value = false;
  }
}

const SECTIONS = [
  { key: "summary_manager", label: "Summary for your manager" },
  { key: "summary_exec", label: "Summary for the executive" },
  { key: "next_week_goals", label: "Next week's goals" },
] as const;

function sectionValue(r: ReportResponse, key: (typeof SECTIONS)[number]["key"]): string | null {
  return r[key];
}
</script>

<template>
  <div class="mx-auto max-w-4xl px-4 py-8">
    <header class="mb-6">
      <NuxtLink to="/reports" class="text-sm text-gray-500 hover:underline">
        &larr; Back to reports
      </NuxtLink>
    </header>

    <p v-if="isPending" class="text-sm text-gray-500">Loading report…</p>

    <div v-else-if="notFound" class="rounded-lg border border-gray-200 bg-white p-6">
      <p class="text-sm font-medium">This report isn't available to you.</p>
      <p class="mt-1 text-sm text-gray-500">
        It may have been deleted, or you may not be its author, its repository's lead or
        deputy, or an admin of its department.
      </p>
    </div>

    <p v-else-if="isError" class="text-sm text-red-600">
      {{ apiMessage(error, "Could not load this report.") }}
    </p>

    <template v-else-if="report">
      <div class="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 class="text-2xl font-semibold">Week of {{ formatDate(report.week_start) }}</h1>
          <p class="mt-1 text-sm text-gray-500">
            {{ repoName(report.repo_id) }} ·
            {{ personName(report.author, report.author_user_id) }}
          </p>
          <p v-if="report.generated_at" class="mt-1 text-xs text-gray-500">
            Drafted by AI on {{ formatDateTime(report.generated_at) }}
            <template v-if="report.prompt_version">({{ report.prompt_version }})</template>
          </p>
        </div>
        <span
          class="rounded-full px-3 py-1 text-xs font-medium"
          :class="statusClass(report.status)"
        >
          {{ statusLabel(report.status) }}
        </span>
      </div>

      <div class="mb-6 flex flex-wrap gap-2">
        <template v-if="isAuthor && isEditable">
          <button
            v-if="!editing"
            class="rounded-md border border-gray-300 px-3 py-2 text-sm font-medium hover:bg-gray-100"
            @click="editing = true; actionError = null"
          >
            Edit
          </button>
          <template v-else>
            <button
              :disabled="save.isPending.value"
              class="rounded-md border border-gray-300 px-3 py-2 text-sm font-medium hover:bg-gray-100 disabled:opacity-60"
              @click="save.mutate()"
            >
              {{ save.isPending.value ? "Saving…" : "Save draft" }}
            </button>
            <button
              class="rounded-md px-3 py-2 text-sm font-medium text-gray-600 hover:bg-gray-100"
              @click="editing = false; seedDraft(); actionError = null"
            >
              Cancel
            </button>
          </template>
          <button
            :disabled="submit.isPending.value"
            class="rounded-md bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-60"
            @click="submit.mutate()"
          >
            {{ submit.isPending.value ? "Submitting…" : "Submit for review" }}
          </button>
        </template>

        <button
          :disabled="pdfLoading"
          class="rounded-md border border-gray-300 px-3 py-2 text-sm font-medium hover:bg-gray-100 disabled:opacity-60"
          @click="openPdf"
        >
          {{ pdfLoading ? "Building PDF…" : "Download PDF" }}
        </button>
      </div>

      <p v-if="actionError" class="mb-4 text-sm text-red-600">{{ actionError }}</p>
      <p v-if="pdfError" class="mb-4 text-sm text-red-600">{{ pdfError }}</p>

      <p
        v-if="isAuthor && !isEditable"
        class="mb-6 rounded-md border border-gray-200 bg-white px-4 py-3 text-sm text-gray-500"
      >
        This report is {{ statusLabel(report.status).toLowerCase() }} — it can't be edited.
        It stays on the record as it was reviewed.
      </p>

      <section class="mb-8 space-y-4">
        <div
          v-for="section in SECTIONS"
          :key="section.key"
          class="rounded-lg border border-gray-200 bg-white p-5"
        >
          <h2 class="mb-2 text-sm font-semibold">{{ section.label }}</h2>
          <textarea
            v-if="editing"
            v-model="draft[section.key]"
            rows="6"
            class="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-gray-500 focus:outline-none"
          />
          <p
            v-else-if="sectionValue(report, section.key)"
            class="whitespace-pre-wrap text-sm text-gray-700"
          >
            {{ sectionValue(report, section.key) }}
          </p>
          <p v-else class="text-sm text-gray-400">Not written yet.</p>
        </div>
      </section>

      <section
        v-if="canApprove && report.status === 'submitted'"
        class="mb-8 rounded-lg border border-gray-200 bg-white p-5"
      >
        <h2 class="mb-3 text-sm font-semibold">Your decision</h2>
        <ReportDecision :report-id="report.id" />
      </section>

      <section class="mb-8 rounded-lg border border-gray-200 bg-white p-5">
        <h2 class="mb-3 text-sm font-semibold">Approval history</h2>
        <p v-if="!approvals || !approvals.items.length" class="text-sm text-gray-500">
          Nothing yet — this report hasn't been submitted for review.
        </p>
        <ul v-else class="space-y-3">
          <li v-for="entry in approvals.items" :key="entry.id" class="text-sm">
            <p>
              <span class="font-medium">{{ personName(entry.actor, entry.actor_user_id) }}</span>
              {{ actionLabel(entry.action) }}
              <span class="text-gray-500">· {{ formatDateTime(entry.created_at) }}</span>
            </p>
            <p v-if="entry.note" class="mt-1 whitespace-pre-wrap text-gray-600">{{ entry.note }}</p>
          </li>
        </ul>
      </section>

      <section class="rounded-lg border border-gray-200 bg-white p-5">
        <h2 class="mb-3 text-sm font-semibold">Comments</h2>

        <p v-if="!comments || !comments.items.length" class="text-sm text-gray-500">
          No comments yet.
        </p>
        <ul v-else class="mb-5 space-y-4">
          <li v-for="comment in comments.items" :key="comment.id" class="text-sm">
            <p class="text-gray-500">
              <span class="font-medium text-gray-900">
                {{ personName(comment.author, comment.author_user_id) }}
              </span>
              · {{ formatDateTime(comment.created_at) }}
              <span v-if="comment.edited_at" class="text-gray-400">(edited)</span>
            </p>

            <template v-if="editingCommentId === comment.id">
              <textarea
                v-model="editingCommentBody"
                rows="3"
                class="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-gray-500 focus:outline-none"
              />
              <div class="mt-2 flex gap-2">
                <button
                  :disabled="updateComment.isPending.value"
                  class="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium hover:bg-gray-100 disabled:opacity-60"
                  @click="updateComment.mutate(comment.id)"
                >
                  Save
                </button>
                <button
                  class="rounded-md px-3 py-1.5 text-sm font-medium text-gray-600 hover:bg-gray-100"
                  @click="editingCommentId = null"
                >
                  Cancel
                </button>
              </div>
            </template>

            <template v-else>
              <p class="mt-1 whitespace-pre-wrap text-gray-700">{{ comment.body }}</p>
              <div v-if="comment.author_user_id === me?.id" class="mt-1 flex gap-3">
                <button
                  class="text-xs font-medium text-gray-500 hover:underline"
                  @click="startCommentEdit(comment)"
                >
                  Edit
                </button>
                <button
                  class="text-xs font-medium text-red-600 hover:underline"
                  @click="removeComment.mutate(comment.id)"
                >
                  Delete
                </button>
              </div>
            </template>
          </li>
        </ul>

        <label for="new-comment" class="mb-1 block text-xs font-medium text-gray-600">
          Add a comment
        </label>
        <textarea
          id="new-comment"
          v-model="newComment"
          rows="3"
          class="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-gray-500 focus:outline-none"
        />
        <button
          :disabled="!newComment.trim() || addComment.isPending.value"
          class="mt-2 rounded-md bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-60"
          @click="addComment.mutate()"
        >
          {{ addComment.isPending.value ? "Posting…" : "Post comment" }}
        </button>
        <p v-if="commentError" class="mt-2 text-sm text-red-600">{{ commentError }}</p>
      </section>
    </template>
  </div>
</template>
