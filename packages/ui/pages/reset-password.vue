<script setup lang="ts">
import { CTA_LINK, CTA_LINK_SECONDARY, FOCUS, MONO_LABEL } from "../utils/ui";

/* The screen the emailed link opens. The token arrives in the query string and is never
   rendered in full — a shoulder or a screenshot is enough to spend it.

   A dead link is not one failure but three, and the advice differs each time, so the
   400 identity returns is sorted into a kind rather than printed as-is. All three route
   back to /forgot-password, because a fresh link is the only way forward from any of
   them. The password rules are usePasswordRules(), which mirrors validate_password() in
   the identity service — the server is still the authority. */

definePageMeta({ layout: false });

const config = useRuntimeConfig();
const route = useRoute();
const router = useRouter();
const announce = useAnnounce();

// PASSWORD_RESET_EXPIRE_MINUTES in services/identity/app/config.py.
const EXPIRY_MINUTES = 30;

const FACTS: [string, string][] = [
  ["01", "One-time token"],
  ["02", `Expires in ${EXPIRY_MINUTES} min`],
  ["03", "All sessions revoked"],
  ["04", "Hashed, never stored plain"],
];

type DeadKind = "invalid" | "expired" | "used";

const DEAD: Record<DeadKind, { eyebrow: string; headline: string; detail: string; advice: string }> = {
  invalid: {
    eyebrow: "Dead link",
    headline: "This link cannot be read",
    detail: "The token in this link does not match any reset request. Usually the link was cut short by an email client, or part of it was retyped.",
    advice: "Open the link straight from the email rather than copying it out. If it still fails, ask for a new one — nothing on the account has changed.",
  },
  expired: {
    eyebrow: "Expired",
    headline: "This link has expired",
    detail: `A reset link is good for ${EXPIRY_MINUTES} minutes and this one is older than that. Nothing was changed and the old password still works.`,
    advice: `Ask for a fresh link and open it within ${EXPIRY_MINUTES} minutes. The new link replaces this one entirely.`,
  },
  used: {
    eyebrow: "Spent",
    headline: "This link has already been used",
    detail: "A reset link works once and identity has no record of this one still being open — either a password was already set with it, or it was never valid.",
    advice: "If you set the password yourself, sign in with it. If you did not, ask for a new link now and change the password — somebody else may have opened this one.",
  },
};

const token = ref(typeof route.query.token === "string" ? route.query.token : "");
// Kept for the display fragment: `token` itself is emptied the moment it is spent.
const tokenSeen = ref(token.value);

const password = ref("");
const confirmPassword = ref("");
const touched = ref({ password: false, confirm: false });
const { rules, valid, lengthError } = usePasswordRules(password);

const errorMessage = ref<string | null>(null);
/* Terminal states: the link itself is unusable, so no amount of retrying helps. A link
   with no token in it at all is `invalid`, with its own wording — the generic detail
   would be describing a mismatch that never happened. */
const deadKind = ref<DeadKind | null>(token.value ? null : "invalid");
const deadDetail = ref<string | null>(
  token.value ? null : "This link has no token in it at all. Open the link straight from the email rather than retyping the address.",
);
const done = ref(false);
const submitting = ref(false);

const passwordField = ref<{ focus: () => void } | null>(null);
const doneNote = ref<HTMLElement | null>(null);

const dead = computed(() => (deadKind.value ? DEAD[deadKind.value] : null));
const detail = computed(() => deadDetail.value ?? dead.value?.detail ?? "");
// Eight characters is enough to tell two links apart in a support conversation and far
// too few to spend one.
const fragment = computed(() => (tokenSeen.value ? `${tokenSeen.value.slice(0, 8)}…` : "none"));

const passwordErr = computed(() => {
  if (!password.value) return "Choose a new password.";
  // The ceiling is not in the rule list, so it has to speak for itself when crossed.
  return lengthError.value ?? (valid.value ? null : "That password does not meet the rules below yet.");
});
const confirmErr = computed(() => {
  if (!confirmPassword.value) return "Type it a second time.";
  return confirmPassword.value === password.value ? null : "The two passwords do not match.";
});
const showPasswordErr = computed(() => touched.value.password && passwordErr.value);
const showConfirmErr = computed(() => touched.value.confirm && confirmErr.value);

const readout = computed(() => (done.value ? "password · changed" : deadKind.value ? "reset link · dead" : "password · reset"));

onMounted(() => {
  if (deadKind.value) {
    announce("This reset link cannot be used.");
    return;
  }
  const coarse = window.matchMedia?.("(pointer: coarse)").matches ?? false;
  if (coarse || window.innerWidth < 768) return;
  passwordField.value?.focus();
});

function serverDetail(err: unknown): string | null {
  const d = (err as { data?: { detail?: unknown } })?.data?.detail;
  return typeof d === "string" ? d : null;
}

/* identity's own wording, from services/identity/app/services/auth.py:
     "This reset link has expired, so request a new one"
     "Invalid or already-used reset link"
   The second covers two cases in one sentence on purpose; the `used` advice is written
   to cover both rather than guess. */
function classify(message: string | null): DeadKind {
  if (!message) return "invalid";
  if (/expired/i.test(message)) return "expired";
  if (/already[-\s]?used/i.test(message)) return "used";
  return "invalid";
}

function markDead(kind: DeadKind, message: string | null) {
  deadKind.value = kind;
  // The server sentence is only shown when it is more specific than the stock one.
  deadDetail.value = kind === "invalid" && message ? message : null;
  errorMessage.value = null;
  announce("This reset link cannot be used.");
}

async function onSubmit() {
  touched.value = { password: true, confirm: true };
  errorMessage.value = null;
  if (passwordErr.value || confirmErr.value) return;

  submitting.value = true;
  try {
    await $fetch(`${config.public.identityUrl}/auth/reset-password`, {
      method: "POST",
      body: { token: token.value, new_password: password.value },
    });
    token.value = "";
    password.value = "";
    confirmPassword.value = "";
    done.value = true;
    announce("Password changed. Every session was signed out.");
    // Drop the token from the address bar and this history entry once it's spent.
    router.replace({ query: {} });
    await nextTick();
    doneNote.value?.focus();
  } catch (err: unknown) {
    const status = (err as { statusCode?: number; status?: number })?.statusCode
      ?? (err as { status?: number })?.status;
    const message = serverDetail(err);
    if (status === 400 && message && /password/i.test(message)) {
      errorMessage.value = message;
    } else if (status === 400) {
      markDead(classify(message), message);
    } else if (status === 422) {
      errorMessage.value = "Password must be between 8 and 72 characters.";
    } else if (status === 429) {
      errorMessage.value = "Too many attempts. Wait a minute and try again.";
    } else {
      errorMessage.value = "Could not reset your password. Is the identity service running?";
    }
  } finally {
    submitting.value = false;
  }
}

useHead({ title: "Choose a new password" });
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
            <Eyebrow>{{ dead ? dead.eyebrow : done ? "Changed" : "New password" }}</Eyebrow>
            <span class="rule-draw h-px w-8 bg-line" style="animation-delay: 160ms" aria-hidden="true" />
            <span :class="[MONO_LABEL, 'text-ink-faint']">identity.meridian</span>
          </div>

          <h1
            class="sec mt-6 max-w-[16ch] text-[clamp(2rem,4.6vw,3.2rem)] font-semibold leading-[0.98] tracking-[-0.04em]"
            style="animation-delay: 40ms"
          >
            <template v-if="dead">
              This link is<br />
              <span class="text-ink-muted">finished.</span>
            </template>
            <template v-else-if="done">
              Done.<br />
              <span class="text-ink-muted">Every device signed out.</span>
            </template>
            <template v-else>
              One link,<br />
              <span class="text-ink-muted">one password, once.</span>
            </template>
          </h1>

          <div class="sec mt-8 flex max-w-[48ch] gap-5" style="animation-delay: 80ms">
            <span class="rule-draw mt-1 h-px w-8 shrink-0 bg-line-strong" style="animation-delay: 240ms" aria-hidden="true" />
            <p class="text-[14px] leading-relaxed text-ink-muted">
              Setting a password here revokes every refresh token on the account and bumps its token version, so every
              device you were signed in on has to sign in again. If it was not you who asked for this link, that is what
              stops whoever did.
            </p>
          </div>

          <ul class="sec mt-10 grid gap-px border-t border-line-subtle sm:grid-cols-2" style="animation-delay: 160ms">
            <li v-for="[n, t] in FACTS" :key="n" class="flex items-baseline gap-2.5 border-b border-line-subtle py-3">
              <span class="mono text-[12px] text-ink-faint">{{ n }}</span>
              <span :class="[MONO_LABEL, 'text-ink-muted']">{{ t }}</span>
            </li>
          </ul>

          <!-- A fragment, never the token. Enough to tell two links apart, useless to spend. -->
          <p class="mono mt-6 text-[12px] tracking-[0.08em] text-ink-muted">
            token {{ fragment }} · never shown in full
          </p>
        </div>

        <!-- form column -->
        <div class="sec relative border-line-subtle pb-16 lg:col-span-5 lg:border-l lg:py-20 lg:pl-10" style="animation-delay: 120ms">
          <Cross class="absolute -left-[5px] -top-[5px] hidden lg:block" />

          <div class="flex items-center gap-2.5">
            <Mark />
            <div class="leading-none">
              <p class="text-[13px] font-medium tracking-tight">Meridian</p>
              <p :class="[MONO_LABEL, 'mt-1 text-ink-faint']">Password reset</p>
            </div>
          </div>

          <div v-if="dead" class="mt-6" data-testid="dead">
            <h2 class="text-[17px] font-semibold tracking-tight">{{ dead.headline }}</h2>
            <div class="mt-3 flex items-start gap-2.5 rounded-md bg-warn-surface px-3 py-2.5">
              <span class="mt-0.5 shrink-0 text-warn"><Icon name="alert" class="h-3.5 w-3.5" /></span>
              <p role="alert" class="text-[12.5px] leading-relaxed text-ink">{{ detail }}</p>
            </div>
            <p class="mt-4 text-[13px] leading-relaxed text-ink-muted">{{ dead.advice }}</p>

            <div class="mt-6 space-y-2.5">
              <NuxtLink to="/forgot-password" :class="[FOCUS, CTA_LINK, 'group/cta']">
                Request a new link
                <Icon name="arrow" class="h-4 w-4 transition-transform group-hover/cta:translate-x-0.5" />
              </NuxtLink>
              <NuxtLink to="/login" :class="[FOCUS, CTA_LINK_SECONDARY]">Back to sign in</NuxtLink>
            </div>
          </div>

          <div v-else-if="done" class="mt-6">
            <h2 class="text-[17px] font-semibold tracking-tight">Password changed</h2>
            <p
              ref="doneNote"
              tabindex="-1"
              :class="[FOCUS, 'mt-3 rounded-md text-[13.5px] leading-relaxed text-ink-muted']"
            >
              Every session on the account was revoked, including any this link was not meant to reach. Sign in with the
              new password to start a fresh one.
            </p>
            <p class="mono mt-4 text-[12px] tracking-[0.08em] text-ink-muted">link spent · token discarded</p>

            <div class="mt-6">
              <NuxtLink to="/login" :class="[FOCUS, CTA_LINK, 'group/cta']">
                Sign in
                <Icon name="arrow" class="h-4 w-4 transition-transform group-hover/cta:translate-x-0.5" />
              </NuxtLink>
            </div>
          </div>

          <div v-else>
            <h2 class="mt-6 text-[17px] font-semibold tracking-tight">Choose a new password</h2>
            <p class="mt-2 text-[13.5px] leading-relaxed text-ink-muted">
              This link works once. Saving a new password signs you out on every device.
            </p>

            <form class="mt-6 space-y-4" novalidate @submit.prevent="onSubmit">
              <div>
                <PasswordField
                  id="reset-pw"
                  ref="passwordField"
                  v-model="password"
                  name="new-password"
                  label="New password"
                  tone="faint"
                  autocomplete="new-password"
                  :invalid="Boolean(showPasswordErr)"
                  :describedby="showPasswordErr ? 'reset-pw-err reset-pw-rules' : 'reset-pw-rules'"
                  :busy="submitting"
                  @blur="touched.password = true"
                />
                <p
                  v-if="showPasswordErr"
                  id="reset-pw-err"
                  role="alert"
                  class="mt-1.5 rounded-md bg-bad-surface px-2.5 py-1.5 text-[12.5px] leading-relaxed text-bad"
                >
                  {{ passwordErr }}
                </p>

                <!-- Live, so the rules answer as they are met rather than waiting for a
                     failed submit to list them. -->
                <ul id="reset-pw-rules" class="mt-2.5 space-y-1.5">
                  <li
                    v-for="rule in rules"
                    :key="rule.label"
                    :class="['flex items-center gap-2 text-[12px]', rule.met ? 'text-ok' : 'text-ink-muted']"
                  >
                    <Icon v-if="rule.met" name="check" class="h-3.5 w-3.5 shrink-0" />
                    <span v-else class="h-1.5 w-1.5 shrink-0 rounded-full bg-ink-faint" aria-hidden="true" />
                    <span>{{ rule.label }}</span>
                    <span class="sr-only">{{ rule.met ? " — met" : " — not met yet" }}</span>
                  </li>
                </ul>
              </div>

              <div>
                <PasswordField
                  id="reset-confirm"
                  v-model="confirmPassword"
                  name="confirm-password"
                  label="Confirm new password"
                  tone="faint"
                  autocomplete="new-password"
                  :invalid="Boolean(showConfirmErr)"
                  :describedby="showConfirmErr ? 'reset-confirm-err' : undefined"
                  :busy="submitting"
                  @blur="touched.confirm = true"
                />
                <p
                  v-if="showConfirmErr"
                  id="reset-confirm-err"
                  role="alert"
                  class="mt-1.5 rounded-md bg-bad-surface px-2.5 py-1.5 text-[12.5px] text-bad"
                >
                  {{ confirmErr }}
                </p>
              </div>

              <p
                v-if="errorMessage"
                role="alert"
                class="rounded-md bg-warn-surface px-3 py-2 text-[12.5px] leading-relaxed text-warn"
              >
                {{ errorMessage }}
              </p>

              <Btn type="submit" full arrow :busy="submitting">
                {{ submitting ? "Saving…" : "Set new password" }}
              </Btn>
            </form>

            <div class="mt-5 border-t border-line-subtle pt-4">
              <p class="text-[12.5px] leading-relaxed text-ink-muted">
                Landed here by mistake? Leaving without saving spends nothing — the link stays good until it expires.
              </p>
              <NuxtLink
                to="/login"
                :class="[FOCUS, 'group/b mt-2.5 inline-flex items-center gap-1.5 rounded text-[12px] font-medium text-ink transition-colors hover:text-ink-muted']"
              >
                <Icon name="arrowLeft" class="h-3.5 w-3.5 transition-transform group-hover/b:-translate-x-0.5" />
                Back to sign in
              </NuxtLink>
            </div>
          </div>
        </div>
      </div>
    </main>

    <footer class="border-t border-line-subtle">
      <div class="mx-auto flex w-full max-w-[1200px] flex-wrap items-center justify-between gap-4 px-5 py-7 sm:px-8">
        <NuxtLink
          to="/forgot-password"
          :class="[FOCUS, 'group/f inline-flex items-center gap-2 rounded text-[12.5px] text-ink-muted transition-colors hover:text-ink']"
        >
          <Icon name="arrowLeft" class="h-3.5 w-3.5 transition-transform group-hover/f:-translate-x-0.5" />
          Ask for another link
        </NuxtLink>
        <span :class="[MONO_LABEL, 'text-ink-faint']">max 72 characters · one use</span>
      </div>
    </footer>
  </div>
</template>
