<script lang="ts">
import { safeNextPath } from "@crescent/ui/composables/useSSO";

/* The create-account rules and the refusal copy, exported rather than left inside
   setup() because they are the behaviour of this screen and are tested directly. */

export const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export function emailError(value: string): string | null {
  if (value.length === 0) return "Enter your work email.";
  return EMAIL_RE.test(value) ? null : "That is not a valid email address.";
}

export function nameError(value: string, label: string): string | null {
  return value.trim().length === 0 ? `A ${label} is required.` : null;
}

function httpStatus(err: unknown): number | undefined {
  return (err as { statusCode?: number })?.statusCode ?? (err as { status?: number })?.status;
}

// FastAPI puts the human-readable reason in `detail`; on a 422 it is a list of field
// errors instead, which is not worth showing raw.
function serverDetail(err: unknown): string | null {
  const detail = (err as { data?: { detail?: unknown } })?.data?.detail;
  return typeof detail === "string" ? detail : null;
}

/** A 409 is the one refusal with an obvious next move, so the screen offers it. */
export function isEmailTaken(err: unknown): boolean {
  return httpStatus(err) === 409;
}

export function signUpMessage(err: unknown): string {
  const status = httpStatus(err);
  const detail = serverDetail(err);
  // Identity can restrict signup to specific email domains.
  if (status === 403) return detail ?? "Sign-ups aren't open to that email domain.";
  if (status === 409) return detail ?? "An account with that email already exists.";
  if (status === 400) return detail ?? "That password doesn't meet the requirements.";
  if (status === 422) return "Check the details above and try again.";
  if (status === 429) return "Too many attempts. Wait a minute and try again.";
  return "Could not create your account. Is the identity service running?";
}

/** The outbound leg of the cross-product handoff. `/auth/callback` is the one address on
    Forge's SSO allowlist, so the round trip starts there rather than from this page. */
export function handoffPath(next: string): string {
  return `/auth/callback?start=1&next=${encodeURIComponent(safeNextPath(next))}`;
}
</script>

<script setup lang="ts">
import { CTA_LINK, FOCUS, MONO_LABEL, TAP } from "@crescent/ui/utils/ui";
import type { Tone } from "@crescent/ui/types/ui";

/* Creating an account, from Forge's side. The account itself is made by identity either
   way — the handoff sends you to make it where it lives, and the form below posts to the
   same service without Forge keeping anything. The rules listed under the password field
   are identity's validate_password(), mirrored so nobody guesses at a 400. */

definePageMeta({ layout: false });

const auth = useAuth();
const route = useRoute();
const router = useRouter();
const announce = useAnnounce();

const first = ref("");
const last = ref("");
const email = ref("");
const password = ref("");
const touched = ref({ first: false, last: false, email: false, password: false });
const busy = ref(false);
const note = ref<string | null>(null);
const emailTaken = ref(false);
const firstField = ref<HTMLInputElement | null>(null);

const { rules, valid: passwordMeetsRules, lengthError } = usePasswordRules(password);

const next = computed(() => safeNextPath(typeof route.query.next === "string" ? route.query.next : "/"));
const handoff = computed(() => handoffPath(next.value));

const firstErr = computed(() => nameError(first.value, "first name"));
const lastErr = computed(() => nameError(last.value, "last name"));
const emailErr = computed(() => emailError(email.value));
const passwordErr = computed(() => {
  if (password.value.length === 0) return "Choose a password.";
  // The ceiling is not in the rule list, so it has to speak for itself when crossed.
  return lengthError.value ?? (passwordMeetsRules.value ? null : "That password does not meet the rules below yet.");
});

const showFirstErr = computed(() => touched.value.first && firstErr.value);
const showLastErr = computed(() => touched.value.last && lastErr.value);
const showEmailErr = computed(() => touched.value.email && emailErr.value);
const showPasswordErr = computed(() => touched.value.password && passwordErr.value);

const blocked = computed(() => Boolean(firstErr.value || lastErr.value || emailErr.value || passwordErr.value));

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
  firstField.value?.focus();
});

async function onSubmit() {
  // Enter in a field still submits a form whose only button is disabled, so the guard
  // against a second request lives here rather than on the control.
  if (busy.value) return;
  touched.value = { first: true, last: true, email: true, password: true };
  note.value = null;
  emailTaken.value = false;
  if (blocked.value) return;

  busy.value = true;
  try {
    await auth.signup({
      first_name: first.value.trim(),
      last_name: last.value.trim(),
      email: email.value.trim(),
      password: password.value,
    });
    announce("Account created. Signed in.");
    await router.push(next.value);
  } catch (err: unknown) {
    emailTaken.value = isEmailTaken(err);
    note.value = signUpMessage(err);
  } finally {
    busy.value = false;
  }
}

useHead({ title: "Create account · Forge" });
</script>

<template>
  <div class="w-full overflow-x-hidden">
    <TopBar :signed-in="false" breadcrumb="Forge" home-to="/" sign-in-to="/login" />
    <RulerStrip readout="account · new" />

    <main id="main" class="relative mx-auto w-full max-w-[1200px] px-5 sm:px-8">
      <div class="grid lg:grid-cols-12">
        <!-- editorial column -->
        <div class="relative border-line-subtle py-12 lg:col-span-7 lg:border-l lg:py-20 lg:pl-10 lg:pr-14">
          <RuleTicks />
          <Cross class="absolute -left-[5px] -top-[5px] hidden lg:block" />

          <div class="sec flex items-center gap-3">
            <Eyebrow>New account</Eyebrow>
            <span class="rule-draw h-px w-8 bg-line" style="animation-delay: 160ms" aria-hidden="true" />
            <span :class="[MONO_LABEL, 'text-ink-faint']">forge.meridian</span>
          </div>

          <h1
            class="sec mt-6 max-w-[16ch] text-[clamp(2rem,4.6vw,3.2rem)] font-semibold leading-[0.98] tracking-[-0.04em]"
            style="animation-delay: 40ms"
          >
            Create it once.<br />
            <span class="text-ink-muted">Use it in both products.</span>
          </h1>

          <div class="sec mt-8 flex max-w-[48ch] gap-5" style="animation-delay: 80ms">
            <span
              class="rule-draw mt-1 h-px w-8 shrink-0 bg-line-strong"
              style="animation-delay: 240ms"
              aria-hidden="true"
            />
            <p class="text-[14px] leading-relaxed text-ink-muted">
              The account is made by Meridian Identity, not by Forge, and the same one opens Pulse. You
              are signed in as soon as it exists; a department admin places you in a department after
              that, which is what decides who else can see your work.
            </p>
          </div>

          <ul class="sec mt-10 grid gap-px border-t border-line-subtle sm:grid-cols-2" style="animation-delay: 160ms">
            <li v-for="[n, t] in GUARANTEES" :key="n" class="flex items-baseline gap-2.5 border-b border-line-subtle py-3">
              <span class="mono text-[12px] text-ink-faint">{{ n }}</span>
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

          <!-- Leads, because it makes the account on the service that owns accounts. A
               link rather than a <Btn>: it is a navigation, and a navigation wearing a
               button loses middle-click and open-in-new-tab. -->
          <NuxtLink :to="handoff" :class="[CTA_LINK, FOCUS, TAP, 'mt-7']">
            <Icon name="shield" class="h-4 w-4" />
            Create it at Meridian
          </NuxtLink>
          <p class="mt-2.5 text-[12px] leading-relaxed text-ink-muted">
            Opens identity, where the Create account tab makes it and sends you back here signed in.
            An invitation link from your admin does the same thing in one step.
          </p>

          <div class="my-7 flex items-center gap-3">
            <span class="h-px flex-1 bg-line-subtle" aria-hidden="true" />
            <span :class="[MONO_LABEL, 'text-ink-muted']">or</span>
            <span class="h-px flex-1 bg-line-subtle" aria-hidden="true" />
          </div>

          <form class="space-y-4" novalidate @submit.prevent="onSubmit">
            <div class="grid gap-4 sm:grid-cols-2">
              <div>
                <label for="signup-first" :class="[MONO_LABEL, 'mb-1.5 block text-ink-muted']">First name</label>
                <input
                  id="signup-first"
                  ref="firstField"
                  v-model="first"
                  name="given-name"
                  type="text"
                  autocomplete="given-name"
                  spellcheck="false"
                  :aria-invalid="showFirstErr ? true : undefined"
                  :aria-describedby="showFirstErr ? 'signup-first-err' : undefined"
                  :class="[
                    FOCUS,
                    TAP,
                    'w-full rounded-md bg-app px-3 py-2.5 text-[13px] text-ink ring-1 ring-inset transition-colors hover:ring-line-strong',
                    showFirstErr ? 'ring-bad' : 'ring-line',
                  ]"
                  @blur="touched.first = true"
                />
                <p
                  v-if="showFirstErr"
                  id="signup-first-err"
                  role="alert"
                  class="mt-1.5 rounded-md bg-bad-surface px-2.5 py-1.5 text-[12.5px] text-bad"
                >
                  {{ firstErr }}
                </p>
              </div>
              <div>
                <label for="signup-last" :class="[MONO_LABEL, 'mb-1.5 block text-ink-muted']">Last name</label>
                <input
                  id="signup-last"
                  v-model="last"
                  name="family-name"
                  type="text"
                  autocomplete="family-name"
                  spellcheck="false"
                  :aria-invalid="showLastErr ? true : undefined"
                  :aria-describedby="showLastErr ? 'signup-last-err' : undefined"
                  :class="[
                    FOCUS,
                    TAP,
                    'w-full rounded-md bg-app px-3 py-2.5 text-[13px] text-ink ring-1 ring-inset transition-colors hover:ring-line-strong',
                    showLastErr ? 'ring-bad' : 'ring-line',
                  ]"
                  @blur="touched.last = true"
                />
                <p
                  v-if="showLastErr"
                  id="signup-last-err"
                  role="alert"
                  class="mt-1.5 rounded-md bg-bad-surface px-2.5 py-1.5 text-[12.5px] text-bad"
                >
                  {{ lastErr }}
                </p>
              </div>
            </div>

            <div>
              <label for="signup-email" :class="[MONO_LABEL, 'mb-1.5 block text-ink-muted']">Work email</label>
              <input
                id="signup-email"
                v-model="email"
                name="email"
                type="email"
                autocomplete="email"
                spellcheck="false"
                placeholder="you@cyphercrescent.com"
                :aria-invalid="showEmailErr ? true : undefined"
                :aria-describedby="showEmailErr ? 'signup-email-err' : undefined"
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
                id="signup-email-err"
                role="alert"
                class="mt-1.5 rounded-md bg-bad-surface px-2.5 py-1.5 text-[12.5px] text-bad"
              >
                {{ emailErr }}
              </p>
            </div>

            <div>
              <PasswordField
                id="signup-password"
                v-model="password"
                name="password"
                label="Password"
                autocomplete="new-password"
                :invalid="Boolean(showPasswordErr)"
                :describedby="showPasswordErr ? 'signup-password-err signup-password-rules' : 'signup-password-rules'"
                :busy="busy"
                @blur="touched.password = true"
              />
              <p
                v-if="showPasswordErr"
                id="signup-password-err"
                role="alert"
                class="mt-1.5 rounded-md bg-bad-surface px-2.5 py-1.5 text-[12.5px] text-bad"
              >
                {{ passwordErr }}
              </p>

              <!-- The server runs validate_password(), so anything looser here just
                   produces a surprise 400. -->
              <ul id="signup-password-rules" class="mt-2.5 grid gap-1.5">
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

            <div
              v-if="note"
              role="alert"
              class="rounded-md bg-warn-surface px-3 py-2 text-[12.5px] leading-relaxed text-warn"
            >
              <p>{{ note }}</p>
              <NuxtLink
                v-if="emailTaken"
                to="/login"
                :class="[FOCUS, 'mt-1 inline-block rounded font-medium underline underline-offset-2']"
              >
                Sign in instead
              </NuxtLink>
            </div>

            <Btn type="submit" variant="secondary" full :busy="busy">
              {{ busy ? "Creating…" : "Create account with a password" }}
            </Btn>
          </form>

          <p class="mt-6 text-[12px] leading-relaxed text-ink-muted">
            The password goes straight to identity and is never stored by Forge. Already have an account?
            <NuxtLink to="/login" :class="[FOCUS, 'rounded font-medium text-ink hover:text-ink-muted']">
              Sign in
            </NuxtLink>
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
