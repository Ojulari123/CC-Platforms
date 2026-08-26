<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import type {
  ChatMessage,
  Conversation,
  ConversationDetail,
  GitHubIndexStatus,
  IndexedRepo,
  Page,
} from "~/types/api";

definePageMeta({ middleware: "auth" });

/* Questions about the code, answered from the code. A repository is indexed once — read,
   chunked and embedded at one commit — and every answer cites the file and lines it came
   from, so the reply can be checked rather than believed.

   Two things share the screen. The conversation is the product; the index is the pantry.
   The index therefore sits in a column beside the thread rather than in front of it, and
   is only allowed to take the whole screen when there is nothing indexed at all. */

const REPO_LIMIT = 100;
const CONVERSATION_LIMIT = 50;
// services/pulse/app/schemas/chat.py is the authority; this is the shape of a question,
// not a hard API limit, and only stops somebody pasting a whole file into the box.
const MAX_QUESTION = 4000;

const api = useApi();
const route = useRoute();
const router = useRouter();
const queryClient = useQueryClient();
const announce = useAnnounce();
const { show: showToast } = useToast();

const conversationId = computed({
  get: () => (route.query.c ? Number(route.query.c) : null),
  set: (value) => router.replace({ query: { ...route.query, c: value === null ? undefined : String(value) } }),
});

/* ── the index ─────────────────────────────────────────────────────────────── */

/* Whether anything is still being indexed, and so whether the list has to keep asking.
   A ref written by a watcher rather than a computed over the query's own data, because
   vue-query reads its options through `cloneDeepUnref` at setup — a computed declared
   after the query it configures would be read before it exists. */
const settling = ref(false);

const {
  data: repoPage,
  isPending: reposPending,
  isError: reposFailed,
} = useQuery({
  queryKey: ["chat-repos"],
  retry: false,
  /* Passed as a ref, not a closure. The options are unwrapped inside a computed, so a
     plain `() => settling.value ? …` would never be re-evaluated when the last job
     lands, and the poll would run for as long as the tab is open. */
  refetchInterval: computed<number | false>(() => (settling.value ? REPO_POLL_MS : false)),
  queryFn: () => api.request<Page<IndexedRepo>>("/chat/repos", { query: { limit: REPO_LIMIT, offset: 0 } }),
});

const repos = computed(() => repoPage.value?.items ?? []);
const readyRepos = computed(() => repos.value.filter((r) => r.status === "ready"));

watch(repos, (list) => {
  settling.value = list.some(isSettling);
});

// A failure here is not a failure of the whole panel: public repositories can be indexed
// whether or not GitHub is connected, so this only ever adds a notice.
const { data: githubStatus } = useQuery({
  queryKey: ["chat-github-status"],
  retry: false,
  queryFn: () => api.request<GitHubIndexStatus>("/chat/repos/github-status"),
});

/* Two states keep private repositories out of the index, and they need different offers.
   Nothing connected at all is a first connection. A connection too narrow to read private
   files is a reconnect, and the server marks that one itself with `reconnect_required` and
   writes the explanation into `detail` — both are read off the response rather than
   inferred, so a reworded sentence upstream cannot break this. */
const notConnected = computed(() => githubStatus.value?.connected === false);
const needsReconnect = computed(() => githubStatus.value?.reconnect_required === true);
const githubInTheWay = computed(() => notConnected.value || needsReconnect.value);
const reconnectDetail = computed(() => githubStatus.value?.detail ?? null);

const repoInput = ref("");
const repoInputEl = ref<HTMLInputElement | null>(null);
const repoError = ref<string | null>(null);

const candidate = computed(() => normalizeRepoInput(repoInput.value));
const candidateOk = computed(() => isFullName(candidate.value));

const addRepo = useMutation({
  mutationFn: (fullName: string) =>
    api.request<IndexedRepo>("/chat/repos", { method: "POST", body: { full_name: fullName } }),
  onSuccess: (queued) => {
    repoInput.value = "";
    repoError.value = null;
    // 202: queued, not indexed. The row appears at `pending` and the list polls it in.
    queryClient.invalidateQueries({ queryKey: ["chat-repos"] });
    showToast(`${queued.full_name} queued for indexing.`, "info");
  },
  onError: (err) => {
    repoError.value = apiMessage(err, "Could not queue that repository for indexing.");
  },
});

function submitRepo() {
  if (!candidateOk.value) {
    repoError.value = repoInput.value.trim()
      ? "A repository is written owner/name — acme/pulse-api. A GitHub URL works too; anything else does not."
      : "Type the repository as owner/name, for example acme/pulse-api.";
    return;
  }
  repoError.value = null;
  addRepo.mutate(candidate.value);
}

const indexMine = useMutation({
  mutationFn: () => api.request<{ queued: number }>("/chat/repos/mine", { method: "POST" }),
  onSuccess: ({ queued }) => {
    repoError.value = null;
    queryClient.invalidateQueries({ queryKey: ["chat-repos"] });
    showToast(
      queued === 0
        ? "Nothing new to index — every repository GitHub showed us is already here."
        : `${queued} ${queued === 1 ? "repository" : "repositories"} queued. They fill in as each one finishes.`,
      queued === 0 ? "muted" : "info",
    );
  },
  onError: (err) => {
    repoError.value = apiMessage(err, "Could not read your GitHub repositories.");
  },
});

const confirmDeleteRepo = ref<IndexedRepo | null>(null);

const removeRepo = useMutation({
  mutationFn: (id: number) => api.request<void>(`/chat/repos/${id}`, { method: "DELETE" }),
  onSuccess: (_result, id) => {
    confirmDeleteRepo.value = null;
    if (scope.value) scope.value = scope.value.filter((chosen) => chosen !== id);
    queryClient.invalidateQueries({ queryKey: ["chat-repos"] });
    showToast("Index deleted. Past answers keep their citations.", "muted");
  },
  onError: (err) => {
    confirmDeleteRepo.value = null;
    repoError.value = apiMessage(err, "Could not delete that index.");
  },
});

/* Retrying is the same POST that queued it: the API takes owner/name and starts a fresh
   job, and a failed row carries the name it was asked for. There is no retry endpoint. */
function retryRepo(repo: IndexedRepo) {
  repoError.value = null;
  addRepo.mutate(repo.full_name);
}

const connecting = ref(false);

/* Same handoff /sync uses: ask Pulse for the authorize URL, then leave in this tab —
   window.open after an await is outside the click's call stack and gets blocked.

   /github/reconnect for someone who is already connected. It leaves the stored account
   alone and only returns a URL, so the connection they have keeps working right up until
   GitHub confirms the new one. /github/connect is for someone with nothing connected. */
async function connectGitHub() {
  connecting.value = true;
  const path = notConnected.value ? "/github/connect" : "/github/reconnect";
  try {
    const res = await api.request<{ authorize_url: string }>(path, {
      method: notConnected.value ? "GET" : "POST",
    });
    window.location.href = res.authorize_url;
  } catch (err: unknown) {
    connecting.value = false;
    showToast(apiMessage(err, "Could not start the GitHub connection."), "bad");
  }
}

/* Indexing finishes while somebody is reading something else, so the arrival is spoken.
   The first list to land only primes the set — nobody wants five repositories read out
   because they opened the page. */
const knownReady = new Set<number>();
let primed = false;

watch(repos, (list) => {
  for (const repo of list) {
    if (repo.status !== "ready" || knownReady.has(repo.id)) continue;
    if (primed) announce(`${repo.full_name} finished indexing`);
    knownReady.add(repo.id);
  }
  primed = true;
});

/* ── which repositories a question searches ────────────────────────────────── */

// null means "every ready repository", including ones indexed after this page loaded.
// An explicit list is only kept once somebody narrows it themselves.
const scope = ref<number[] | null>(null);

const scopeIds = computed(() => scope.value ?? readyRepos.value.map((r) => r.id));
const nothingInScope = computed(() => readyRepos.value.length > 0 && scopeIds.value.length === 0);

function inScope(id: number): boolean {
  return scopeIds.value.includes(id);
}

function toggleScope(id: number) {
  const chosen = new Set(scopeIds.value);
  if (chosen.has(id)) chosen.delete(id);
  else chosen.add(id);
  scope.value = readyRepos.value.filter((r) => chosen.has(r.id)).map((r) => r.id);
}

/* ── conversations ─────────────────────────────────────────────────────────── */

const { data: conversationPage, isPending: listPending } = useQuery({
  queryKey: ["chat-conversations"],
  retry: false,
  queryFn: () =>
    api.request<Page<Conversation>>("/chat/conversations", {
      query: { limit: CONVERSATION_LIMIT, offset: 0 },
    }),
});

const conversations = computed(() => conversationPage.value?.items ?? []);

// Same rule as /journal: what is on screen is what the URL says, so a conversation can
// be sent to somebody. The most recent one is opened when nothing is asked for.
watch(
  conversations,
  (list) => {
    if (conversationId.value === null && list.length) conversationId.value = list[0]!.id;
  },
  { immediate: true },
);

const {
  data: detail,
  isPending: threadPending,
  isError: threadFailed,
  error: threadError,
} = useQuery({
  queryKey: computed(() => ["chat-conversation", conversationId.value ?? "none"]),
  enabled: computed(() => conversationId.value !== null),
  retry: false,
  queryFn: () => api.request<ConversationDetail>(`/chat/conversations/${conversationId.value}`),
});

// 404 is "someone else's, or gone". Said the same way /journal says it: not available to
// you, with no claim either way about what is behind the id.
const threadOutOfReach = computed(() => httpStatus(threadError.value) === 404);

const newConversation = useMutation({
  mutationFn: () => api.request<Conversation>("/chat/conversations", { method: "POST", body: {} }),
  onSuccess: (created) => {
    sendError.value = null;
    conversationId.value = created.id;
    queryClient.invalidateQueries({ queryKey: ["chat-conversations"] });
    nextTick(() => composerEl.value?.focus());
  },
  onError: (err) => {
    showToast(apiMessage(err, "Could not start a conversation."), "bad");
  },
});

const confirmDeleteConversation = ref<Conversation | null>(null);

const removeConversation = useMutation({
  mutationFn: (id: number) => api.request<void>(`/chat/conversations/${id}`, { method: "DELETE" }),
  onSuccess: (_result, id) => {
    confirmDeleteConversation.value = null;
    if (conversationId.value === id) conversationId.value = null;
    queryClient.invalidateQueries({ queryKey: ["chat-conversations"] });
    showToast("Conversation deleted.", "muted");
  },
  onError: (err) => {
    confirmDeleteConversation.value = null;
    showToast(apiMessage(err, "Could not delete that conversation."), "bad");
  },
});

/* ── asking ────────────────────────────────────────────────────────────────── */

const draft = ref("");
const composerEl = ref<HTMLTextAreaElement | null>(null);
// The question currently with the API. Held here so the thread can show it while the
// answer is being written, and so a failure can put it back in the box word for word.
const asking = ref<string | null>(null);
const sendError = ref<string | null>(null);
const nothingIndexed = ref(false);
// Set while a conversation opened for a failed first question is being thrown away, so
// the id returning to null is not read as somebody switching threads.
const discarded = ref(false);

const elapsed = ref(0);
let ticker: ReturnType<typeof setInterval> | null = null;

function stopTicker() {
  if (ticker !== null) clearInterval(ticker);
  ticker = null;
}

onUnmounted(stopTicker);

/* A conversation this composer opened for a question that never landed is thrown away
   again, so a refused first question does not leave a titled, empty thread in the list.
   Only one opened HERE: pressing New is somebody deliberately keeping an empty
   conversation to come back to, and that one is left alone.

   Cleaning up afterwards rather than creating the conversation only once the message
   lands, because the API takes a message on a conversation that already exists, and
   because the success path then keeps its timing exactly: the question stays on screen
   until the refetched thread replaces it. */
async function discardOpenedConversation(id: number) {
  try {
    await api.request<void>(`/chat/conversations/${id}`, { method: "DELETE" });
  } catch {
    // The send has already failed and is about to be explained. A tidy-up that also
    // failed is not a second thing to tell somebody about.
  }
  if (conversationId.value === id) {
    // The verdict on the send belongs to the composer and has to survive this. See the
    // watch on conversationId at the foot of this block.
    discarded.value = true;
    conversationId.value = null;
  }
  queryClient.invalidateQueries({ queryKey: ["chat-conversations"] });
}

const send = useMutation({
  mutationFn: async (question: string) => {
    // A first question with no conversation open makes one, rather than refusing until
    // somebody presses New.
    let id = conversationId.value;
    let opened: number | null = null;
    if (id === null) {
      const created = await api.request<Conversation>("/chat/conversations", { method: "POST", body: {} });
      id = created.id;
      opened = created.id;
      conversationId.value = id;
      queryClient.invalidateQueries({ queryKey: ["chat-conversations"] });
    }
    let reply: ChatMessage;
    try {
      reply = await api.request<ChatMessage>(`/chat/conversations/${id}/messages`, {
        method: "POST",
        body: { content: question, indexed_repo_ids: scopeIds.value },
      });
    } catch (err) {
      if (opened !== null) await discardOpenedConversation(opened);
      throw err;
    }
    return { id, reply };
  },
  onSuccess: async ({ id, reply }) => {
    sendError.value = null;
    nothingIndexed.value = false;
    // The server owns the order and the ids, so the thread is refetched rather than
    // spliced — the same rule the journal feed follows. `asking` is only dropped once
    // the refetch has landed, so the question never blinks out of the thread.
    await queryClient.invalidateQueries({ queryKey: ["chat-conversation", id] });
    queryClient.invalidateQueries({ queryKey: ["chat-conversations"] });
    asking.value = null;
    // The thread itself is a log region and reads the answer out; this adds the one
    // thing the prose does not say, rather than saying the answer twice.
    const count = reply.citations?.length ?? 0;
    announce(count ? `Answer received, ${count} ${count === 1 ? "citation" : "citations"}` : "Answer received");
  },
  onError: (err) => {
    // The question goes back in the box before anything else happens.
    if (asking.value !== null) draft.value = asking.value;
    asking.value = null;
    const code = httpStatus(err);
    nothingIndexed.value = code === 422;
    sendError.value =
      code === 429
        /* Two refusals share this status. The daily allowance comes back as a FastAPI
           `detail` written for whoever is paying, so it is shown as sent rather than
           reworded; the sixty-an-hour burst limit is slowapi's and carries no `detail`,
           so it falls through to the sentence below. Either way the question is back in
           the box. */
        ? apiMessage(err, "That is sixty questions in an hour, which is the limit. Nothing here is lost, and your question is back in the box.")
        : code === 502
          ? "The AI service did not answer, so the question was not answered and nothing was saved. Your question is back in the box."
          : code === 422
            ? "Nothing is indexed yet, so there is nothing to search. Index a repository and the assistant has something to read."
            : code === 404
              ? "This conversation is not available to you, so the question was not sent."
              : apiMessage(err, "Could not send that question.");
  },
});

watch(
  () => send.isPending.value,
  (busy) => {
    stopTicker();
    elapsed.value = 0;
    if (!busy) return;
    ticker = setInterval(() => {
      elapsed.value += 1;
    }, 1000);
  },
);

// Not streaming: the whole answer arrives at once, so the wait has to say what it is
// doing rather than leave a spinner turning over an empty panel.
const waitingLine = computed(() => {
  const names = readyRepos.value.filter((r) => inScope(r.id)).map((r) => r.full_name);
  const where = names.length === 1 ? names[0] : `${names.length} repositories`;
  if (elapsed.value < 6) return `Searching ${where} for the relevant code…`;
  if (elapsed.value < 20) return `Reading the files it found in ${where} and writing an answer…`;
  return `Still writing. A first question over a large repository can take a minute — ${where} is being read in full.`;
});

const messages = computed(() => detail.value?.messages ?? []);
const question = computed(() => draft.value.trim());
const canSend = computed(() =>
  question.value !== "" && !send.isPending.value && !nothingInScope.value && question.value.length <= MAX_QUESTION,
);

function submitQuestion() {
  if (!canSend.value) return;
  const typed = question.value;
  sendError.value = null;
  nothingIndexed.value = false;
  asking.value = typed;
  draft.value = "";
  send.mutate(typed);
}

// Enter sends, Shift+Enter breaks the line. isComposing keeps an IME's own Enter — the
// one that commits a candidate — from posting a half-typed question.
function onComposerKeydown(event: KeyboardEvent) {
  if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
  event.preventDefault();
  submitQuestion();
}

function focusRepoInput() {
  repoInputEl.value?.focus();
  repoInputEl.value?.scrollIntoView({ block: "center", behavior: "smooth" });
}

const openCitations = ref<string | null>(null);

function citationKey(messageId: number, index: number): string {
  return `${messageId}:${index}`;
}

const readout = computed(() =>
  readyRepos.value.length
    ? `${readyRepos.value.length} ${readyRepos.value.length === 1 ? "repo" : "repos"} indexed`
    : "assistant",
);

// A different conversation is a different thread and a different verdict on the last
// question, so nothing from the previous one may survive the switch. Discarding a
// conversation the composer itself opened is not a switch: the refusal that caused it is
// the one thing on screen worth keeping.
watch(conversationId, () => {
  if (discarded.value) {
    discarded.value = false;
    return;
  }
  sendError.value = null;
  nothingIndexed.value = false;
  openCitations.value = null;
});
</script>

<template>
  <PulseShell :readout="readout">
    <header class="sec flex flex-wrap items-end justify-between gap-4">
      <div class="min-w-0">
        <Eyebrow>Pulse · assistant</Eyebrow>
        <h1 class="mt-3 text-[clamp(1.5rem,2.2vw,1.9rem)] font-semibold leading-[1.05] tracking-[-0.035em]">
          Ask about the code
        </h1>
        <p class="mt-1.5 max-w-[68ch] text-[12.5px] leading-relaxed text-ink-muted">
          Index a repository once, then ask questions about it in plain English. Every answer names
          the files and lines it was drawn from, so it can be checked rather than taken on trust.
        </p>
      </div>
      <p class="mono flex shrink-0 items-center gap-2 rounded-md bg-sunken px-2.5 py-2 text-[12px] ring-1 ring-inset ring-line-subtle">
        <span :class="[MONO_LABEL, 'text-ink-faint']">post</span>
        <span class="text-ink">/chat/conversations/…/messages</span>
      </p>
    </header>

    <!-- Nothing indexed at all is the one case where the index outranks the chat: there
         is no question anybody can usefully ask yet. -->
    <div
      v-if="!reposPending && !repos.length && !reposFailed"
      class="sec mt-8 rounded-md bg-surface/40 px-5 py-8 ring-1 ring-inset ring-line-subtle"
      style="animation-delay: 60ms"
      data-test="no-repos"
    >
      <h2 class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">Nothing is indexed yet</h2>
      <p class="mt-1.5 max-w-[62ch] text-[12.5px] leading-relaxed text-ink-muted">
        The assistant only answers from repositories it has read. Index one below — your own
        GitHub repositories in a batch, or any public repository by name — and the first question
        becomes possible. Indexing runs in the background and a small repository takes under a
        minute.
      </p>
    </div>

    <div class="sec mt-8 grid items-start gap-8 lg:grid-cols-[minmax(0,1fr)_320px]" style="animation-delay: 80ms">
      <!-- ── the conversation ──────────────────────────────────────────────── -->
      <section class="min-w-0" aria-labelledby="thread-heading">
        <div class="flex flex-wrap items-baseline justify-between gap-3 border-b border-line-subtle pb-2">
          <h2 id="thread-heading" class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">
            {{ detail?.title ?? "Conversation" }}
          </h2>
          <p v-if="messages.length" class="mono text-[12px] text-ink-muted">
            {{ messages.length }} {{ messages.length === 1 ? "message" : "messages" }}
          </p>
        </div>

        <div
          v-if="threadFailed && threadOutOfReach"
          class="mt-6 rounded-md bg-surface/40 px-5 py-8 ring-1 ring-inset ring-line-subtle"
          data-test="thread-missing"
        >
          <h3 class="text-[13.5px] font-medium text-ink">This conversation is not available to you</h3>
          <p class="mt-1.5 max-w-[58ch] text-[12.5px] leading-relaxed text-ink-muted">
            The list beside this one holds every conversation you can open, so an id typed into the
            address bar usually lands here. Start a new one, or pick one from the list.
          </p>
        </div>

        <p
          v-else-if="threadFailed"
          role="alert"
          class="mt-6 max-w-[74ch] rounded-md bg-bad-surface px-4 py-3 text-[12.5px] leading-relaxed text-ink"
        >
          {{ apiMessage(threadError, "Could not read this conversation. Nothing has been lost.") }}
        </p>

        <template v-else>
          <p v-if="threadPending && conversationId !== null" class="mt-6 text-[12.5px] text-ink-muted">
            Reading the conversation…
          </p>

          <div
            v-else-if="!messages.length && asking === null"
            class="mt-6 rounded-md bg-surface/40 px-5 py-8 ring-1 ring-inset ring-line-subtle"
            data-test="thread-empty"
          >
            <p class="text-[13.5px] font-medium text-ink">Ask the first question</p>
            <p class="mt-1.5 max-w-[58ch] text-[12.5px] leading-relaxed text-ink-muted">
              Try <span class="text-ink">where is the refresh token rotated?</span> or
              <span class="text-ink">what does the sync worker do when GitHub rate limits it?</span>
              The answer comes back with the files it was read from.
            </p>
          </div>

          <!-- role="log" so a screen reader hears an answer arrive without the whole
               thread being read again. Keyed on the conversation: switching threads
               replaces the region rather than adding fifty messages to the live one. -->
          <ol
            v-else
            :key="conversationId ?? 'none'"
            role="log"
            aria-live="polite"
            aria-relevant="additions"
            aria-label="Conversation"
            data-test="thread"
            class="mt-5 space-y-5"
          >
            <li v-for="message in messages" :key="message.id" data-test="message" :data-role="message.role">
              <p class="flex flex-wrap items-baseline gap-2 text-[12px] text-ink-muted">
                <span :class="[MONO_LABEL, message.role === 'user' ? 'text-ink' : 'text-ink-faint']">
                  {{ message.role === "user" ? "you" : "assistant" }}
                </span>
                <span class="mono text-[12px]">{{ formatDateTime(message.created_at) }}</span>
                <span v-if="message.model" class="mono text-[12px]">{{ message.model }}</span>
              </p>

              <!-- Interpolated, never v-html. This is a language model's output: it is
                   text on this page and nothing else, whatever it happens to contain. -->
              <p
                data-test="message-content"
                :class="[
                  'mt-1.5 max-w-[80ch] whitespace-pre-wrap text-[13px] leading-relaxed text-ink',
                  message.role === 'user'
                    ? 'rounded-md bg-sunken px-3.5 py-3 ring-1 ring-inset ring-line-subtle'
                    : '',
                ]"
              >{{ message.content }}</p>

              <ul v-if="message.citations?.length" class="mt-2.5 space-y-1.5" data-test="citations">
                <li v-for="(citation, index) in message.citations" :key="citationKey(message.id, index)" data-test="citation">
                  <button
                    type="button"
                    data-test="citation-toggle"
                    :aria-expanded="openCitations === citationKey(message.id, index)"
                    :class="[FOCUS, 'mono flex w-full items-baseline gap-2 rounded px-1 py-0.5 text-left text-[12px] text-ink-muted transition-colors hover:text-ink']"
                    @click="openCitations = openCitations === citationKey(message.id, index) ? null : citationKey(message.id, index)"
                  >
                    <span aria-hidden="true">{{ openCitations === citationKey(message.id, index) ? "−" : "+" }}</span>
                    <span class="min-w-0 break-all">{{ citationRef(citation) }}</span>
                  </button>
                  <!-- Code, so it keeps its own whitespace and scrolls sideways rather
                       than wrapping a long line in the middle of an identifier. -->
                  <pre
                    v-if="openCitations === citationKey(message.id, index)"
                    data-test="citation-snippet"
                    class="mono mt-1 max-w-full overflow-x-auto whitespace-pre rounded-md bg-sunken px-3 py-2.5 text-[12px] leading-relaxed text-ink ring-1 ring-inset ring-line-subtle"
                  >{{ citation.snippet }}</pre>
                </li>
              </ul>
            </li>

            <!-- The question, while it is with the API. -->
            <li v-if="asking !== null" data-test="asking">
              <p :class="[MONO_LABEL, 'text-ink']">you</p>
              <p class="mt-1.5 max-w-[80ch] whitespace-pre-wrap rounded-md bg-sunken px-3.5 py-3 text-[13px] leading-relaxed text-ink ring-1 ring-inset ring-line-subtle">{{ asking }}</p>
            </li>
          </ol>

          <div
            v-if="send.isPending.value"
            data-test="waiting"
            class="mt-5 flex flex-wrap items-center gap-3 rounded-md bg-surface/40 px-4 py-3 ring-1 ring-inset ring-line-subtle"
          >
            <StatusDot tone="info" />
            <p class="min-w-0 text-[12.5px] leading-relaxed text-ink-muted">{{ waitingLine }}</p>
            <span class="mono ml-auto text-[12px] text-ink-faint">{{ elapsed }}s</span>
          </div>
        </template>

        <!-- ── the composer ─────────────────────────────────────────────────── -->
        <div class="mt-6 border-t border-line-subtle pt-5">
          <div v-if="readyRepos.length" class="flex flex-wrap items-center gap-2" data-test="scope">
            <span :class="[MONO_LABEL, 'text-ink-faint']">search</span>
            <button
              v-for="repo in repos"
              :key="repo.id"
              type="button"
              data-test="scope-option"
              :disabled="repo.status !== 'ready'"
              :aria-pressed="repo.status === 'ready' ? inScope(repo.id) : undefined"
              :title="repo.status === 'ready' ? undefined : `${indexLabel(repo.status)} — not ready to search`"
              :class="[
                FOCUS,
                DISABLED,
                'rounded-md px-2.5 py-1 text-[12px] ring-1 ring-inset transition-colors',
                repo.status !== 'ready'
                  ? 'ring-line-subtle'
                  : inScope(repo.id)
                    ? 'bg-surface-active text-ink ring-line-strong'
                    : 'text-ink-muted ring-line-subtle hover:bg-surface-hover hover:text-ink',
              ]"
              @click="toggleScope(repo.id)"
            >{{ repo.full_name }}</button>
          </div>

          <p v-if="nothingInScope" class="mt-2 text-[12px] text-warn" data-test="scope-empty">
            Nothing is selected to search, so there is nothing to ask about. Pick at least one
            repository above.
          </p>

          <label for="chat-question" class="mt-3 block text-[12px] text-ink-muted">
            Your question
          </label>
          <textarea
            id="chat-question"
            ref="composerEl"
            v-model="draft"
            rows="3"
            data-test="composer"
            :maxlength="MAX_QUESTION"
            :disabled="send.isPending.value"
            placeholder="Where is the refresh token rotated?"
            :class="[FOCUS, DISABLED, 'mt-1.5 w-full resize-y rounded-md bg-sunken px-3 py-2.5 text-[12.5px] leading-relaxed text-ink ring-1 ring-inset ring-line transition-colors placeholder:text-ink-faint enabled:hover:ring-line-strong']"
            @keydown="onComposerKeydown"
          />
          <div class="mt-2 flex flex-wrap items-center gap-3">
            <Btn
              size="sm"
              data-test="composer-send"
              :disabled="!canSend"
              :busy="send.isPending.value"
              @click="submitQuestion"
            >Ask</Btn>
            <p class="text-[12.5px] text-ink-muted">
              <kbd class="text-[12px] text-ink">Enter</kbd> sends ·
              <kbd class="text-[12px] text-ink">Shift</kbd> +
              <kbd class="text-[12px] text-ink">Enter</kbd> starts a new line
            </p>
            <span v-if="send.isPending.value" class="mono text-[12px] text-ink-faint">
              the answer arrives whole, not word by word
            </span>
          </div>

          <div
            v-if="sendError"
            role="alert"
            data-test="composer-error"
            class="mt-3 max-w-[74ch] rounded-md bg-bad-surface px-3.5 py-2.5 text-[12.5px] leading-relaxed text-ink"
          >
            {{ sendError }}
            <div v-if="nothingIndexed" class="mt-2.5">
              <Btn size="sm" variant="secondary" data-test="go-to-index" @click="focusRepoInput">
                Index a repository
              </Btn>
            </div>
          </div>
        </div>
      </section>

      <!-- ── the index and the conversation list ───────────────────────────── -->
      <aside class="min-w-0 space-y-8">
        <section aria-labelledby="conversations-heading">
          <div class="flex items-baseline justify-between gap-3 border-b border-line-subtle pb-2">
            <h2 id="conversations-heading" class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">
              Conversations
            </h2>
            <button
              type="button"
              data-test="conversation-new"
              :class="[FOCUS, 'rounded text-[12.5px] text-ink-muted transition-colors hover:text-ink']"
              @click="newConversation.mutate()"
            >New</button>
          </div>

          <p v-if="listPending" class="mt-3 text-[12px] text-ink-muted">Reading your conversations…</p>

          <p v-else-if="!conversations.length" class="mt-3 max-w-[40ch] text-[12px] leading-relaxed text-ink-muted" data-test="no-conversations">
            No conversations yet. Ask a question and this fills itself in — the first question
            names the thread.
          </p>

          <ul v-else class="mt-1 divide-y divide-line-subtle" data-test="conversation-list">
            <li v-for="row in conversations" :key="row.id" class="flex items-center gap-2 py-1.5" data-test="conversation-row">
              <button
                type="button"
                data-test="conversation-open"
                :aria-current="row.id === conversationId ? 'true' : undefined"
                :class="[
                  FOCUS,
                  'min-w-0 flex-1 rounded px-1 py-1 text-left transition-colors',
                  row.id === conversationId ? 'text-ink' : 'text-ink-muted hover:text-ink',
                ]"
                @click="conversationId = row.id"
              >
                <span class="block truncate text-[12.5px]">{{ row.title }}</span>
                <span class="mono block text-[12px] text-ink-faint">{{ relativeTime(row.updated_at) }}</span>
              </button>
              <button
                type="button"
                data-test="conversation-delete"
                :aria-label="`Delete ${row.title}`"
                :class="[FOCUS, 'shrink-0 rounded px-1.5 py-1 text-[12.5px] text-ink-faint transition-colors hover:text-bad']"
                @click="confirmDeleteConversation = row"
              >Delete</button>
            </li>
          </ul>
        </section>

        <section aria-labelledby="index-heading">
          <div class="flex items-baseline justify-between gap-3 border-b border-line-subtle pb-2">
            <h2 id="index-heading" class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">
              Indexed repositories
            </h2>
            <p v-if="settling" class="mono text-[12px] text-ink-muted" data-test="indexing-now">working…</p>
          </div>

          <!-- A notice, not a wall: a public repository indexes whether or not GitHub is
               connected, so the input below stays live either way. -->
          <div
            v-if="githubInTheWay"
            data-test="github-notice"
            class="mt-3 rounded-md bg-warn-surface px-3.5 py-3"
          >
            <p class="text-[12.5px] font-medium text-ink">
              {{ notConnected ? "Connect GitHub to index private repositories" : "Private repositories need a GitHub reconnect" }}
            </p>
            <!-- The server's own sentence when it has one. It already says that approving
                 replaces the connection in place, so nothing here repeats or contradicts it. -->
            <p v-if="needsReconnect" data-test="github-notice-detail" class="mt-1 text-[12px] leading-relaxed text-ink-muted">
              {{ reconnectDetail ?? "The connected GitHub account cannot read private repositories." }}
              Anything already indexed is kept.
            </p>
            <p v-else class="mt-1 text-[12px] leading-relaxed text-ink-muted">
              No GitHub account is connected, so only public repositories can be indexed.
            </p>
            <Btn
              class="mt-2.5"
              size="sm"
              variant="secondary"
              data-test="github-connect"
              :busy="connecting"
              @click="connectGitHub"
            >{{ notConnected ? "Connect GitHub" : "Reconnect GitHub" }}</Btn>
          </div>

          <div class="mt-3">
            <label for="chat-repo" class="block text-[12px] text-ink-muted">Add a public repository</label>
            <div class="mt-1.5 flex gap-2">
              <input
                id="chat-repo"
                ref="repoInputEl"
                v-model="repoInput"
                type="text"
                autocomplete="off"
                spellcheck="false"
                placeholder="owner/name"
                data-test="repo-input"
                :class="[FOCUS, 'mono min-w-0 flex-1 rounded-md bg-sunken px-3 py-2 text-[12px] text-ink ring-1 ring-inset ring-line transition-colors placeholder:text-ink-faint hover:ring-line-strong']"
                @keydown.enter.prevent="submitRepo"
              />
              <Btn size="sm" data-test="repo-add" :busy="addRepo.isPending.value" @click="submitRepo">Index</Btn>
            </div>
            <p class="mt-2">
              <button
                type="button"
                data-test="index-mine"
                :disabled="indexMine.isPending.value"
                :class="[FOCUS, DISABLED, 'rounded text-[12.5px] text-ink-muted underline underline-offset-2 transition-colors enabled:hover:text-ink']"
                @click="indexMine.mutate()"
              >{{ indexMine.isPending.value ? "Asking GitHub…" : "Index my GitHub repositories" }}</button>
            </p>
            <p
              v-if="repoError"
              role="alert"
              data-test="repo-error"
              class="mt-2 rounded-md bg-bad-surface px-3 py-2 text-[12px] leading-relaxed text-ink"
            >{{ repoError }}</p>
          </div>

          <p v-if="reposPending" class="mt-4 text-[12px] text-ink-muted">Reading the index…</p>

          <p v-else-if="reposFailed" role="alert" class="mt-4 text-[12px] leading-relaxed text-ink-muted">
            The index could not be read, so nothing below is current. Asking a question still
            works if something was indexed earlier.
          </p>

          <ul v-else-if="repos.length" class="mt-4 divide-y divide-line-subtle" data-test="repo-list">
            <li v-for="repo in repos" :key="repo.id" class="py-2.5" data-test="repo-row">
              <div class="flex items-baseline justify-between gap-2">
                <span class="mono min-w-0 break-all text-[12px] text-ink">{{ repo.full_name }}</span>
                <StatusDot :tone="indexTone(repo.status)" quiet class="shrink-0" data-test="repo-status">
                  {{ indexLabel(repo.status) }}
                </StatusDot>
              </div>

              <p class="mono mt-1 text-[12px] text-ink-faint">
                <template v-if="repo.status === 'ready'">
                  {{ repo.file_count }} files · {{ repo.chunk_count }} chunks
                  <template v-if="repo.commit_sha"> · {{ repo.commit_sha.slice(0, 7) }}</template>
                </template>
                <template v-else-if="isSettling(repo)">
                  {{ repo.file_count ? `${repo.file_count} files read so far` : "waiting for a worker" }}
                </template>
                <template v-else>{{ repo.is_public ? "public" : "private" }}</template>
              </p>

              <p v-if="repo.detail && repo.status !== 'ready'" data-test="repo-detail" class="mt-1 text-[12.5px] leading-relaxed text-ink-muted">
                {{ repo.detail }}
              </p>

              <!-- A pause is waiting, so carrying on is the offer and it is a button rather
                   than a quiet link. A failure keeps the quieter retry: it usually needs
                   reading first, not clicking again. -->
              <div class="mt-2 flex flex-wrap items-center gap-3">
                <Btn
                  v-if="isResumable(repo)"
                  size="sm"
                  variant="secondary"
                  data-test="repo-resume"
                  @click="retryRepo(repo)"
                >Carry on indexing</Btn>
                <button
                  v-else-if="isRetryable(repo)"
                  type="button"
                  data-test="repo-retry"
                  :class="[FOCUS, 'rounded text-[12.5px] text-ink-muted transition-colors hover:text-ink']"
                  @click="retryRepo(repo)"
                >Try again</button>
                <button
                  type="button"
                  data-test="repo-delete"
                  :aria-label="`Delete the index of ${repo.full_name}`"
                  :class="[FOCUS, 'rounded text-[12.5px] text-ink-faint transition-colors hover:text-bad']"
                  @click="confirmDeleteRepo = repo"
                >Delete</button>
              </div>
            </li>
          </ul>
        </section>
      </aside>
    </div>

    <Modal
      :open="confirmDeleteRepo !== null"
      title="Delete this index?"
      description="The repository itself is untouched. Questions can no longer be answered from it until it is indexed again."
      :close-on-backdrop="false"
      @close="confirmDeleteRepo = null"
    >
      <p class="mono max-w-[42ch] break-all text-[12.5px] text-ink-muted">{{ confirmDeleteRepo?.full_name }}</p>
      <template #footer>
        <Btn size="sm" variant="ghost" @click="confirmDeleteRepo = null">Keep it</Btn>
        <Btn
          size="sm"
          variant="destructive"
          data-test="repo-delete-confirm"
          :busy="removeRepo.isPending.value"
          @click="confirmDeleteRepo && removeRepo.mutate(confirmDeleteRepo.id)"
        >Delete index</Btn>
      </template>
    </Modal>

    <Modal
      :open="confirmDeleteConversation !== null"
      title="Delete this conversation?"
      description="Every question and answer in it goes with it. This cannot be undone."
      :close-on-backdrop="false"
      @close="confirmDeleteConversation = null"
    >
      <p class="max-w-[42ch] text-[12.5px] leading-relaxed text-ink-muted">
        {{ confirmDeleteConversation?.title }}
      </p>
      <template #footer>
        <Btn size="sm" variant="ghost" @click="confirmDeleteConversation = null">Keep it</Btn>
        <Btn
          size="sm"
          variant="destructive"
          data-test="conversation-delete-confirm"
          :busy="removeConversation.isPending.value"
          @click="confirmDeleteConversation && removeConversation.mutate(confirmDeleteConversation.id)"
        >Delete conversation</Btn>
      </template>
    </Modal>
  </PulseShell>
</template>
