<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import type { SelectOption } from "@crescent/ui/types/ui";
import type { ActivityResponse, JournalResponse, LatestRollupResponse, Page, RollupResponse } from "~/types/api";

definePageMeta({ middleware: "auth" });

/* What a repository is working on, in the words of the people doing it, plus an AI
   readout of the recent entries for whoever is catching up. Pulse has no per-repository
   screen, so the repository is chosen here and kept in the URL — a journal someone wants
   to point a colleague at has to be a link. */

const PER_PAGE = 20;
// services/pulse/app/schemas/journals.py: Field(min_length=1, max_length=10000).
const MAX_BODY = 10000;

const api = useApi();
const route = useRoute();
const router = useRouter();
const queryClient = useQueryClient();
const announce = useAnnounce();
const { show: showToast } = useToast();
const { me } = useMe();
const {
  repositories,
  isPending: reposPending,
  isError: reposFailed,
} = useRepositories();

const repoId = computed({
  get: () => (route.query.repo ? Number(route.query.repo) : null),
  set: (value) => patchQuery({ repo: value === null ? undefined : String(value), page: undefined }),
});
const page = computed({
  get: () => Math.max(0, Number(route.query.page ?? 0) || 0),
  set: (value) => patchQuery({ page: value === 0 ? undefined : String(value) }),
});

function patchQuery(patch: Record<string, string | undefined>) {
  router.replace({ query: { ...route.query, ...patch } });
}

const offset = computed(() => page.value * PER_PAGE);
const base = computed(() => `/github/repositories/${repoId.value}/journals`);
const chosen = computed(() => repoId.value !== null);

// A journal is repository-scoped, so a page with nothing chosen has nothing to show. The
// first visible repository is picked once the list arrives and written into the query
// string rather than held in a ref, so what is on screen is what the URL says.
watch(
  repositories,
  (list) => {
    if (repoId.value === null && list.length) repoId.value = list[0]!.id;
  },
  { immediate: true },
);

const repo = computed(() => repositories.value.find((r) => r.id === repoId.value) ?? null);

const repoOptions = computed<SelectOption[]>(() =>
  repositories.value.map((r) => ({ value: String(r.id), label: r.full_name })),
);

/* ── the feed ──────────────────────────────────────────────────────────────── */

const {
  data: feed,
  isPending: feedPending,
  isError: feedFailed,
  error: feedError,
} = useQuery({
  queryKey: computed(() => ["journals", repoId.value ?? "none", offset.value]),
  enabled: chosen,
  retry: false,
  queryFn: () =>
    api.request<Page<JournalResponse>>(base.value, { query: { limit: PER_PAGE, offset: offset.value } }),
});

const entries = computed(() => feed.value?.items ?? []);
const total = computed(() => feed.value?.total ?? 0);
const pages = computed(() => pageCount(total.value, PER_PAGE));

// The API answers 404, not 403, for a repository the caller cannot see, so that a URL
// cannot be used to confirm a private repository exists. This screen says the same
// thing back: not available to you, with no claim either way about what is behind it.
const outOfReach = computed(() => httpStatus(feedError.value) === 404);

/* ── who may write ─────────────────────────────────────────────────────────── */

/* Reading the feed does not carry the right to post to it: may_write_on_repo in
   services/pulse/app/services/repositories.py wants the lead, the deputy, an admin of
   the repository's department, or synced commits/pull requests/issues in it. The first
   three are decidable from data this page already holds. The fourth is not, so it is
   asked for once, only when the other three have said no — a composer that answers 403
   on every attempt is worse than one that is honestly not offered. */
const memberByPost = computed(() => {
  const user = me.value;
  const r = repo.value;
  if (!user || !r) return false;
  if (user.is_platform_admin) return true;
  if (user.id === r.lead_user_id || user.id === r.deputy_user_id) return true;
  return r.dept_id !== null && user.memberships.some((m) => m.dept_id === r.dept_id && m.role === "admin");
});

const { data: myWork, isError: probeFailed } = useQuery({
  queryKey: computed(() => ["activity", "journal-write", repoId.value ?? "none"]),
  enabled: computed(() => chosen.value && me.value !== null && !memberByPost.value),
  retry: false,
  queryFn: () => api.request<ActivityResponse>("/activity/me", { query: { repo_id: repoId.value } }),
});

// Set by a 403 the API actually returned, which outranks anything guessed from counts.
const postRefused = ref(false);

const mayWrite = computed<"yes" | "no" | "unknown">(() => {
  if (postRefused.value) return "no";
  if (memberByPost.value) return "yes";
  if (!chosen.value || me.value === null || probeFailed.value) return "unknown";
  const counts = myWork.value?.counts;
  if (!counts) return "unknown";
  // Reviews are deliberately absent: the API's predicate counts commits, pull requests
  // and issues only.
  return counts.commits + counts.pull_requests + counts.issues > 0 ? "yes" : "no";
});

/* ── writing ───────────────────────────────────────────────────────────────── */

const draft = ref("");
const composeError = ref<string | null>(null);

const remaining = computed(() => MAX_BODY - draft.value.length);
const overLong = computed(() => remaining.value < 0);
const nothingToPost = computed(() => draft.value.trim() === "");

// An attempt that has already been refused still leaves the box up while anything is
// typed in it. Swapping it for an explanation would take the entry with it.
const composerOpen = computed(() => mayWrite.value !== "no" || draft.value !== "");

const post = useMutation({
  mutationFn: () =>
    api.request<JournalResponse>(base.value, { method: "POST", body: { body: draft.value.trim() } }),
  onSuccess: () => {
    draft.value = "";
    composeError.value = null;
    postRefused.value = false;
    if (page.value !== 0) page.value = 0;
    // Same as the comment thread on /reports/[id]: post, then invalidate. The feed is
    // ordered and paged by the server, so a locally spliced row could sit in the wrong
    // place until the next fetch.
    queryClient.invalidateQueries({ queryKey: ["journals", repoId.value] });
    announce("Entry posted");
  },
  onError: (err) => {
    // The draft is deliberately untouched here.
    if (httpStatus(err) === 403) postRefused.value = true;
    composeError.value = apiMessage(err, "Could not post that entry.");
  },
});

const editingId = ref<number | null>(null);
const editingBody = ref("");
const entryError = ref<string | null>(null);

function startEdit(entry: JournalResponse) {
  editingId.value = entry.id;
  editingBody.value = entry.body;
  entryError.value = null;
}

const saveEdit = useMutation({
  mutationFn: (entryId: number) =>
    api.request<JournalResponse>(`${base.value}/${entryId}`, {
      method: "PATCH",
      body: { body: editingBody.value.trim() },
    }),
  onSuccess: () => {
    editingId.value = null;
    entryError.value = null;
    queryClient.invalidateQueries({ queryKey: ["journals", repoId.value] });
    announce("Entry saved");
  },
  onError: (err) => {
    entryError.value =
      httpStatus(err) === 403
        ? "Only the person who wrote an entry can change it. Nothing was saved."
        : apiMessage(err, "Could not save that entry.");
  },
});

const confirmDelete = ref<JournalResponse | null>(null);

const remove = useMutation({
  mutationFn: (entryId: number) => api.request<void>(`${base.value}/${entryId}`, { method: "DELETE" }),
  onSuccess: () => {
    confirmDelete.value = null;
    queryClient.invalidateQueries({ queryKey: ["journals", repoId.value] });
    announce("Entry deleted");
    showToast("Entry deleted.", "muted");
  },
  onError: (err) => {
    confirmDelete.value = null;
    entryError.value =
      httpStatus(err) === 403
        ? "Only the person who wrote an entry can delete it. It is still there."
        : apiMessage(err, "Could not delete that entry.");
  },
});

/* ── the rollup ────────────────────────────────────────────────────────────── */

/* Never generated is `rollup: null` inside a 200, so the empty state is an answer rather
   than a caught error. A 404 here means only one thing now — the repository is not
   visible to you — which is the same verdict the feed query above reaches, and that one
   decides what the whole screen says. */
const {
  data: rollupEnvelope,
  isPending: rollupPending,
  isError: rollupFailed,
  error: rollupQueryError,
} = useQuery({
  queryKey: computed(() => ["journal-rollup", repoId.value ?? "none"]),
  enabled: chosen,
  retry: false,
  queryFn: () => api.request<LatestRollupResponse>(`${base.value}/rollup`),
});

const rollup = computed(() => rollupEnvelope.value?.rollup ?? null);
const rollupOutOfReach = computed(() => httpStatus(rollupQueryError.value) === 404);

const rollupError = ref<string | null>(null);

const generate = useMutation({
  mutationFn: () => api.request<RollupResponse>(`${base.value}/rollup`, { method: "POST" }),
  onSuccess: (created) => {
    rollupError.value = null;
    queryClient.setQueryData<LatestRollupResponse>(["journal-rollup", repoId.value ?? "none"], { rollup: created });
    announce("Progress rollup generated");
  },
  onError: (err) => {
    const code = httpStatus(err);
    if (code === 403) postRefused.value = true;
    rollupError.value =
      code === 422
        ? "There is nothing to summarise yet — this journal has no entries. Write the first one and the rollup has something to read."
        : code === 429
          /* Two different refusals share this status. The daily allowance arrives as a
             FastAPI `detail` and is the server's own wording, which says who is paying
             and when it resets; the ten-an-hour limit is slowapi's and carries no
             `detail` at all, so it falls through to the sentence below. */
          ? apiMessage(err, "That is ten rollups in an hour, which is the limit. The entries are untouched; the next rollup can be asked for once the hour is up.")
          : code === 502
            ? "The AI service did not answer, so no rollup was written. Nothing in the journal changed."
            : apiMessage(err, "Could not generate a rollup.");
  },
});

// Announced together, because the pair is the whole answer to "is this feed worth reading".
watch([total, repoId], () => {
  if (!chosen.value || feedPending.value) return;
  announce(`${total.value} journal entries in ${repo.value?.full_name ?? "this repository"}`);
});

// A repository swap is a different feed, a different rollup and a different verdict on
// writing, so nothing from the last one may survive it.
watch(repoId, () => {
  editingId.value = null;
  confirmDelete.value = null;
  entryError.value = null;
  composeError.value = null;
  rollupError.value = null;
  postRefused.value = false;
});
</script>

<template>
  <PulseShell :readout="chosen ? `${total} entries` : 'journal'">
    <header class="sec flex flex-wrap items-end justify-between gap-4">
      <div class="min-w-0">
        <Eyebrow>Pulse · journal</Eyebrow>
        <h1 class="mt-3 text-[clamp(1.5rem,2.2vw,1.9rem)] font-semibold leading-[1.05] tracking-[-0.035em]">
          Repository journal
        </h1>
        <p class="mt-1.5 max-w-[68ch] text-[12.5px] leading-relaxed text-ink-muted">
          What is being worked on and what is in the way, written by hand. Everyone who can see the
          repository reads the feed; posting to it needs membership of the repository.
        </p>
      </div>
      <p class="mono flex shrink-0 items-center gap-2 rounded-md bg-sunken px-2.5 py-2 text-[12px] ring-1 ring-inset ring-line-subtle">
        <span :class="[MONO_LABEL, 'text-ink-faint']">get</span>
        <span class="text-ink">{{ chosen ? base : "/github/repositories/…/journals" }}</span>
        <span class="hidden text-ink-muted sm:inline">?limit={{ PER_PAGE }}&offset={{ offset }}</span>
      </p>
    </header>

    <section class="sec mt-6 flex flex-wrap items-center gap-3" style="animation-delay: 40ms" aria-label="Choose a repository">
      <Select
        class="w-[320px]"
        label="Repository"
        placeholder="Choose a repository"
        :disabled="!repositories.length"
        :model-value="repoId === null ? '' : String(repoId)"
        :options="repoOptions"
        @update:model-value="repoId = Number($event)"
      />
      <p v-if="reposPending" class="text-[12px] text-ink-muted">Reading your repositories…</p>
      <p v-else-if="reposFailed" role="alert" class="text-[12px] text-ink-muted">
        The repository list did not come back, so there is nothing to choose from. Everything below
        waits on it.
      </p>
      <p v-else-if="!repositories.length" class="text-[12px] text-ink-muted">
        No repositories are visible to you yet, so there is no journal to read.
      </p>
    </section>

    <div
      v-if="feedFailed && outOfReach"
      class="sec mt-8 rounded-md bg-surface/40 px-5 py-10 ring-1 ring-inset ring-line-subtle"
      style="animation-delay: 80ms"
    >
      <h2 class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">This journal is not available to you</h2>
      <p class="mt-1.5 max-w-[58ch] text-[12.5px] leading-relaxed text-ink-muted">
        The picker above only offers repositories you can see, so a repository id typed into the
        address bar usually lands here. Choose one from the list.
      </p>
    </div>

    <p
      v-else-if="feedFailed"
      role="alert"
      class="mt-8 max-w-[74ch] rounded-md bg-bad-surface px-4 py-3 text-[12.5px] leading-relaxed text-ink"
    >
      {{ apiMessage(feedError, "Could not reach the Pulse API. Check that the service is running.") }}
    </p>

    <template v-else-if="chosen">
      <!-- The rollup reads the journal; it never replaces it, so it sits above the entries
           rather than in place of them. -->
      <section
        class="sec mt-8 rounded-md bg-surface/40 px-5 py-5 ring-1 ring-inset ring-line-subtle"
        style="animation-delay: 80ms"
        aria-labelledby="rollup-heading"
      >
        <div class="flex flex-wrap items-baseline justify-between gap-3">
          <h2 id="rollup-heading" class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">Progress rollup</h2>
          <p v-if="rollup" class="mono text-[12px] text-ink-muted">
            {{ rollup.entry_count }} {{ rollup.entry_count === 1 ? "entry" : "entries" }} ·
            {{ formatDateTime(rollup.created_at) }} ·
            {{ personName(rollup.generated_by, rollup.generated_by_user_id) }}
            <template v-if="rollup.model"> · {{ rollup.model }}</template>
          </p>
        </div>

        <p v-if="rollupPending" class="mt-3 text-[12.5px] text-ink-muted">Looking for a rollup…</p>

        <p v-else-if="rollupFailed && rollupOutOfReach" data-test="rollup-out-of-reach" class="mt-3 max-w-[70ch] text-[12.5px] leading-relaxed text-ink-muted">
          This repository is not available to you, so there is no rollup to read. Choose one from
          the picker above.
        </p>

        <p v-else-if="rollupFailed" data-test="rollup-unreadable" class="mt-3 max-w-[70ch] text-[12.5px] leading-relaxed text-ink-muted">
          The last rollup could not be read. The entries below are a separate request and are
          unaffected.
        </p>

        <template v-else-if="rollup">
          <p class="mt-3 max-w-[80ch] whitespace-pre-wrap text-[13px] leading-relaxed text-ink">
            {{ rollup.summary }}
          </p>
          <p v-if="rollup.covers_from" class="mono mt-3 text-[12px] text-ink-muted">
            covers {{ formatStamp(rollup.covers_from) }} → {{ formatStamp(rollup.covers_to) }}
          </p>
        </template>

        <template v-else>
          <p class="mt-3 max-w-[70ch] text-[12.5px] leading-relaxed text-ink-muted">
            No rollup has been written for this repository yet. One reads the recent entries and
            turns them into a readout for somebody catching up.
          </p>
        </template>

        <div class="mt-4 flex flex-wrap items-center gap-3">
          <Btn
            size="sm"
            variant="secondary"
            data-test="rollup-generate"
            :disabled="mayWrite === 'no'"
            :busy="generate.isPending.value"
            @click="generate.mutate()"
          >
            {{ rollup ? "Regenerate" : "Generate a rollup" }}
          </Btn>
          <p v-if="mayWrite === 'no'" class="max-w-[52ch] text-[12px] leading-relaxed text-ink-muted">
            Asking for a rollup needs the same membership as posting, so this one is read-only for
            you.
          </p>
          <p v-else class="mono text-[12px] text-ink-faint">up to 10 an hour</p>
        </div>

        <p
          v-if="rollupError"
          role="alert"
          data-test="rollup-error"
          class="mt-3 max-w-[70ch] rounded-md bg-bad-surface px-3.5 py-2.5 text-[12.5px] leading-relaxed text-ink"
        >
          {{ rollupError }}
        </p>
      </section>

      <!-- Writing. -->
      <section class="sec mt-8" style="animation-delay: 100ms" aria-labelledby="compose-heading">
        <h2 id="compose-heading" class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">New entry</h2>

        <template v-if="composerOpen">
          <label for="journal-body" class="mt-2 block text-[12px] text-ink-muted">
            What you are working on, and what is in the way
          </label>
          <textarea
            id="journal-body"
            v-model="draft"
            rows="4"
            data-test="composer"
            :maxlength="MAX_BODY"
            :class="[FOCUS, 'mt-1.5 w-full resize-y rounded-md bg-sunken px-3 py-2.5 text-[12.5px] leading-relaxed text-ink ring-1 ring-inset ring-line transition-colors placeholder:text-ink-faint hover:ring-line-strong']"
          />
          <div class="mt-2 flex flex-wrap items-center gap-3">
            <Btn
              size="sm"
              data-test="composer-post"
              :disabled="nothingToPost || overLong"
              :busy="post.isPending.value"
              @click="post.mutate()"
            >Post entry</Btn>
            <!-- The count is chrome until it is nearly news: 10,000 characters is far
                 past what anyone writes here, so a running total all the way down would
                 only ever be noise. -->
            <span
              data-test="composer-count"
              :class="[
                'mono text-[12px]',
                overLong ? 'text-bad' : remaining <= 200 ? 'text-warn' : 'text-ink-faint',
              ]"
            >
              <template v-if="remaining <= 500">{{ remaining }} characters left</template>
              <template v-else>{{ draft.length }} / {{ MAX_BODY }}</template>
            </span>
            <p v-if="mayWrite === 'unknown'" class="text-[12.5px] leading-relaxed text-ink-muted">
              Whether you can post here is settled by the API when you do.
            </p>
          </div>

          <p
            v-if="composeError"
            role="alert"
            data-test="composer-error"
            class="mt-2 max-w-[70ch] rounded-md bg-bad-surface px-3.5 py-2.5 text-[12.5px] leading-relaxed text-ink"
          >
            {{ composeError }}
            <template v-if="postRefused">
              Your entry is still in the box above — copy it somewhere safe before leaving this
              page.
            </template>
          </p>
        </template>

        <p v-else data-test="read-only" class="mt-2 max-w-[70ch] text-[12.5px] leading-relaxed text-ink-muted">
          You can read this journal but not write to it. Posting is for members of the repository:
          its lead, its deputy, an admin of its department, or anyone with synced GitHub work in it.
        </p>
      </section>

      <!-- The feed. -->
      <section class="sec mt-8" style="animation-delay: 120ms" aria-labelledby="entries-heading">
        <div class="flex items-baseline justify-between gap-3 border-b border-line-subtle pb-2">
          <h2 id="entries-heading" class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">Entries</h2>
          <p class="mono text-[12px] text-ink-muted">newest first</p>
        </div>

        <p v-if="entryError" role="alert" data-test="entry-error" class="mt-3 max-w-[70ch] rounded-md bg-bad-surface px-3.5 py-2.5 text-[12.5px] leading-relaxed text-ink">
          {{ entryError }}
        </p>

        <p v-if="feedPending" class="mt-4 text-[12.5px] text-ink-muted">Reading the journal…</p>

        <div v-else-if="!entries.length" class="mt-4 rounded-md bg-surface/40 px-5 py-8 ring-1 ring-inset ring-line-subtle">
          <p class="text-[13.5px] font-medium text-ink">Nothing written yet</p>
          <p class="mt-1.5 max-w-[58ch] text-[12.5px] leading-relaxed text-ink-muted">
            A journal entry is a couple of sentences on what you are doing and what is holding it
            up. The first one gives everyone else something to read.
          </p>
        </div>

        <ul v-else data-test="feed" class="mt-1 divide-y divide-line-subtle">
          <li v-for="entry in entries" :key="entry.id" class="py-4" data-test="entry">
            <p class="flex flex-wrap items-baseline gap-2 text-[12px] text-ink-muted">
              <Avatar :name="personName(entry.author, entry.author_user_id)" size="sm" />
              <span class="text-ink">{{ personName(entry.author, entry.author_user_id) }}</span>
              <span v-if="entry.author_user_id === me?.id">(you)</span>
              <span class="mono text-[12px]">{{ formatDateTime(entry.created_at) }}</span>
              <span v-if="entry.edited_at" class="mono text-[12px]" data-test="edited">
                (edited {{ relativeTime(entry.edited_at) }})
              </span>
            </p>

            <template v-if="editingId === entry.id">
              <label class="sr-only" :for="`entry-${entry.id}`">Edit your entry</label>
              <textarea
                :id="`entry-${entry.id}`"
                v-model="editingBody"
                rows="4"
                :maxlength="MAX_BODY"
                data-test="entry-editor"
                :class="[FOCUS, 'mt-2 w-full resize-y rounded-md bg-sunken px-3 py-2.5 text-[12.5px] leading-relaxed text-ink ring-1 ring-inset ring-line hover:ring-line-strong']"
              />
              <div class="mt-2 flex gap-2">
                <Btn
                  size="sm"
                  data-test="entry-save"
                  :disabled="editingBody.trim() === ''"
                  :busy="saveEdit.isPending.value"
                  @click="saveEdit.mutate(entry.id)"
                >Save</Btn>
                <Btn size="sm" variant="ghost" @click="editingId = null">Cancel</Btn>
              </div>
            </template>

            <template v-else>
              <!-- Interpolated, never v-html: an entry is whatever somebody typed. -->
              <p class="mt-1.5 max-w-[80ch] whitespace-pre-wrap text-[13px] leading-relaxed text-ink">
                {{ entry.body }}
              </p>
              <div v-if="entry.author_user_id === me?.id" class="mt-2 flex gap-3">
                <button
                  type="button"
                  data-test="entry-edit"
                  :class="[FOCUS, 'rounded text-[12.5px] text-ink-muted transition-colors hover:text-ink']"
                  @click="startEdit(entry)"
                >Edit</button>
                <button
                  type="button"
                  data-test="entry-delete"
                  :class="[FOCUS, 'rounded text-[12.5px] text-bad transition-colors hover:brightness-110']"
                  @click="confirmDelete = entry"
                >Delete</button>
              </div>
            </template>
          </li>
        </ul>

        <div v-if="total > PER_PAGE" class="mt-4 flex flex-wrap items-center gap-3 border-t border-line-subtle pt-3">
          <p class="mono text-[12px] text-ink-muted">
            {{ offset + 1 }}–{{ Math.min(offset + PER_PAGE, total) }} of {{ total }}
          </p>
          <div class="ml-auto flex items-center gap-1.5">
            <button
              type="button"
              data-test="page-newer"
              :disabled="page === 0"
              :class="[FOCUS, DISABLED, 'rounded-md px-2.5 py-1.5 text-[12px] text-ink-muted ring-1 ring-inset ring-line-subtle transition-colors enabled:hover:bg-surface-hover enabled:hover:text-ink']"
              @click="page = Math.max(0, page - 1)"
            >Newer</button>
            <span class="mono px-1 text-[12px] text-ink-muted">page {{ page + 1 }} of {{ pages }}</span>
            <button
              type="button"
              data-test="page-older"
              :disabled="page + 1 >= pages"
              :class="[FOCUS, DISABLED, 'rounded-md px-2.5 py-1.5 text-[12px] text-ink-muted ring-1 ring-inset ring-line-subtle transition-colors enabled:hover:bg-surface-hover enabled:hover:text-ink']"
              @click="page = page + 1"
            >Older</button>
          </div>
        </div>
      </section>
    </template>

    <Modal
      :open="confirmDelete !== null"
      title="Delete this entry?"
      description="Everyone who can see this repository has been able to read it. Deleting cannot be undone."
      :close-on-backdrop="false"
      @close="confirmDelete = null"
    >
      <p class="max-w-[42ch] whitespace-pre-wrap text-[12.5px] leading-relaxed text-ink-muted">
        {{ confirmDelete?.body }}
      </p>
      <template #footer>
        <Btn size="sm" variant="ghost" @click="confirmDelete = null">Keep it</Btn>
        <Btn
          size="sm"
          variant="destructive"
          data-test="delete-confirm"
          :busy="remove.isPending.value"
          @click="confirmDelete && remove.mutate(confirmDelete.id)"
        >Delete entry</Btn>
      </template>
    </Modal>
  </PulseShell>
</template>
