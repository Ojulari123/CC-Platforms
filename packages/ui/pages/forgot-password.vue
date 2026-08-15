<script setup lang="ts">
import { CTA_LINK, FOCUS, MONO_LABEL } from "../utils/ui";

/* Recovery. The one screen here that is deliberately less helpful than it could be: it
   answers the same way whether or not the address has an account, because a different
   answer for a real address is a way of listing who works here. POST
   /auth/forgot-password returns 204 either way — this screen only mirrors what the
   service already refuses to say. */

definePageMeta({ layout: false });

const config = useRuntimeConfig();
const announce = useAnnounce();

// PASSWORD_RESET_EXPIRE_MINUTES in services/identity/app/config.py.
const EXPIRY_MINUTES = 30;

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

const FACTS: [string, string][] = [
  ["01", "One-time token"],
  ["02", `Expires in ${EXPIRY_MINUTES} min`],
  ["03", "Sent by email only"],
  ["04", "Same reply either way"],
];

const email = ref("");
const touched = ref(false);
const errorMessage = ref<string | null>(null);
const sent = ref(false);
// The address the request went out for, kept separately so editing the field afterwards
// does not rewrite what the confirmation says was asked for.
const sentTo = ref("");
const submitting = ref(false);

const emailField = ref<HTMLInputElement | null>(null);
const sentNote = ref<HTMLElement | null>(null);

const emailErr = computed(() => {
  const value = email.value.trim();
  if (!value) return "Enter the email you sign in with.";
  return EMAIL_RE.test(value) ? null : "That is not a valid email address.";
});
const showEmailErr = computed(() => touched.value && emailErr.value);

onMounted(() => {
  // Fine pointers and wide screens only: on a phone an autofocus pops the on-screen
  // keyboard over the page before anyone has decided to type.
  const coarse = window.matchMedia?.("(pointer: coarse)").matches ?? false;
  if (coarse || window.innerWidth < 768) return;
  emailField.value?.focus();
});

function serverDetail(err: unknown): string | null {
  const detail = (err as { data?: { detail?: unknown } })?.data?.detail;
  return typeof detail === "string" ? detail : null;
}

async function onSubmit() {
  touched.value = true;
  errorMessage.value = null;
  if (emailErr.value) return;

  const address = email.value.trim();
  submitting.value = true;
  try {
    await $fetch(`${config.public.identityUrl}/auth/forgot-password`, {
      method: "POST",
      body: { email: address },
    });
    sentTo.value = address;
    const first = !sent.value;
    sent.value = true;
    announce("Request sent. If that address has an account, a reset link is on its way.");
    if (first) {
      await nextTick();
      sentNote.value?.focus();
    }
  } catch (err: unknown) {
    const status = (err as { statusCode?: number; status?: number })?.statusCode
      ?? (err as { status?: number })?.status;
    if (status === 503) {
      // Server-wide email misconfiguration: same answer for every address, so
      // showing it still says nothing about whether this one has an account.
      errorMessage.value = serverDetail(err) ?? "Password reset email isn't configured on the server yet.";
    } else if (status === 429) {
      errorMessage.value = "That is identity's limit on this route. Wait a minute and ask again.";
    } else if (status === 422) {
      errorMessage.value = "Enter a valid email address.";
    } else {
      errorMessage.value = "Could not send the reset link. Is the identity service running?";
    }
  } finally {
    submitting.value = false;
  }
}

useHead({ title: "Reset your password" });
</script>

<template>
  <div class="w-full overflow-x-hidden bg-app font-sans text-ink">
    <TopBar :signed-in="false" home-to="/" sign-in-to="/login" />
    <RulerStrip :readout="sent ? 'reset · link requested' : 'reset · not requested'" />

    <main id="main" class="relative mx-auto w-full max-w-[1200px] px-5 sm:px-8">
      <div class="grid lg:grid-cols-12">
        <!-- editorial column -->
        <div class="relative border-line-subtle py-12 lg:col-span-7 lg:border-l lg:py-20 lg:pl-10 lg:pr-14">
          <RuleTicks />
          <Cross class="absolute -left-[5px] -top-[5px] hidden lg:block" />

          <div class="sec flex items-center gap-3">
            <Eyebrow>Recovery</Eyebrow>
            <span class="rule-draw h-px w-8 bg-line" style="animation-delay: 160ms" aria-hidden="true" />
            <span :class="[MONO_LABEL, 'text-ink-faint']">identity.meridian</span>
          </div>

          <h1
            class="sec mt-6 max-w-[16ch] text-[clamp(2rem,4.6vw,3.2rem)] font-semibold leading-[0.98] tracking-[-0.04em]"
            style="animation-delay: 40ms"
          >
            Nobody can read it<br />
            <span class="text-ink-muted">back to you.</span>
          </h1>

          <div class="sec mt-8 flex max-w-[48ch] gap-5" style="animation-delay: 80ms">
            <span class="rule-draw mt-1 h-px w-8 shrink-0 bg-line-strong" style="animation-delay: 240ms" aria-hidden="true" />
            <p class="text-[14px] leading-relaxed text-ink-muted">
              Passwords are stored as a hash and never in a form anything can reverse — not an admin, not the database, not
              this screen. Recovery is the only route back in, and it works by proving you can open the mailbox.
            </p>
          </div>

          <ul class="sec mt-10 grid gap-px border-t border-line-subtle sm:grid-cols-2" style="animation-delay: 160ms">
            <li v-for="[n, t] in FACTS" :key="n" class="flex items-baseline gap-2.5 border-b border-line-subtle py-3">
              <span class="mono text-[11px] text-ink-faint">{{ n }}</span>
              <span :class="[MONO_LABEL, 'text-ink-muted']">{{ t }}</span>
            </li>
          </ul>

          <p class="sec mt-7 max-w-[52ch] text-[12.5px] leading-relaxed text-ink-muted" style="animation-delay: 200ms">
            The reply is identical for an address that has an account and one that does not. That is not evasiveness —
            telling the two apart is how somebody works out who has a login here without ever needing a password.
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

          <div v-if="sent" class="mt-6">
            <h2 class="text-[17px] font-semibold tracking-tight">Check your email</h2>
            <!-- Says nothing about whether that address has an account. -->
            <p
              ref="sentNote"
              tabindex="-1"
              :class="[FOCUS, 'mt-3 rounded-md text-[13.5px] leading-relaxed text-ink-muted']"
            >
              If that address has an account, a link is on its way. It expires {{ EXPIRY_MINUTES }} minutes after it is
              sent and works once. Check the spam folder before assuming it never arrived.
            </p>
            <p class="mono mt-4 text-[11px] tracking-[0.08em] text-ink-muted">requested for {{ sentTo }}</p>

            <div class="mt-6 space-y-2.5">
              <NuxtLink to="/login" :class="[FOCUS, CTA_LINK, 'group/cta']">
                Back to sign in
                <Icon name="arrow" class="h-4 w-4 transition-transform group-hover/cta:translate-x-0.5" />
              </NuxtLink>
              <Btn full variant="secondary" :busy="submitting" @click="onSubmit">
                {{ submitting ? "Sending…" : "Send it again" }}
              </Btn>
            </div>

            <p
              v-if="errorMessage"
              role="alert"
              class="mt-3 rounded-md bg-warn-surface px-3 py-2 text-[12.5px] leading-relaxed text-warn"
            >
              {{ errorMessage }}
            </p>
          </div>

          <div v-else>
            <h2 class="mt-6 text-[17px] font-semibold tracking-tight">Send a reset link</h2>
            <p class="mt-2 text-[13.5px] leading-relaxed text-ink-muted">
              Give us the email you sign in with and we will send a link that lets you choose a new password.
            </p>

            <form class="mt-6 space-y-4" novalidate @submit.prevent="onSubmit">
              <div>
                <label for="forgot-email" :class="[MONO_LABEL, 'mb-1.5 block text-ink-faint']">Work email</label>
                <input
                  id="forgot-email"
                  ref="emailField"
                  v-model="email"
                  name="email"
                  type="email"
                  autocomplete="email"
                  spellcheck="false"
                  placeholder="you@cyphercrescent.com"
                  :aria-invalid="showEmailErr ? true : undefined"
                  :aria-describedby="showEmailErr ? 'forgot-email-err' : 'forgot-email-hint'"
                  :class="['mono', FOCUS, 'w-full rounded-md bg-app px-3 py-2.5 text-[13px] text-ink ring-1 ring-inset transition-colors placeholder:text-ink-faint hover:ring-line-strong', showEmailErr ? 'ring-bad' : 'ring-line']"
                  @blur="touched = true"
                />
                <p
                  v-if="showEmailErr"
                  id="forgot-email-err"
                  role="alert"
                  class="mt-1.5 rounded-md bg-bad-surface px-2.5 py-1.5 text-[12.5px] text-bad"
                >
                  {{ emailErr }}
                </p>
                <p v-else id="forgot-email-hint" class="mono mt-1.5 text-[11px] tracking-[0.08em] text-ink-muted">
                  link expires in {{ EXPIRY_MINUTES }} min · one use
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
                {{ submitting ? "Sending…" : "Send reset link" }}
              </Btn>
            </form>

            <div class="mt-5 border-t border-line-subtle pt-4">
              <p class="text-[12.5px] leading-relaxed text-ink-muted">Remembered it after all?</p>
              <NuxtLink
                to="/login"
                :class="[FOCUS, 'group/b mt-2.5 inline-flex items-center gap-1.5 rounded text-[12px] font-medium text-ink transition-colors hover:text-ink-muted']"
              >
                <Icon name="arrowLeft" class="h-3.5 w-3.5 transition-transform group-hover/b:-translate-x-0.5" />
                Back to sign in
              </NuxtLink>
            </div>

            <p class="mt-6 text-[11px] leading-relaxed text-ink-muted">
              Never had an account? Accounts here are created by an invite from a department admin, so a reset link will
              not make one.
            </p>
          </div>
        </div>
      </div>
    </main>

    <footer class="border-t border-line-subtle">
      <div class="mx-auto flex w-full max-w-[1200px] flex-wrap items-center justify-between gap-4 px-5 py-7 sm:px-8">
        <NuxtLink
          to="/login"
          :class="[FOCUS, 'group/f inline-flex items-center gap-2 rounded text-[12.5px] text-ink-muted transition-colors hover:text-ink']"
        >
          <Icon name="arrowLeft" class="h-3.5 w-3.5 transition-transform group-hover/f:-translate-x-0.5" />
          Back to sign in
        </NuxtLink>
        <span :class="[MONO_LABEL, 'text-ink-faint']">reset token · {{ EXPIRY_MINUTES }} min · one use</span>
      </div>
    </footer>
  </div>
</template>
