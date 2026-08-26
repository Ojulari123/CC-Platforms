import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from "vue";
import { mount } from "@vue/test-utils";
import { vi } from "vitest";
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import Avatar from "@crescent/ui/components/Avatar.vue";
import Cross from "@crescent/ui/components/Cross.vue";
import Btn from "@crescent/ui/components/Btn.vue";
import Eyebrow from "@crescent/ui/components/Eyebrow.vue";
import Icon from "@crescent/ui/components/Icon.vue";
import Modal from "@crescent/ui/components/Modal.vue";
import Select from "@crescent/ui/components/Select.vue";
import StatusDot from "@crescent/ui/components/StatusDot.vue";
import TabPanel from "@crescent/ui/components/TabPanel.vue";
import Tabs from "@crescent/ui/components/Tabs.vue";
import { DISABLED, FOCUS, MONO_LABEL, TAP } from "@crescent/ui/utils/ui";
import type { MemberResponse, RepositoryResponse, UserMeResponse } from "~/types/api";
import {
  actionLabel,
  apiMessage,
  formatDate,
  formatDateTime,
  formatStamp,
  httpStatus,
  isoDaysAgo,
  mondayOf,
  personName,
  relativeTime,
  statusClass,
  statusLabel,
} from "~/utils/format";
import { failedRuns, failureFingerprint, inferTrigger, nextScheduledRun, pageCount, parseSyncCounts, runDuration, runLabel, runTone } from "~/utils/pulse";
import {
  citationRef,
  indexLabel,
  indexTone,
  isFullName,
  isResumable,
  isRetryable,
  isSettling,
  normalizeRepoInput,
  REPO_POLL_MS,
} from "~/utils/chat";
import {
  budgetSentence,
  budgetSourceLine,
  capLabel,
  capLockedLine,
  dialOptions,
  effectiveSentence,
  isSystemPersona,
  personaLine,
  personaPreview,
  PERSONA_DIALS,
  providerLabel,
  tokenCount,
} from "~/utils/personas";
import {
  adhocFailure,
  isGithubLogin,
  MAX_ADHOC_PER_HOUR,
  MAX_RANGE_DAYS,
  MAX_SUBJECTS,
  rangeProblem,
  spanDays,
  subjectPayload,
  subjectReady,
} from "~/utils/adhoc";
import {
  ATTRIBUTION_NOTE,
  canDecide,
  isAdhoc,
  reportKindLabel,
  reportKindShort,
  orderedSubjects,
  REPORT_FIELDS,
  REPORT_STATUSES,
  reportRange,
  reportRepoLabel,
  statusTone,
  subjectLabel,
} from "~/utils/pulse";
import ReportDecision from "~/components/ReportDecision.vue";

/* Mounting a Pulse page outside Nuxt, the way packages/ui/test/pageHarness.ts does it for
   the layer's own pages. A page carries no imports for `ref`, `useRoute` or `useApi`
   because Nuxt injects them; free identifiers in the compiled setup function fall through
   to globalThis, so putting them there runs the real page rather than a copy of it.

   Template-only names (FOCUS, personName, …) are a separate problem: the SFC compiler
   emits those as `_ctx.NAME`, which never reaches globalThis. They go in through
   `global.mocks`, which is Vue's own globalProperties. */

export interface ApiCall {
  path: string;
  method: string;
  query?: Record<string, unknown>;
  body?: unknown;
}

export type ApiHandler = (call: ApiCall) => unknown;

export interface HarnessOptions {
  /** Answers every request the page makes. Throw `apiError(...)` to fail one. */
  api: ApiHandler;
  repositories?: RepositoryResponse[];
  /** What useTeammates() answers with — identity's members of your departments. */
  teammates?: MemberResponse[];
  reposPending?: boolean;
  reposFailed?: boolean;
  me?: UserMeResponse | null;
  query?: Record<string, string>;
  /** Route params, for the pages that read one — /reports/[id] wants `id`. */
  params?: Record<string, string>;
  /** Which page to mount. Defaults to the journal, which is what most of these ask for. */
  page?: keyof typeof PAGES;
}

const TEMPLATE_NAMES = {
  DISABLED,
  mondayOf,
  nextScheduledRun,
  failedRuns,
  failureFingerprint,
  parseSyncCounts,
  runDuration,
  runLabel,
  runTone,
  inferTrigger,
  REPORT_STATUSES,
  FOCUS,
  MONO_LABEL,
  TAP,
  apiMessage,
  formatDate,
  formatDateTime,
  formatStamp,
  httpStatus,
  pageCount,
  personName,
  relativeTime,
  REPO_POLL_MS,
  citationRef,
  indexLabel,
  indexTone,
  isFullName,
  isResumable,
  isRetryable,
  isSettling,
  normalizeRepoInput,
  isoDaysAgo,
  PERSONA_DIALS,
  dialOptions,
  personaPreview,
  personaLine,
  isSystemPersona,
  effectiveSentence,
  providerLabel,
  budgetSentence,
  budgetSourceLine,
  capLabel,
  capLockedLine,
  tokenCount,
  MAX_RANGE_DAYS,
  MAX_SUBJECTS,
  MAX_ADHOC_PER_HOUR,
  spanDays,
  rangeProblem,
  isGithubLogin,
  subjectReady,
  subjectPayload,
  adhocFailure,
  isAdhoc,
  reportKindLabel,
  reportKindShort,
  orderedSubjects,
  reportRange,
  reportRepoLabel,
  subjectLabel,
  ATTRIBUTION_NOTE,
  canDecide,
  REPORT_FIELDS,
  statusTone,
  statusClass,
  statusLabel,
  actionLabel,
};

// Which page mountPage() puts up. The import paths are literal so vite can see them.
const PAGES = {
  journal: () => import("~/pages/journal.vue"),
  chat: () => import("~/pages/chat.vue"),
  settings: () => import("~/pages/settings.vue"),
  adhoc: () => import("~/pages/reports/adhoc.vue"),
  report: () => import("~/pages/reports/[id].vue"),
  home: () => import("~/pages/index.vue"),
  sync: () => import("~/pages/sync.vue"),
};

// The layer components a Pulse page reaches for by auto-import, plus the product shell,
// which is only a slot around the chrome and would drag TopBar's router links in.
const components = {
  Avatar,
  Cross,
  Btn,
  Eyebrow,
  Icon,
  Modal,
  Select,
  StatusDot,
  TabPanel,
  Tabs,
  ReportDecision,
  PulseShell: { template: "<div><slot /></div>" },
  // The real one needs a router; every screen only ever uses it as a link.
  NuxtLink: { props: ["to"], template: "<a :href='to'><slot /></a>" },
};

export function installNuxt(options: HarnessOptions) {
  const g = globalThis as Record<string, unknown>;

  g.ref = ref;
  g.computed = computed;
  g.reactive = reactive;
  g.watch = watch;
  g.nextTick = nextTick;
  g.onMounted = onMounted;
  g.onUnmounted = onUnmounted;
  g.definePageMeta = () => {};
  g.useHead = () => {};

  Object.assign(g, TEMPLATE_NAMES);

  const request = vi.fn(async (path: string, opts: { method?: string; query?: Record<string, unknown>; body?: unknown } = {}) =>
    options.api({ path, method: opts.method ?? "GET", query: opts.query, body: opts.body }),
  );

  const route = reactive({
    path: `/${options.page ?? "journal"}`,
    query: { ...(options.query ?? {}) } as Record<string, string>,
    params: { ...(options.params ?? {}) } as Record<string, string>,
  });
  const replace = vi.fn((to: { query: Record<string, string | undefined> }) => {
    const next: Record<string, string> = {};
    for (const [key, value] of Object.entries(to.query)) if (value !== undefined) next[key] = String(value);
    route.query = next;
    return Promise.resolve();
  });
  const announce = vi.fn();
  const toast = vi.fn();
  const push = vi.fn();

  const repositories = ref(options.repositories ?? []);
  const me = ref(options.me === undefined ? null : options.me);

  g.useApi = () => ({ request });
  g.navigateTo = vi.fn();
  g.useRuntimeConfig = () => ({ public: { pulseUrl: "http://pulse.test", identityUrl: "http://identity.test", authStoragePrefix: "pulse" } });
  g.useAuth = () => ({
    user: me,
    accessToken: ref("test-token"),
    isAuthenticated: computed(() => me.value !== null),
    fetchMe: vi.fn(),
  });
  g.useRoute = () => route;
  g.useRouter = () => ({ replace, push });
  g.useAnnounce = () => announce;
  g.useToast = () => ({ show: toast, clear: vi.fn(), toast: ref(null) });
  g.useMe = () => ({ me, unavailable: computed(() => false), settled: ref(true) });
  g.useRepositories = () => ({
    repositories,
    isPending: ref(options.reposPending ?? false),
    isError: ref(options.reposFailed ?? false),
    repoName: (id: number) => repositories.value.find((r) => r.id === id)?.full_name ?? `repo_id ${id}`,
  });

  const teammates = ref(options.teammates ?? []);
  g.useTeammates = () => ({
    data: teammates,
    others: computed(() => teammates.value.filter((m) => m.user_id !== me.value?.id)),
    hasDepartment: computed(() => (me.value?.memberships.length ?? 0) > 0),
    isPending: ref(false),
    isError: ref(false),
  });

  return { request, route, replace, push, announce, toast, repositories, me, teammates };
}

export async function mountPage(options: HarnessOptions) {
  const harness = installNuxt(options);
  const Page = (await PAGES[options.page ?? "journal"]()).default;
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, refetchOnWindowFocus: false } },
  });
  const wrapper = mount(Page, {
    global: {
      components,
      mocks: TEMPLATE_NAMES,
      plugins: [[VueQueryPlugin, { queryClient }]],
    },
  });
  await flush();
  return { ...harness, wrapper, queryClient };
}

/** Let every pending promise, watcher and query settle. */
export async function flush(rounds = 6) {
  for (let i = 0; i < rounds; i += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0));
    await nextTick();
  }
}

/** An HTTP failure shaped the way ofetch reports one, which is what the pages read. */
export function apiError(status: number, detail?: string) {
  return Object.assign(new Error(`HTTP ${status}`), {
    status,
    statusCode: status,
    data: detail ? { detail } : undefined,
  });
}
