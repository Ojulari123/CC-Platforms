<script lang="ts">
import { safeNextPath } from "@crescent/ui/composables/useSSO";

/* Sign-in validation and the refusal copy, exported rather than left inside setup()
   because they are the behaviour of this screen and are tested directly. */

export const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export function emailError(value: string): string | null {
  if (value.length === 0) return "Enter your work email.";
  return EMAIL_RE.test(value) ? null : "That is not a valid email address.";
}

// Length only. Identity decides the rest, and a stricter rule here would lock out an
// account whose password predates the current ones.
export function passwordError(value: string): string | null {
  return value.length < 8 ? "Password must be at least 8 characters." : null;
}

function httpStatus(err: unknown): number | undefined {
  return (err as { statusCode?: number })?.statusCode ?? (err as { status?: number })?.status;
}

// One message for a wrong address and a wrong password: telling them apart is an
// account-enumeration oracle.
export function signInMessage(err: unknown): string {
  const status = httpStatus(err);
  if (status === 401) return "That email and password do not match an account.";
  if (status === 403) return "That account has been deactivated. A platform admin can turn it back on.";
  if (status === 429) return "Too many attempts from here. Wait a minute and try again.";
  return "Could not sign you in. Is the identity service running?";
}

/** The outbound leg of the cross-product handoff. `/auth/callback` comes from the shared
    layer and is the one address on Forge's SSO allowlist, so the round trip has to start
    from there: leaving from /login itself would be refused on the way back. */
export function handoffPath(next: string): string {
  return `/auth/callback?start=1&next=${encodeURIComponent(safeNextPath(next))}`;
}
</script>

<script setup lang="ts">
import { CTA_LINK, FOCUS, MONO_LABEL, TAP } from "@crescent/ui/utils/ui";
import type { Tone } from "@crescent/ui/types/ui";

/* Forge's front desk. Two ways in, in the order they should be taken: the handoff to
   identity first, because that is the one that leaves the password on the service that
   owns it, and the email/password form second for when the round trip cannot run. Both
   end at the same place — identity — so nothing here is a second account system. */

definePageMeta({ layout: false });

const auth = useAuth();
const route = useRoute();
const router = useRouter();
const announce = useAnnounce();

const email = ref("");
const password = ref("");
const touched = ref({ email: false, password: false });
const busy = ref(false);
const note = ref<string | null>(null);
const emailField = ref<HTMLInputElement | null>(null);

// Forge's own guard sends people here without a `next`, so this is usually "/" — it is
// read anyway so a link that carries one keeps working through both routes in.
const next = computed(() => safeNextPath(typeof route.query.next === "string" ? route.query.next : "/"));
const handoff = computed(() => handoffPath(next.value));

const emailErr = computed(() => emailError(email.value));
const passwordErr = computed(() => passwordError(password.value));
const showEmailErr = computed(() => touched.value.email && emailErr.value);
const showPasswordErr = computed(() => touched.value.password && passwordErr.value);
const blocked = computed(() => Boolean(emailErr.value || passwordErr.value));

const GUARANTEES: [string, string][] = [
  ["01", "One login, both products"],
  ["02", "Access token · 15 min"],
  ["03", "Password held only by identity"],
  ["04", "Verified against a public key"],
];

const FORGE_STATE: { tone: Tone; label: string }[] = [
  { tone: "ok", label: "Upload, preview and delete are live" },
  { tone: "muted", label: "Guided paths and canvas land in week 6" },
];

onMounted(() => {
  auth.hydrate();
  if (auth.isAuthenticated.value) {
    router.replace(next.value);
    return;
  }
  // Fine pointers and wide screens only: on a phone an autofocus pops the on-screen
  // keyboard over the page before anyone has decided to type.
  const coarse = window.matchMedia?.("(pointer: coarse)").matches ?? false;
  if (coarse || window.innerWidth < 768) return;
  emailField.value?.focus();
});

async function onSubmit() {
  // Enter in a field still submits a form whose only button is disabled, so the guard
  // against a second request lives here rather than on the control.
  if (busy.value) return;
  touched.value = { email: true, password: true };
  note.value = null;
  if (blocked.value) return;

  busy.value = true;
  try {
    await auth.login(email.value.trim(), password.value);
    announce("Signed in.");
    await router.push(next.value);
  } catch (err: unknown) {
    note.value = signInMessage(err);
  } finally {
    busy.value = false;
  }
}

useHead({ title: "Sign in · Forge" });
</script>

<template>
  <div class="w-full overflow-x-hidden">
    <TopBar :signed-in="false" breadcrumb="Forge" home-to="/" get-started-to="/signup" />
    <RulerStrip readout="session · not started" />

    <main id="main" class="relative mx-auto w-full max-w-[1200px] px-5 sm:px-8">
      <div class="grid lg:grid-cols-12">
        <!-- editorial column -->
        <div class="relative border-line-subtle py-12 lg:col-span-7 lg:border-l lg:py-20 lg:pl-10 lg:pr-14">
          <RuleTicks />
          <Cross class="absolute -left-[5px] -top-[5px] hidden lg:block" />

          <div class="sec flex items-center gap-3">
            <Eyebrow>Returning</Eyebrow>
            <span class="rule-draw h-px w-8 bg-line" style="animation-delay: 160ms" aria-hidden="true" />
            <span :class="[MONO_LABEL, 'text-ink-faint']">forge.meridian</span>
          </div>

          <h1
            class="sec mt-6 max-w-[16ch] text-[clamp(2rem,4.6vw,3.2rem)] font-semibold leading-[0.98] tracking-[-0.04em]"
            style="animation-delay: 40ms"
          >
            Sign in to Forge.<br />
            <span class="text-ink-muted">Identity keeps the password.</span>
          </h1>

          <div class="sec mt-8 flex max-w-[48ch] gap-5" style="animation-delay: 80ms">
            <span
              class="rule-draw mt-1 h-px w-8 shrink-0 bg-line-strong"
              style="animation-delay: 240ms"
              aria-hidden="true"
            />
            <p class="text-[14px] leading-relaxed text-ink-muted">
              Forge stores datasets and refers to you by an id. It has no accounts of its own: signing in
              through Meridian hands it one short-lived token, which is the whole of what it knows about
              you until that token expires.
            </p>
          </div>

          <ul class="sec mt-10 grid gap-px border-t border-line-subtle sm:grid-cols-2" style="animation-delay: 160ms">
            <li v-for="[n, t] in GUARANTEES" :key="n" class="flex items-baseline gap-2.5 border-b border-line-subtle py-3">
              <span class="mono text-[11px] text-ink-faint">{{ n }}</span>
              <span :class="[MONO_LABEL, 'text-ink-muted']">{{ t }}</span>
            </li>
          </ul>

          <ul class="sec mt-8 space-y-2" style="animation-delay: 200ms">
            <li v-for="row in FORGE_STATE" :key="row.label">
              <StatusDot :tone="row.tone" quiet>{{ row.label }}</StatusDot>
            </li>
          </ul>
        </div>

        <!-- form column -->
        <div
          class="sec relative border-line-subtle pb-16 lg:col-span-5 lg:border-l lg:py-20 lg:pl-10"
          style="animation-delay: 120ms"
        >
          <Cross class="absolute -left-[5px] -top-[5px] hidden lg:block" />

          <div class="flex items-center gap-2.5">
            <Mark />
            <div class="leading-none">
              <p class="text-[13px] font-medium tracking-tight">Meridian</p>
              <p :class="[MONO_LABEL, 'mt-1 text-ink-faint']">Forge</p>
            </div>
          </div>

          <!-- The way in that leaves the password where it belongs, so it leads. A link
               rather than a <Btn>: it is a navigation, and a navigation wearing a button
               loses middle-click and open-in-new-tab. -->
          <NuxtLink :to="handoff" :class="[CTA_LINK, FOCUS, TAP, 'mt-7']">
            <Icon name="shield" class="h-4 w-4" />
            Continue with Meridian
          </NuxtLink>
          <p class="mt-2.5 text-[12px] leading-relaxed text-ink-muted">
            Signs you in at identity and returns with a fifteen-minute access token. If you are already
            signed in to Pulse in this browser, it does not ask twice.
          </p>

          <div class="my-7 flex items-center gap-3">
            <span class="h-px flex-1 bg-line-subtle" aria-hidden="true" />
            <span :class="[MONO_LABEL, 'text-ink-muted']">or</span>
            <span class="h-px flex-1 bg-line-subtle" aria-hidden="true" />
          </div>

          <form class="space-y-4" novalidate @submit.prevent="onSubmit">
            <div>
              <label for="signin-email" :class="[MONO_LABEL, 'mb-1.5 block text-ink-muted']">Work email</label>
              <input
                id="signin-email"
                ref="emailField"
                v-model="email"
                name="email"
                type="email"
                autocomplete="email"
                spellcheck="false"
                placeholder="you@cyphercrescent.com"
                :aria-invalid="showEmailErr ? true : undefined"
                :aria-describedby="showEmailErr ? 'signin-email-err' : undefined"
                :class="[
                  'mono',
                  FOCUS,
                  TAP,
                  'w-full rounded-md bg-app px-3 py-2.5 text-[13px] text-ink ring-1 ring-inset transition-colors placeholder:text-ink-faint hover:ring-line-strong',
                  showEmailErr ? 'ring-bad' : 'ring-line',
                ]"
                @blur="touched.email = true"
              />
              <p
                v-if="showEmailErr"
                id="signin-email-err"
                role="alert"
                class="mt-1.5 rounded-md bg-bad-surface px-2.5 py-1.5 text-[12.5px] text-bad"
              >
                {{ emailErr }}
              </p>
            </div>

            <div>
              <PasswordField
                id="signin-password"
                v-model="password"
                name="password"
                label="Password"
                autocomplete="current-password"
                :invalid="Boolean(showPasswordErr)"
                :describedby="showPasswordErr ? 'signin-password-err' : 'signin-password-hint'"
                :busy="busy"
                @blur="touched.password = true"
              >
                <template #action>
                  <NuxtLink
                    to="/forgot-password"
                    :class="[FOCUS, 'rounded text-[11px] text-ink-muted transition-colors hover:text-ink']"
                  >
                    Forgot?
                  </NuxtLink>
                </template>
              </PasswordField>
              <p
                v-if="showPasswordErr"
                id="signin-password-err"
                role="alert"
                class="mt-1.5 rounded-md bg-bad-surface px-2.5 py-1.5 text-[12.5px] text-bad"
              >
                {{ passwordErr }}
              </p>
              <p v-else id="signin-password-hint" :class="[MONO_LABEL, 'mt-1.5 text-ink-muted']">min 8 characters</p>
            </div>

            <p
              v-if="note"
              role="alert"
              class="rounded-md bg-warn-surface px-3 py-2 text-[12.5px] leading-relaxed text-warn"
            >
              {{ note }}
            </p>

            <Btn type="submit" variant="secondary" full :busy="busy">
              {{ busy ? "Checking…" : "Sign in with a password" }}
            </Btn>
          </form>

          <p class="mt-6 text-[12px] leading-relaxed text-ink-muted">
            The password goes straight to identity and is never stored by Forge. No account yet?
            <NuxtLink to="/signup" :class="[FOCUS, 'rounded font-medium text-ink hover:text-ink-muted']">
              Create one
            </NuxtLink>
            — or accept the invitation your department admin sent you.
          </p>
        </div>
      </div>
    </main>

    <footer class="border-t border-line-subtle">
      <div class="mx-auto flex w-full max-w-[1200px] flex-wrap items-center justify-between gap-4 px-5 py-7 sm:px-8">
        <span :class="[MONO_LABEL, 'text-ink-muted']">Meridian · Forge</span>
        <span :class="[MONO_LABEL, 'text-ink-faint']">access token · 15 min</span>
      </div>
    </footer>
  </div>
</template>
