<script lang="ts">
import { httpStatus } from "~/utils/format";

/* Identity — confirm an email change.

   The screen the emailed link opens. The token in the query string is the whole
   credential — there is no Authorization header on this call and no button to press,
   because arriving here *is* the confirmation. It is never rendered in full: a shoulder
   or a screenshot is enough to spend it.

   A dead link is several failures wearing one status code, and the advice differs each
   time, so the 400 identity returns is sorted into a kind rather than printed as-is.

   Succeeding revokes every refresh family on the account and bumps its token version, so
   the tokens this browser is holding are already dead when the 204 arrives. Clearing them
   here is what stops the next screen 401ing on a session that no longer exists. */

export type ConfirmState = "working" | "done" | "missing" | "expired" | "invalid" | "taken" | "limited" | "failed";

export interface ConfirmCopy {
  eyebrow: string;
  heading: string;
  tail: string;
  title: string;
  message: string;
}

export const CONFIRM_COPY: Record<ConfirmState, ConfirmCopy> = {
  working: {
    eyebrow: "Confirming",
    heading: "Reading the link,",
    tail: "then moving the address.",
    title: "One moment",
    message: "Confirming your new email address…",
  },
  done: {
    eyebrow: "Updated",
    heading: "Done.",
    tail: "Every device signed out.",
    title: "Email updated",
    message: "Your sign-in email has been updated. For security, we signed you out everywhere — sign in again with your new address.",
  },
  missing: {
    eyebrow: "No token",
    heading: "This link is",
    tail: "incomplete.",
    title: "This link has no token in it",
    message: "This link has no token in it at all. Open the link straight from the email rather than retyping the address, then request the change again from your account page.",
  },
  expired: {
    eyebrow: "Expired",
    heading: "This link is",
    tail: "finished.",
    title: "This link has expired",
    message: "This link has expired. Request the change again from your account page.",
  },
  invalid: {
    eyebrow: "Dead link",
    heading: "This link is",
    tail: "finished.",
    title: "This link is no longer valid",
    message: "This link is no longer valid. It may have already been used, replaced by a newer request, or cancelled by a password change. Request the change again.",
  },
  taken: {
    eyebrow: "Taken",
    heading: "That address",
    tail: "belongs to someone else.",
    title: "That address is no longer free",
    message: "That address now belongs to another account, so we couldn't move your sign-in email.",
  },
  limited: {
    eyebrow: "Slow down",
    heading: "Too many",
    tail: "attempts.",
    title: "Too many attempts",
    message: "Too many attempts. Wait a minute and try again, then open the link once more.",
  },
  failed: {
    eyebrow: "No answer",
    heading: "Could not reach",
    tail: "identity.",
    title: "Could not confirm the change",
    message: "Nothing on the account has changed. Open the link again in a moment; it stays good until it expires.",
  },
};

/* identity's own wording, from services/identity/app/services/auth.py:
     "This confirmation link has expired, so request the change again"
     "Invalid or already-used confirmation link"
   The second covers unknown, spent, superseded, deactivated and cancelled-by-a-password-
   change in one sentence, so its advice is written to cover all five rather than guess. */
export function confirmState(status: number | undefined, detail: string | null): ConfirmState {
  if (status === 400) return detail && /expired/i.test(detail) ? "expired" : "invalid";
  if (status === 409) return "taken";
  // The 429 body puts its sentence under `error` rather than `detail`; nothing here reads
  // it, so the shape does not matter.
  if (status === 429) return "limited";
  return "failed";
}

function serverDetail(err: unknown): string | null {
  const d = (err as { data?: { detail?: unknown } })?.data?.detail;
  return typeof d === "string" ? d : null;
}

/** The whole confirmation, with its two effects handed in so the page and its test run
    the same code. A blank token never reaches the server, and the stored session is only
    cleared once identity has actually made the swap. */
export async function runConfirm(
  deps: { post: (token: string) => Promise<unknown>; clearSession: () => void },
  token: string,
): Promise<ConfirmState> {
  if (!token.trim()) return "missing";
  try {
    await deps.post(token);
  } catch (err: unknown) {
    return confirmState(httpStatus(err), serverDetail(err));
  }
  deps.clearSession();
  return "done";
}

/** States where opening the link again could still work, so the token stays in the URL. */
export function isRetryable(state: ConfirmState): boolean {
  return state === "limited" || state === "failed";
}
</script>

<script setup lang="ts">
import { CTA_LINK, CTA_LINK_SECONDARY, FOCUS, MONO_LABEL } from "@crescent/ui/utils/ui";

definePageMeta({ layout: false });

// EMAIL_CHANGE_EXPIRE_MINUTES in services/identity/app/config.py.
const EXPIRY_MINUTES = 30;

const FACTS: [string, string][] = [
  ["01", "One-time token"],
  ["02", `Expires in ${EXPIRY_MINUTES} min`],
  ["03", "All sessions revoked"],
  ["04", "Old address notified"],
];

const config = useRuntimeConfig();
const route = useRoute();
const router = useRouter();
const auth = useAuth();
const announce = useAnnounce();

const token = ref(typeof route.query.token === "string" ? route.query.token : "");
// Kept for the display fragment: `token` itself is emptied once it has been spent.
const tokenSeen = ref(token.value);
const state = ref<ConfirmState>(token.value.trim() ? "working" : "missing");
const panel = ref<HTMLElement | null>(null);

const copy = computed(() => CONFIRM_COPY[state.value]);
const settled = computed(() => state.value !== "working");
// Eight characters is enough to tell two links apart in a support conversation and far
// too few to spend one.
const fragment = computed(() => (tokenSeen.value ? `${tokenSeen.value.slice(0, 8)}…` : "none"));
const readout = computed(() =>
  state.value === "working" ? "email · confirming" : state.value === "done" ? "email · updated" : "email · link dead",
);

onMounted(async () => {
  if (state.value === "missing") {
    announce(CONFIRM_COPY.missing.message);
    return;
  }

  state.value = await runConfirm(
    {
      post: (raw) =>
        $fetch(`${config.public.identityUrl}/auth/confirm-email-change`, { method: "POST", body: { token: raw } }),
      // Every session is dead server-side by now, so anything still held here would only
      // 401 on the next call. useAuth().logout() drops both tokens and the cached user.
      clearSession: () => auth.logout(),
    },
    token.value,
  );

  if (!isRetryable(state.value)) {
    token.value = "";
    // Drop the token from the address bar and this history entry once it is spent.
    router.replace({ query: {} });
  }

  announce(copy.value.message);
  await nextTick();
  panel.value?.focus();
});

useHead({ title: "Confirm your new email address" });
</script>

<template>
  <div class="w-full overflow-x-hidden bg-app font-sans text-ink">
    <TopBar :signed-in="false" home-to="/" sign-in-to="/login" />
    <RulerStrip :readout="readout" />

    <main id="main" class="relative mx-auto w-full max-w-[1200px] px-5 sm:px-8">
      <div class="grid lg:grid-cols-12">
        <!-- editorial column -->
        <div class="relative border-line-subtle py-12 lg:col-span-7 lg:border-l lg:py-20 lg:pl-10 lg:pr-14">
          <RuleTicks />
          <Cross class="absolute -left-[5px] -top-[5px] hidden lg:block" />

          <div class="sec flex items-center gap-3">
            <Eyebrow>{{ copy.eyebrow }}</Eyebrow>
            <span class="rule-draw h-px w-8 bg-line" style="animation-delay: 160ms" aria-hidden="true" />
            <span :class="[MONO_LABEL, 'text-ink-faint']">identity.meridian</span>
          </div>

          <h1
            class="sec mt-6 max-w-[16ch] text-[clamp(2rem,4.6vw,3.2rem)] font-semibold leading-[0.98] tracking-[-0.04em]"
            style="animation-delay: 40ms"
          >
            {{ copy.heading }}<br />
            <span class="text-ink-muted">{{ copy.tail }}</span>
          </h1>

          <div class="sec mt-8 flex max-w-[48ch] gap-5" style="animation-delay: 80ms">
            <span class="rule-draw mt-1 h-px w-8 shrink-0 bg-line-strong" style="animation-delay: 240ms" aria-hidden="true" />
            <p class="text-[14px] leading-relaxed text-ink-muted">
              Moving the address moves the whole account: it is the handle you sign in with and where a reset link goes.
              Identity revokes every refresh token and bumps the account's token version as it makes the swap, so every
              device has to sign in again under the new address.
            </p>
          </div>

          <ul class="sec mt-10 grid gap-px border-t border-line-subtle sm:grid-cols-2" style="animation-delay: 160ms">
            <li v-for="[n, t] in FACTS" :key="n" class="flex items-baseline gap-2.5 border-b border-line-subtle py-3">
              <span class="mono text-[12px] text-ink-faint">{{ n }}</span>
              <span :class="[MONO_LABEL, 'text-ink-muted']">{{ t }}</span>
            </li>
          </ul>

          <!-- A fragment, never the token. Enough to tell two links apart, useless to spend. -->
          <p class="mono mt-6 text-[12px] tracking-[0.08em] text-ink-muted">token {{ fragment }} · never shown in full</p>
        </div>

        <!-- outcome column -->
        <div
          class="sec relative border-line-subtle pb-16 lg:col-span-5 lg:border-l lg:py-20 lg:pl-10"
          style="animation-delay: 120ms"
        >
          <Cross class="absolute -left-[5px] -top-[5px] hidden lg:block" />

          <div class="flex items-center gap-2.5">
            <Mark />
            <div class="leading-none">
              <p class="text-[13px] font-medium tracking-tight">Meridian</p>
              <p :class="[MONO_LABEL, 'mt-1 text-ink-faint']">Email change</p>
            </div>
          </div>

          <div class="mt-6" :data-testid="`state-${state}`">
            <h2 class="text-[17px] font-semibold tracking-tight">{{ copy.title }}</h2>

            <!-- In flight. Nothing to press: arriving here is the confirmation. -->
            <p
              v-if="state === 'working'"
              role="status"
              class="mt-3 flex items-center gap-2.5 text-[13.5px] leading-relaxed text-ink-muted"
            >
              <span class="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-ink-faint" aria-hidden="true" />
              {{ copy.message }}
            </p>

            <p
              v-else-if="state === 'done'"
              ref="panel"
              tabindex="-1"
              role="status"
              :class="[FOCUS, 'mt-3 rounded text-[13.5px] leading-relaxed text-ink-muted']"
            >
              {{ copy.message }}
            </p>

            <div v-else class="mt-3 flex items-start gap-2.5 rounded-md bg-warn-surface px-3 py-2.5">
              <span class="mt-0.5 shrink-0 text-warn"><Icon name="alert" class="h-3.5 w-3.5" /></span>
              <p ref="panel" tabindex="-1" role="alert" :class="[FOCUS, 'rounded text-[12.5px] leading-relaxed text-ink']">
                {{ copy.message }}
              </p>
            </div>

            <p v-if="state === 'done'" class="mono mt-4 text-[12px] tracking-[0.08em] text-ink-muted">
              link spent · sessions revoked
            </p>

            <div v-if="settled" class="mt-6 space-y-2.5">
              <NuxtLink to="/login" :class="[FOCUS, CTA_LINK, 'group/cta']">
                Go to sign in
                <Icon name="arrow" class="h-4 w-4 transition-transform group-hover/cta:translate-x-0.5" />
              </NuxtLink>
              <NuxtLink v-if="state !== 'done'" to="/account" :class="[FOCUS, CTA_LINK_SECONDARY]">
                Back to your account
              </NuxtLink>
            </div>

            <p v-if="state === 'done'" class="mt-5 border-t border-line-subtle pt-4 text-[12.5px] leading-relaxed text-ink-muted">
              Your old address was told the change happened. If it was not you who asked for this, sign in and change your
              password — that revokes everything again.
            </p>
          </div>
        </div>
      </div>
    </main>

    <footer class="border-t border-line-subtle">
      <div class="mx-auto flex w-full max-w-[1200px] flex-wrap items-center justify-between gap-4 px-5 py-7 sm:px-8">
        <NuxtLink
          to="/account"
          :class="[FOCUS, 'group/f inline-flex items-center gap-2 rounded text-[12.5px] text-ink-muted transition-colors hover:text-ink']"
        >
          <Icon name="arrowLeft" class="h-3.5 w-3.5 transition-transform group-hover/f:-translate-x-0.5" />
          Your account
        </NuxtLink>
        <span :class="[MONO_LABEL, 'text-ink-faint']">one use · 30 min</span>
      </div>
    </footer>
  </div>
</template>
