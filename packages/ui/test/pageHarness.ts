import { computed, nextTick, onMounted, ref } from "vue";
import { vi } from "vitest";
import Btn from "../components/Btn.vue";
import Cross from "../components/Cross.vue";
import Eyebrow from "../components/Eyebrow.vue";
import Icon from "../components/Icon.vue";
import Mark from "../components/Mark.vue";
import PasswordField from "../components/PasswordField.vue";
import RuleTicks from "../components/RuleTicks.vue";
import RulerStrip from "../components/RulerStrip.vue";
import StatusDot from "../components/StatusDot.vue";
import TopBar from "../components/TopBar.vue";
import { usePasswordRules } from "../composables/usePasswordRules";

/* Mounting a Nuxt page outside Nuxt. The page files carry no imports for `ref`,
   `useRoute`, `$fetch` and friends because Nuxt injects them; unresolved identifiers in
   compiled SFC code fall through to globalThis, so putting them there is enough to run
   the real page rather than a copy of it. types/nuxt-globals.d.ts types the same set. */

export const IDENTITY_URL = "http://identity.test";

export interface HarnessOptions {
  query?: Record<string, unknown>;
  fetch?: ReturnType<typeof vi.fn>;
}

export interface Harness {
  fetch: ReturnType<typeof vi.fn>;
  push: ReturnType<typeof vi.fn>;
  replace: ReturnType<typeof vi.fn>;
  adoptSession: ReturnType<typeof vi.fn>;
  announce: ReturnType<typeof vi.fn>;
  navigateTo: ReturnType<typeof vi.fn>;
}

export function installNuxt(options: HarnessOptions = {}): Harness {
  const g = globalThis as Record<string, unknown>;

  g.ref = ref;
  g.computed = computed;
  g.onMounted = onMounted;
  g.nextTick = nextTick;
  g.usePasswordRules = usePasswordRules;

  g.definePageMeta = () => {};
  g.useHead = () => {};

  const fetch = options.fetch ?? vi.fn();
  const push = vi.fn(async () => undefined);
  const replace = vi.fn(async () => undefined);
  const adoptSession = vi.fn(async () => undefined);
  const announce = vi.fn();
  const navigateTo = vi.fn(async () => undefined);

  g.$fetch = fetch;
  g.useRuntimeConfig = () => ({ public: { identityUrl: IDENTITY_URL } });
  g.useRoute = () => ({ query: options.query ?? {} });
  g.useRouter = () => ({ push, replace });
  g.useAnnounce = () => announce;
  // The whole of useAuth's surface the layer's own composables touch, not only the part
  // the recovery pages call, so a module under test can be typed against one shape.
  g.useAuth = () => ({ adoptSession, accessToken: ref<string | null>(null), logout: () => {} });
  g.navigateTo = navigateTo;

  return { fetch, push, replace, adoptSession, announce, navigateTo };
}

// The layer components a page reaches for by auto-import. Real ones, not stubs: a page
// that renders illegibly usually does so in the chrome, not in its own markup.
export const chrome = { Btn, Cross, Eyebrow, Icon, Mark, PasswordField, RuleTicks, RulerStrip, StatusDot, TopBar };

/** An HTTP failure shaped the way ofetch reports one, which is what the pages read. */
export function apiError(status: number, detail?: string) {
  return Object.assign(new Error(`HTTP ${status}`), { status, statusCode: status, data: detail ? { detail } : undefined });
}

/** A promise the test resolves by hand, for asserting on what renders mid-flight. */
export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}
