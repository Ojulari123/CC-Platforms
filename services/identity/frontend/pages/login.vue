<script setup lang="ts">
import { FOCUS, MONO_LABEL } from "@crescent/ui/utils/ui";
import type { TabItem } from "@crescent/ui/types/ui";
import { TRUST } from "~/utils/site";

/* The front desk. A screen rather than a modal, because signing in is a place you go —
   and because whatever you were trying to open is waiting behind it. */

definePageMeta({ layout: false });

const auth = useAuth();
const route = useRoute();
const router = useRouter();
const announce = useAnnounce();
const { label: signingKey } = useSigningKey();

const tab = ref<"signin" | "signup">(route.query.mode === "signup" ? "signup" : "signin");
const email = ref("");
const password = ref("");
const first = ref("");
const last = ref("");
const touched = ref({ email: false, password: false, first: false, last: false });
const busy = ref(false);
const note = ref<string | null>(null);
const emailField = ref<HTMLInputElement | null>(null);

const { rules, valid: passwordMeetsRules, lengthError } = usePasswordRules(password);

const next = computed(() => afterSignInPath(route.query.next));
const asked = computed(() => (typeof route.query.next === "string" && route.query.next ? destinationLabel(route.query.next) : null));

const emailErr = computed(() => emailError(email.value));
const passwordErr = computed(() => {
  if (tab.value === "signin") return signInPasswordError(password.value);
  if (password.value.length === 0) return "Choose a password.";
  // The ceiling is not in the rule list, so it has to speak for itself when crossed.
  return lengthError.value ?? (passwordMeetsRules.value ? null : "That password does not meet the rules below yet.");
});
const firstErr = computed(() => (tab.value === "signup" ? nameError(first.value, "first name") : null));
const lastErr = computed(() => (tab.value === "signup" ? nameError(last.value, "last name") : null));

const showEmailErr = computed(() => touched.value.email && emailErr.value);
const showPasswordErr = computed(() => touched.value.password && passwordErr.value);
const showFirstErr = computed(() => touched.value.first && firstErr.value);
const showLastErr = computed(() => touched.value.last && lastErr.value);

const blocked = computed(() => Boolean(emailErr.value || passwordErr.value || firstErr.value || lastErr.value));

const tabs: TabItem[] = [
  { id: "signin", label: "Sign in" },
  { id: "signup", label: "Create account" },
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

function switchTab(value: string) {
  tab.value = value === "signup" ? "signup" : "signin";
  note.value = null;
}

// "Get started" in the top bar is a link to this same route, so the query has to be what
// moves the tab — a click that changes nothing visible reads as a broken control.
watch(() => route.query.mode, (mode) => switchTab(mode === "signup" ? "signup" : "signin"));

async function onSubmit() {
  touched.value = { email: true, password: true, first: tab.value === "signup", last: tab.value === "signup" };
  note.value = null;
  if (blocked.value) return;

  busy.value = true;
  try {
    if (tab.value === "signin") {
      await auth.login(email.value.trim(), password.value);
    } else {
      await auth.signup({
        email: email.value.trim(),
        password: password.value,
        first_name: first.value.trim(),
        last_name: last.value.trim(),
      });
    }
    announce("Signed in.");
    await router.push(next.value);
  } catch (err: unknown) {
    note.value = tab.value === "signin" ? signInMessage(err) : signUpMessage(err);
  } finally {
    busy.value = false;
  }
}

useHead({ title: () => (tab.value === "signin" ? "Sign in" : "Create account") });
</script>

<template>
  <div class="w-full overflow-x-hidden">
    <TopBar :signed-in="false" home-to="/" sign-in-to="/login" get-started-to="/login?mode=signup" />
    <RulerStrip :readout="tab === 'signin' ? 'session · not started' : 'account · new'" />

    <main id="main" class="relative mx-auto w-full max-w-[1200px] px-5 sm:px-8">
      <div class="grid lg:grid-cols-12">
        <!-- editorial column -->
        <div class="relative border-line-subtle py-12 lg:col-span-7 lg:border-l lg:py-20 lg:pl-10 lg:pr-14">
          <RuleTicks />
          <Cross class="absolute -left-[5px] -top-[5px] hidden lg:block" />

          <div class="sec flex items-center gap-3">
            <Eyebrow>{{ tab === "signin" ? "Returning" : "New account" }}</Eyebrow>
            <span class="rule-draw h-px w-8 bg-line" style="animation-delay: 160ms" aria-hidden="true" />
            <span :class="[MONO_LABEL, 'text-ink-faint']">identity.meridian</span>
          </div>

          <h1
            class="sec mt-6 max-w-[16ch] text-[clamp(2rem,4.6vw,3.2rem)] font-semibold leading-[0.98] tracking-[-0.04em]"
            style="animation-delay: 40ms"
          >
            <template v-if="tab === 'signin'">
              One account.<br />
              <span class="text-ink-muted">Pick up where you left off.</span>
            </template>
            <template v-else>
              Create it once.<br />
              <span class="text-ink-muted">Use it everywhere.</span>
            </template>
          </h1>

          <div class="sec mt-8 flex max-w-[48ch] gap-5" style="animation-delay: 80ms">
            <span class="rule-draw mt-1 h-px w-8 shrink-0 bg-line-strong" style="animation-delay: 240ms" aria-hidden="true" />
            <p class="text-[14px] leading-relaxed text-ink-muted">
              Identity is the only service that stores a password. Pulse and Forge never see one — they verify the token it
              hands you against a published public key, and that is the whole trust relationship.
            </p>
          </div>

          <p
            v-if="asked"
            class="sec mono mt-8 inline-flex items-center gap-2 rounded-md bg-info-surface px-3 py-2 text-[12px] text-info"
            style="animation-delay: 120ms"
          >
            <Icon name="shield" class="h-3.5 w-3.5" />
            Sign in required · continuing to {{ asked }}
          </p>

          <ul class="sec mt-10 grid gap-px border-t border-line-subtle sm:grid-cols-2" style="animation-delay: 160ms">
            <li v-for="[n, t] in TRUST" :key="n" class="flex items-baseline gap-2.5 border-b border-line-subtle py-3">
              <span class="mono text-[12px] text-ink-faint">{{ n }}</span>
              <span :class="[MONO_LABEL, 'text-ink-muted']">{{ t }}</span>
            </li>
          </ul>

          <!-- A key id to check against JWKS, not a caption: a value, so ink-muted. -->
          <p v-if="signingKey" :class="[MONO_LABEL, 'mt-6 text-ink-muted']">{{ signingKey }}</p>
        </div>

        <!-- form column -->
        <div class="sec relative border-line-subtle pb-16 lg:col-span-5 lg:border-l lg:py-20 lg:pl-10" style="animation-delay: 120ms">
          <Cross class="absolute -left-[5px] -top-[5px] hidden lg:block" />

          <div class="flex items-center gap-2.5">
            <Mark />
            <div class="leading-none">
              <p class="text-[13px] font-medium tracking-tight">Meridian</p>
              <p :class="[MONO_LABEL, 'mt-1 text-ink-faint']">One login</p>
            </div>
          </div>

          <div class="mt-6">
            <Tabs id="auth" :items="tabs" :model-value="tab" label="Sign in or create an account" has-panel @update:model-value="switchTab" />
          </div>

          <TabPanel id="auth" :tab="tab">
            <form class="mt-6 space-y-4" novalidate @submit.prevent="onSubmit">
              <div v-if="tab === 'signup'" class="grid gap-4 sm:grid-cols-2">
                <div>
                  <label for="auth-first" :class="[MONO_LABEL, 'mb-1.5 block text-ink-faint']">First name</label>
                  <input
                    id="auth-first"
                    v-model="first"
                    name="given-name"
                    type="text"
                    autocomplete="given-name"
                    spellcheck="false"
                    :aria-invalid="showFirstErr ? true : undefined"
                    :aria-describedby="showFirstErr ? 'auth-first-err' : undefined"
                    :class="[FOCUS, 'w-full rounded-md bg-app px-3 py-2.5 text-[13px] text-ink ring-1 ring-inset transition-colors hover:ring-line-strong', showFirstErr ? 'ring-bad' : 'ring-line']"
                    @blur="touched.first = true"
                  />
                  <p v-if="showFirstErr" id="auth-first-err" role="alert" class="mt-1.5 rounded-md bg-bad-surface px-2.5 py-1.5 text-[12.5px] text-bad">
                    {{ firstErr }}
                  </p>
                </div>
                <div>
                  <label for="auth-last" :class="[MONO_LABEL, 'mb-1.5 block text-ink-faint']">Last name</label>
                  <input
                    id="auth-last"
                    v-model="last"
                    name="family-name"
                    type="text"
                    autocomplete="family-name"
                    spellcheck="false"
                    :aria-invalid="showLastErr ? true : undefined"
                    :aria-describedby="showLastErr ? 'auth-last-err' : undefined"
                    :class="[FOCUS, 'w-full rounded-md bg-app px-3 py-2.5 text-[13px] text-ink ring-1 ring-inset transition-colors hover:ring-line-strong', showLastErr ? 'ring-bad' : 'ring-line']"
                    @blur="touched.last = true"
                  />
                  <p v-if="showLastErr" id="auth-last-err" role="alert" class="mt-1.5 rounded-md bg-bad-surface px-2.5 py-1.5 text-[12.5px] text-bad">
                    {{ lastErr }}
                  </p>
                </div>
              </div>

              <div>
                <label for="auth-email" :class="[MONO_LABEL, 'mb-1.5 block text-ink-faint']">Work email</label>
                <input
                  id="auth-email"
                  ref="emailField"
                  v-model="email"
                  name="email"
                  type="email"
                  autocomplete="email"
                  spellcheck="false"
                  placeholder="you@cyphercrescent.com"
                  :aria-invalid="showEmailErr ? true : undefined"
                  :aria-describedby="showEmailErr ? 'auth-email-err' : undefined"
                  :class="['mono', FOCUS, 'w-full rounded-md bg-app px-3 py-2.5 text-[13px] text-ink ring-1 ring-inset transition-colors placeholder:text-ink-faint hover:ring-line-strong', showEmailErr ? 'ring-bad' : 'ring-line']"
                  @blur="touched.email = true"
                />
                <p v-if="showEmailErr" id="auth-email-err" role="alert" class="mt-1.5 rounded-md bg-bad-surface px-2.5 py-1.5 text-[12.5px] text-bad">
                  {{ emailErr }}
                </p>
              </div>

              <div>
                <PasswordField
                  id="auth-pw"
                  v-model="password"
                  name="password"
                  label="Password"
                  tone="faint"
                  :autocomplete="tab === 'signin' ? 'current-password' : 'new-password'"
                  :invalid="Boolean(showPasswordErr)"
                  :describedby="showPasswordErr ? (tab === 'signup' ? 'auth-pw-err auth-pw-rules' : 'auth-pw-err') : tab === 'signup' ? 'auth-pw-rules' : 'auth-pw-hint'"
                  :busy="busy"
                  @blur="touched.password = true"
                >
                  <template #action>
                    <NuxtLink
                      v-if="tab === 'signin'"
                      to="/forgot-password"
                      :class="[FOCUS, 'rounded text-[12px] text-ink-muted transition-colors hover:text-ink']"
                    >
                      Forgot?
                    </NuxtLink>
                  </template>
                </PasswordField>
                <p v-if="showPasswordErr" id="auth-pw-err" role="alert" class="mt-1.5 rounded-md bg-bad-surface px-2.5 py-1.5 text-[12.5px] text-bad">
                  {{ passwordErr }}
                </p>
                <p v-else-if="tab === 'signin'" id="auth-pw-hint" :class="[MONO_LABEL, 'mt-1.5 text-ink-faint']">min 8 characters</p>

                <!-- The full rule list on create-account: the server runs validate_password(),
                     so anything looser here just produces a surprise 400. -->
                <ul v-if="tab === 'signup'" id="auth-pw-rules" class="mt-2.5 grid gap-1.5 sm:grid-cols-2">
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

              <p v-if="note" role="alert" class="rounded-md bg-warn-surface px-3 py-2 text-[12.5px] leading-relaxed text-warn">{{ note }}</p>

              <Btn type="submit" full arrow :busy="busy">
                {{ busy ? "Checking…" : tab === "signin" ? "Sign in" : "Create account" }}
              </Btn>
            </form>
          </TabPanel>

          <p class="mt-6 text-[12px] leading-relaxed text-ink-muted">
            One account works across Pulse and Forge. Accounts are usually created by an invite from your department admin —
            an invitation link signs you in as it is accepted.
          </p>
        </div>
      </div>
    </main>

    <footer class="border-t border-line-subtle">
      <div class="mx-auto flex w-full max-w-[1200px] flex-wrap items-center justify-between gap-4 px-5 py-7 sm:px-8">
        <NuxtLink to="/" :class="[FOCUS, 'group/b inline-flex items-center gap-2 rounded text-[12.5px] text-ink-muted transition-colors hover:text-ink']">
          <Icon name="arrowLeft" class="h-3.5 w-3.5 transition-transform group-hover/b:-translate-x-0.5" />
          Back to Meridian
        </NuxtLink>
        <span :class="[MONO_LABEL, 'text-ink-faint']">access token · 15 min</span>
      </div>
    </footer>
  </div>
</template>
