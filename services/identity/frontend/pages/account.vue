<script lang="ts">
import { EMAIL_RE } from "~/utils/auth-form";
import { apiMessage, httpStatus } from "~/utils/format";

/* What the screen says once identity has taken the request. Held as segments rather than
   as one sentence because the address and the expiry are set in mono, and split here
   rather than in the template so `sentMessage()` — what the test reads and what the
   screen reader is told — is assembled from the very strings that are rendered.

   Every clause is conditional on purpose. A 204 means the request was accepted, not that
   an email went out: an address that already belongs to an account answers identically
   and sends nothing, so anything firmer would be a lie about a taken address. */
export const SENT = {
  lead: "Check your new inbox.",
  // The leading space belongs to the segment, not to the template: the two are rendered
  // as adjacent spans and any whitespace between the tags is collapsed away.
  beforeAddress: " If ",
  beforeExpiry: " isn't already tied to another account, a confirmation link is on its way to it. The link expires in ",
  expiry: "30 minutes",
  afterExpiry: ". Nothing changes until you open it, and we've emailed your current address to let you know.",
} as const;

export function sentMessage(email: string): string {
  return `${SENT.lead}${SENT.beforeAddress}${email}${SENT.beforeExpiry}${SENT.expiry}${SENT.afterExpiry}`;
}

/** Which field an email-change refusal belongs under. `null` is the whole form. */
export interface EmailChangeProblem {
  field: "password" | null;
  message: string;
}

export function newEmailError(value: string): string | null {
  const trimmed = value.trim();
  if (trimmed.length === 0) return "Enter the new email address.";
  return EMAIL_RE.test(trimmed) ? null : "Enter a valid email address.";
}

/* POST /auth/change-email answers 401 twice over: once for a session that has gone and
   once for a password that does not match. Only the second belongs under the password
   field, so they are told apart by the sentence identity sends.

   The 429 body puts its sentence under `error` rather than `detail`, so nothing here
   reads it — the wording is ours either way. */
export function changeEmailMessage(err: unknown): EmailChangeProblem {
  const status = httpStatus(err);
  if (status === 401) {
    if (/authenticat/i.test(apiMessage(err, ""))) {
      return { field: null, message: "Your session has expired. Sign in again, then retry the change." };
    }
    return { field: "password", message: "That password doesn't match. Try again." };
  }
  if (status === 400) return { field: null, message: "That's already the email on this account." };
  if (status === 422) return { field: null, message: "Enter a valid email address." };
  if (status === 429) return { field: null, message: "Too many attempts. Wait a minute and try again." };
  if (status === 503) return { field: null, message: "Email isn't set up on the server, so we can't send the confirmation. Contact an admin." };
  return { field: null, message: "Could not request the change. Nothing has been sent." };
}
</script>

<script setup lang="ts">
import { useMutation, useQuery } from "@tanstack/vue-query";
import { FOCUS, MONO_LABEL } from "@crescent/ui/utils/ui";
import type { Tone } from "@crescent/ui/types/ui";
import type { TokenPair, UserMeResponse } from "~/types/api";

/* Your own account, which is not a product — so no ProductShell and no console sub-nav.

   The split down this screen is deliberate: the things you administer yourself (name,
   password, sessions) are forms; the things a department admin administers are facts.
   Rendering the second group as disabled inputs would suggest they might be typed into
   one day, which is not how identity works. */

definePageMeta({ layout: false, middleware: "require-auth" });

// One row per refresh-token family. session_id is a digest of the family id, so it names
// the row without handing back a value the database stores.
interface SessionRow {
  session_id: string;
  started_at: string;
  last_used_at: string;
  rotations: number;
  expires_at: string;
  is_revoked: boolean;
  is_current: boolean;
}

const api = useApi();
const auth = useAuth();
const signOut = useSignOut();
const announce = useAnnounce();
const { toast, show, clear } = useToast();
const { label: signingKey } = useSigningKey();

const me = computed(() => auth.user.value as UserMeResponse | null);
const displayName = computed(() => (me.value ? fullName(me.value.first_name, me.value.last_name, me.value.email) : ""));
const membership = computed(() => me.value?.memberships?.[0] ?? null);

/* ── profile ── */
const first = ref("");
const last = ref("");
const nameTouched = ref({ first: false, last: false });
const savedName = ref("");
const profileNote = ref<string | null>(null);

watch(
  me,
  (user) => {
    if (!user) return;
    first.value = user.first_name ?? "";
    last.value = user.last_name ?? "";
    savedName.value = `${(user.first_name ?? "").trim()} ${(user.last_name ?? "").trim()}`.trim();
  },
  { immediate: true },
);

const firstErr = computed(() => nameError(first.value, "first name"));
const lastErr = computed(() => nameError(last.value, "last name"));
const showFirstErr = computed(() => nameTouched.value.first && firstErr.value);
const showLastErr = computed(() => nameTouched.value.last && lastErr.value);
const nameDirty = computed(() => `${first.value.trim()} ${last.value.trim()}`.trim() !== savedName.value);

const saveProfile = useMutation({
  mutationFn: () =>
    api.request<UserMeResponse>("/me", {
      method: "PATCH",
      body: { first_name: first.value.trim(), last_name: last.value.trim() },
    }),
  onSuccess: (updated) => {
    // Keep the chrome's name in step without a second round trip.
    auth.user.value = updated;
    savedName.value = `${updated.first_name} ${updated.last_name}`.trim();
    profileNote.value = null;
    show("Name updated. Every product reads it by user_id, so it changes everywhere at once.", "ok");
    announce("Name updated.");
  },
  onError: (err) => {
    profileNote.value = profileMessage(err);
  },
});

function submitProfile() {
  nameTouched.value = { first: true, last: true };
  profileNote.value = null;
  if (firstErr.value || lastErr.value) return;
  saveProfile.mutate();
}

/* ── email ── */
/* The address is the one field on this screen the server will not take on trust: it is
   the sign-in handle, so it moves only after the new inbox has been opened. A 204 means
   the request was accepted, not that anything was sent — an address that already belongs
   to an account answers exactly the same way and sends nothing — so the copy after a
   success promises a link only conditionally. That is also why there is no resend. */
type EmailStage = "idle" | "form" | "sent";

const emailStage = ref<EmailStage>("idle");
const newEmail = ref("");
const emailPassword = ref("");
const emailTouched = ref({ email: false, password: false });
const emailNote = ref<string | null>(null);
const emailPasswordNote = ref<string | null>(null);
// Held apart from `newEmail`, which is emptied the moment the request is accepted.
const requestedEmail = ref("");
const emailField = ref<HTMLInputElement | null>(null);
const emailPasswordField = ref<{ focus: () => void } | null>(null);
const sentNote = ref<HTMLElement | null>(null);

const newEmailErr = computed(() => newEmailError(newEmail.value));
const emailPasswordErr = computed(() => currentPasswordError(emailPassword.value));
const emailProblem = computed(() => (emailTouched.value.email ? newEmailErr.value : null));
// The server's sentence outranks the typed-in one: it is the newer fact about the field.
const passwordProblem = computed(() => emailPasswordNote.value ?? (emailTouched.value.password ? emailPasswordErr.value : null));

const changeEmail = useMutation({
  mutationFn: () =>
    api.request<void>("/auth/change-email", {
      method: "POST",
      body: { new_email: newEmail.value.trim(), current_password: emailPassword.value },
    }),
  onSuccess: async () => {
    requestedEmail.value = newEmail.value.trim();
    emailStage.value = "sent";
    newEmail.value = "";
    emailPassword.value = "";
    emailTouched.value = { email: false, password: false };
    emailNote.value = null;
    emailPasswordNote.value = null;
    announce(sentMessage(requestedEmail.value));
    await nextTick();
    sentNote.value?.focus();
  },
  onError: async (err) => {
    const problem = changeEmailMessage(err);
    if (problem.field === "password") {
      // Keep the address they typed and empty only the password, which is the part that
      // has to be retyped anyway.
      emailPasswordNote.value = problem.message;
      emailNote.value = null;
      emailPassword.value = "";
      await nextTick();
      emailPasswordField.value?.focus();
      return;
    }
    emailNote.value = problem.message;
    emailPasswordNote.value = null;
  },
});

// The server's refusal belongs to the password that earned it, so typing clears it.
function onEmailPasswordInput(value: string) {
  emailPassword.value = value;
  emailPasswordNote.value = null;
}

async function openEmailForm() {
  emailStage.value = "form";
  emailTouched.value = { email: false, password: false };
  emailNote.value = null;
  emailPasswordNote.value = null;
  emailPassword.value = "";
  await nextTick();
  emailField.value?.focus();
}

function closeEmailForm() {
  emailStage.value = "idle";
  newEmail.value = "";
  emailPassword.value = "";
  emailTouched.value = { email: false, password: false };
  emailNote.value = null;
  emailPasswordNote.value = null;
}

function submitEmail() {
  emailTouched.value = { email: true, password: true };
  emailNote.value = null;
  emailPasswordNote.value = null;
  if (newEmailErr.value || emailPasswordErr.value) return;
  changeEmail.mutate();
}

/* ── password ── */
const current = ref("");
const next = ref("");
const confirm = ref("");
const pwTouched = ref({ current: false, next: false, confirm: false });
const passwordNote = ref<string | null>(null);
const { rules, valid: meetsRules } = usePasswordRules(next);

const currentErr = computed(() => currentPasswordError(current.value));
const nextErr = computed(() => newPasswordError(next.value, current.value, meetsRules.value));
const confirmErr = computed(() => confirmPasswordError(confirm.value, next.value));
const showCurrentErr = computed(() => pwTouched.value.current && currentErr.value);
const showNextErr = computed(() => pwTouched.value.next && nextErr.value);
const showConfirmErr = computed(() => pwTouched.value.confirm && confirmErr.value);

const changePassword = useMutation({
  mutationFn: () =>
    api.request<TokenPair>("/auth/change-password", {
      method: "POST",
      body: { current_password: current.value, new_password: next.value },
    }),
  onSuccess: async (pair) => {
    // Changing the password revokes every refresh family and bumps token_version, then
    // re-issues this device. Adopting the returned pair is what stops the next request
    // 401ing in the tab you just used.
    await auth.adoptSession(pair);
    current.value = "";
    next.value = "";
    confirm.value = "";
    pwTouched.value = { current: false, next: false, confirm: false };
    passwordNote.value = null;
    show("Password changed. Every other device was signed out; this one was re-issued a token.", "ok");
    announce("Password changed. Every other device was signed out.");
    await sessions.refetch();
  },
  onError: (err) => {
    passwordNote.value = changePasswordMessage(err);
  },
});

function submitPassword() {
  pwTouched.value = { current: true, next: true, confirm: true };
  passwordNote.value = null;
  if (currentErr.value || nextErr.value || confirmErr.value) return;
  changePassword.mutate();
}

/* ── sessions ── */
const sessions = useQuery({
  queryKey: ["me", "sessions"],
  queryFn: () => api.request<SessionRow[]>("/me/sessions"),
  retry: false,
});

const rows = computed(() => sessions.data.value ?? []);
const live = computed(() => rows.value.filter((row) => sessionState(row) === "refreshing" || sessionState(row) === "idle"));

const STATE_TONE: Record<string, Tone> = { revoked: "muted", expired: "bad", idle: "warn", refreshing: "ok" };

const confirmAll = ref(false);

async function signOutEverywhere() {
  confirmAll.value = false;
  try {
    await api.request<void>("/auth/logout-all", { method: "POST" });
  } catch {
    // The local session goes either way: leaving someone signed in here after they asked
    // to be signed out everywhere is the worse failure.
  }
  announce("Every session revoked. Signing out.");
  await signOut();
}

function expiryLabel(row: SessionRow): string {
  const ms = new Date(row.expires_at).getTime() - Date.now();
  if (row.is_revoked) return "revoked";
  if (ms <= 0) return `expired ${Math.abs(Math.round(ms / 86_400_000))}d ago`;
  const days = Math.floor(ms / 86_400_000);
  return days >= 1 ? `in ${days}d` : "under a day";
}

const readout = computed(() => (me.value ? `user_id ${me.value.id} · ${live.value.length} live` : undefined));

useHead({ title: "Account" });
</script>

<template>
  <div class="w-full overflow-x-hidden">
    <TopBar
      signed-in
      show-sign-out
      breadcrumb="Account"
      home-to="/products"
      all-products-to="/products"
      :user-name="displayName"
      @sign-out="signOut"
    />
    <RulerStrip v-bind="readout ? { readout } : {}" />

    <main id="main" class="relative mx-auto w-full max-w-[1200px] px-5 sm:px-8">
      <!-- header -->
      <div class="relative border-line-subtle py-12 lg:pr-14">
        <Cross class="absolute -left-[5px] -top-[5px] hidden lg:block" />
        <div class="sec flex flex-wrap items-center gap-3">
          <Eyebrow>Account</Eyebrow>
          <span class="rule-draw h-px w-8 bg-line" style="animation-delay: 160ms" aria-hidden="true" />
          <StatusDot tone="ok">Session active</StatusDot>
        </div>

        <h1
          class="sec mt-6 max-w-[18ch] text-[clamp(2rem,4.6vw,3.2rem)] font-semibold leading-[0.98] tracking-[-0.04em]"
          style="animation-delay: 40ms"
        >
          One record of you,<br />
          <span class="text-ink-muted">read by everything.</span>
        </h1>

        <div v-if="me" class="sec mt-7 flex flex-wrap items-baseline gap-x-3 gap-y-1.5" style="animation-delay: 80ms">
          <span class="mono text-[12px] text-ink-muted">{{ me.email }}</span>
          <span class="text-ink-faint" aria-hidden="true">·</span>
          <span class="mono text-[12px] text-ink-muted">user_id {{ me.id }}</span>
          <span class="text-ink-faint" aria-hidden="true">·</span>
          <span class="mono text-[12px] text-ink-muted">{{ membership?.dept_name ?? "Unplaced" }}</span>
        </div>

        <p class="sec mt-5 max-w-[52ch] text-[13.5px] leading-relaxed text-ink-muted" style="animation-delay: 100ms">
          Pulse and Forge keep no copy of you. They store your id and ask identity for the rest, so a change made here is a
          change everywhere — and revoking a session here stops both of them just as quickly.
        </p>
      </div>

      <!-- ── profile ── -->
      <section aria-labelledby="acct-profile" class="sec grid border-t border-line-subtle py-10 lg:grid-cols-12 lg:gap-10">
        <div class="lg:col-span-4">
          <h2 id="acct-profile" class="text-[17px] font-semibold tracking-tight">Profile</h2>
          <p class="mt-2 max-w-[38ch] text-[13px] leading-relaxed text-ink-muted">
            Your name is the only part of this you set yourself. It is what appears on a report, on an approval and next to a
            commit once the author has been resolved.
          </p>
        </div>

        <form class="mt-6 max-w-[38rem] lg:col-span-8 lg:mt-0" novalidate @submit.prevent="submitProfile">
          <div class="grid gap-4 sm:grid-cols-2">
            <div>
              <label for="acct-first" :class="[MONO_LABEL, 'mb-1.5 block text-ink-faint']">First name</label>
              <input
                id="acct-first"
                v-model="first"
                name="given-name"
                type="text"
                autocomplete="given-name"
                spellcheck="false"
                :aria-invalid="showFirstErr ? true : undefined"
                :aria-describedby="showFirstErr ? 'acct-first-err' : undefined"
                :class="[FOCUS, 'w-full rounded-md bg-app px-3 py-2.5 text-[13px] text-ink ring-1 ring-inset transition-colors hover:ring-line-strong', showFirstErr ? 'ring-bad' : 'ring-line']"
                @blur="nameTouched.first = true"
              />
              <p v-if="showFirstErr" id="acct-first-err" role="alert" class="mt-1.5 rounded-md bg-bad-surface px-2.5 py-1.5 text-[12.5px] text-bad">
                {{ firstErr }}
              </p>
            </div>
            <div>
              <label for="acct-last" :class="[MONO_LABEL, 'mb-1.5 block text-ink-faint']">Last name</label>
              <input
                id="acct-last"
                v-model="last"
                name="family-name"
                type="text"
                autocomplete="family-name"
                spellcheck="false"
                :aria-invalid="showLastErr ? true : undefined"
                :aria-describedby="showLastErr ? 'acct-last-err' : undefined"
                :class="[FOCUS, 'w-full rounded-md bg-app px-3 py-2.5 text-[13px] text-ink ring-1 ring-inset transition-colors hover:ring-line-strong', showLastErr ? 'ring-bad' : 'ring-line']"
                @blur="nameTouched.last = true"
              />
              <p v-if="showLastErr" id="acct-last-err" role="alert" class="mt-1.5 rounded-md bg-bad-surface px-2.5 py-1.5 text-[12.5px] text-bad">
                {{ lastErr }}
              </p>
            </div>
          </div>

          <!-- The address is not a field in this form: PATCH /me takes first_name,
               last_name and avatar_url and ignores an email, so an input here could never
               save. It has its own section below, with its own re-authentication. -->

          <p v-if="profileNote" role="alert" class="mt-4 rounded-md bg-bad-surface px-3 py-2 text-[12.5px] text-bad">{{ profileNote }}</p>

          <div class="mt-5 flex flex-wrap items-center gap-3">
            <Btn type="submit" :busy="saveProfile.isPending.value" :disabled="!nameDirty">
              {{ saveProfile.isPending.value ? "Saving…" : "Save profile" }}
            </Btn>
            <span v-if="nameDirty && !saveProfile.isPending.value" :class="[MONO_LABEL, 'text-ink-faint']">unsaved</span>
          </div>
        </form>
      </section>

      <!-- ── email ── -->
      <section aria-labelledby="acct-email" class="sec grid border-t border-line-subtle py-10 lg:grid-cols-12 lg:gap-10">
        <div class="lg:col-span-4">
          <h2 id="acct-email" class="text-[17px] font-semibold tracking-tight">Email address</h2>
          <p class="mt-2 max-w-[38ch] text-[13px] leading-relaxed text-ink-muted">
            The address is the account. It is how you sign in and where a reset link goes, so changing it means proving the
            new one is yours before it takes over.
          </p>
          <p class="mt-3 max-w-[38ch] text-[12.5px] leading-relaxed text-ink-muted">
            Your password is asked for again here. Anyone who walks up to an unlocked screen could otherwise move the
            account to an address of their own.
          </p>
        </div>

        <div v-if="me" class="mt-6 max-w-[38rem] lg:col-span-8 lg:mt-0">
          <div class="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 border-y border-line-subtle py-3">
            <span :class="[MONO_LABEL, 'text-ink-faint']">Signing in as</span>
            <span class="mono text-[12.5px] text-ink">{{ me.email }}</span>
          </div>

          <div v-if="emailStage === 'idle'" class="mt-5">
            <Btn variant="secondary" @click="openEmailForm">Change email</Btn>
          </div>

          <form v-else-if="emailStage === 'form'" class="mt-5" novalidate @submit.prevent="submitEmail">
            <div>
              <label for="acct-new-email" :class="[MONO_LABEL, 'mb-1.5 block text-ink-faint']">New email address</label>
              <input
                id="acct-new-email"
                ref="emailField"
                v-model="newEmail"
                name="email"
                type="email"
                autocomplete="email"
                spellcheck="false"
                :aria-invalid="emailProblem ? true : undefined"
                :aria-describedby="emailProblem ? 'acct-new-email-err acct-email-help' : 'acct-email-help'"
                :class="['mono', FOCUS, 'w-full rounded-md bg-app px-3 py-2.5 text-[13px] text-ink ring-1 ring-inset transition-colors hover:ring-line-strong', emailProblem ? 'ring-bad' : 'ring-line']"
                @blur="emailTouched.email = true"
              />
              <p v-if="emailProblem" id="acct-new-email-err" role="alert" class="mt-1.5 rounded-md bg-bad-surface px-2.5 py-1.5 text-[12.5px] text-bad">
                {{ emailProblem }}
              </p>
            </div>

            <div class="mt-4">
              <PasswordField
                id="acct-email-pw"
                ref="emailPasswordField"
                :model-value="emailPassword"
                name="current-password"
                label="Current password"
                tone="faint"
                autocomplete="current-password"
                :invalid="Boolean(passwordProblem)"
                :describedby="passwordProblem ? 'acct-email-pw-err' : undefined"
                @update:model-value="onEmailPasswordInput"
                @blur="emailTouched.password = true"
              />
              <p v-if="passwordProblem" id="acct-email-pw-err" role="alert" class="mt-1.5 rounded-md bg-bad-surface px-2.5 py-1.5 text-[12.5px] text-bad">
                {{ passwordProblem }}
              </p>
            </div>

            <p id="acct-email-help" class="mt-3 text-[12.5px] leading-relaxed text-ink-muted">
              You'll need to confirm the new address before it takes effect. Your current address keeps working until then.
            </p>

            <p v-if="emailNote" role="alert" class="mt-4 rounded-md bg-bad-surface px-3 py-2 text-[12.5px] leading-relaxed text-bad">
              {{ emailNote }}
            </p>

            <div class="mt-5 flex flex-wrap items-center gap-3">
              <Btn type="submit" :busy="changeEmail.isPending.value">
                {{ changeEmail.isPending.value ? "Requesting…" : "Request email change" }}
              </Btn>
              <Btn variant="ghost" :disabled="changeEmail.isPending.value" @click="closeEmailForm">Cancel</Btn>
            </div>
          </form>

          <!-- Deliberately not a success banner. 204 says the request was accepted; an
               address that already belongs to someone answers the same way and sends
               nothing, so the sentence stays conditional and there is no resend. -->
          <div v-else class="mt-5">
            <div class="flex items-start gap-2.5 rounded-md bg-info-surface px-3.5 py-3">
              <span class="mt-0.5 shrink-0 text-info"><Icon name="clock" class="h-3.5 w-3.5" /></span>
              <p ref="sentNote" tabindex="-1" :class="[FOCUS, 'rounded text-[13px] leading-relaxed text-ink']">
                <span class="font-medium">{{ SENT.lead }}</span>
                <span class="text-ink-muted"
                  >{{ SENT.beforeAddress }}<span class="mono text-[12px] text-ink">{{ requestedEmail }}</span
                  >{{ SENT.beforeExpiry }}<span class="mono text-[12px] text-ink">{{ SENT.expiry }}</span
                  >{{ SENT.afterExpiry }}</span
                >
              </p>
            </div>

            <div class="mt-4">
              <Btn variant="ghost" size="sm" @click="openEmailForm">Request a different address</Btn>
            </div>
          </div>
        </div>
      </section>

      <!-- ── administered elsewhere ── -->
      <section aria-labelledby="acct-org" class="sec grid border-t border-line-subtle py-10 lg:grid-cols-12 lg:gap-10">
        <div class="lg:col-span-4">
          <h2 id="acct-org" class="text-[17px] font-semibold tracking-tight">Where you sit</h2>
          <p class="mt-2 max-w-[38ch] text-[13px] leading-relaxed text-ink-muted">
            Read-only on purpose. A department admin places people and sets roles; if these are wrong, the fix is a
            conversation, not a form.
          </p>
        </div>

        <div v-if="me" class="mt-6 lg:col-span-8 lg:mt-0">
          <dl class="grid gap-px border-t border-line-subtle sm:grid-cols-2">
            <div
              v-for="fact in [
                { label: 'Email', value: me.email, mono: true },
                { label: 'Department', value: membership?.dept_name ?? 'Not placed yet', mono: false },
                { label: 'Team', value: membership?.team_name ?? 'None', mono: false },
                { label: 'Role', value: membership?.role ?? 'None yet', mono: false },
                { label: 'Platform admin', value: me.is_platform_admin ? 'Yes' : 'No', mono: false },
                { label: 'Email verified', value: me.email_verified ? 'Yes' : 'Not yet', mono: false },
                { label: 'user_id', value: String(me.id), mono: true },
                { label: 'dept_id', value: membership ? String(membership.dept_id) : 'null', mono: true },
              ]"
              :key="fact.label"
              class="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 border-b border-line-subtle py-3 sm:odd:pr-6 sm:even:border-l sm:even:pl-6"
            >
              <dt :class="[MONO_LABEL, 'text-ink-faint']">{{ fact.label }}</dt>
              <dd :class="[fact.mono ? 'mono text-[12px]' : 'text-[13px]', 'text-ink']">{{ fact.value }}</dd>
            </div>
          </dl>

          <p v-if="membership" class="mt-4 max-w-[52ch] text-[12.5px] leading-relaxed text-ink-muted">
            {{ roleBlurb(membership.role) }}
            <template v-if="me.is_platform_admin">
              Platform admin sits above the departments: it opens the identity console itself, which is a different thing
              from your role inside a department.
            </template>
          </p>
          <p :class="[MONO_LABEL, 'mt-3 text-ink-faint']">ids are what products store · names are looked up</p>
        </div>
      </section>

      <!-- ── password ── -->
      <section aria-labelledby="acct-password" class="sec grid border-t border-line-subtle py-10 lg:grid-cols-12 lg:gap-10">
        <div class="lg:col-span-4">
          <h2 id="acct-password" class="text-[17px] font-semibold tracking-tight">Password</h2>
          <p class="mt-2 max-w-[38ch] text-[13px] leading-relaxed text-ink-muted">
            Changing it signs out every other device and leaves this one signed in. Stored as a bcrypt hash, so nobody here
            can read the one you have now — which is why the current one is asked for rather than looked up.
          </p>
        </div>

        <form class="mt-6 max-w-[38rem] lg:col-span-8 lg:mt-0" novalidate @submit.prevent="submitPassword">
          <div>
            <PasswordField
              id="acct-current"
              v-model="current"
              name="current-password"
              label="Current password"
              tone="faint"
              autocomplete="current-password"
              :invalid="Boolean(showCurrentErr)"
              :describedby="showCurrentErr ? 'acct-current-err' : undefined"
              @blur="pwTouched.current = true"
            />
            <p v-if="showCurrentErr" id="acct-current-err" role="alert" class="mt-1.5 rounded-md bg-bad-surface px-2.5 py-1.5 text-[12.5px] text-bad">
              {{ currentErr }}
            </p>
          </div>

          <div class="mt-4">
            <PasswordField
              id="acct-new"
              v-model="next"
              name="new-password"
              label="New password"
              tone="faint"
              autocomplete="new-password"
              :invalid="Boolean(showNextErr)"
              :describedby="showNextErr ? 'acct-new-err acct-new-rules' : 'acct-new-rules'"
              @blur="pwTouched.next = true"
            />
            <p v-if="showNextErr" id="acct-new-err" role="alert" class="mt-1.5 rounded-md bg-bad-surface px-2.5 py-1.5 text-[12.5px] leading-relaxed text-bad">
              {{ nextErr }}
            </p>
            <ul id="acct-new-rules" class="mt-2.5 grid gap-1.5 sm:grid-cols-2">
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

          <div class="mt-4">
            <PasswordField
              id="acct-confirm"
              v-model="confirm"
              name="confirm-password"
              label="Confirm new password"
              tone="faint"
              autocomplete="new-password"
              :invalid="Boolean(showConfirmErr)"
              :describedby="showConfirmErr ? 'acct-confirm-err' : undefined"
              @blur="pwTouched.confirm = true"
            />
            <p v-if="showConfirmErr" id="acct-confirm-err" role="alert" class="mt-1.5 rounded-md bg-bad-surface px-2.5 py-1.5 text-[12.5px] text-bad">
              {{ confirmErr }}
            </p>
          </div>

          <p v-if="passwordNote" role="alert" class="mt-4 rounded-md bg-bad-surface px-3 py-2 text-[12.5px] text-bad">{{ passwordNote }}</p>

          <div class="mt-5">
            <Btn type="submit" :busy="changePassword.isPending.value">
              {{ changePassword.isPending.value ? "Changing…" : "Change password" }}
            </Btn>
          </div>
        </form>
      </section>

      <!-- ── sessions ── -->
      <section aria-labelledby="acct-sessions" class="sec grid border-t border-line-subtle py-10 lg:grid-cols-12 lg:gap-10">
        <div class="lg:col-span-4">
          <h2 id="acct-sessions" class="text-[17px] font-semibold tracking-tight">Sessions</h2>
          <p class="mt-2 max-w-[38ch] text-[13px] leading-relaxed text-ink-muted">
            One row per refresh-token family. The refresh token rotates on every use and the old one is blacklisted, so a
            family is a chain of tokens under a single id — ending the id is what signs a device out.
          </p>
          <p class="mt-3 max-w-[38ch] text-[12.5px] leading-relaxed text-ink-muted">
            There is no device or location column. Neither is recorded, so anything written here would be a guess. What is
            real is the family id and how often it has rotated.
          </p>
        </div>

        <div class="mt-6 lg:col-span-8 lg:mt-0">
          <p v-if="sessions.isPending.value" role="status" class="border-t border-line-subtle py-3.5 text-[13px] text-ink-muted">
            Reading your sessions…
          </p>
          <p v-else-if="sessions.isError.value" role="alert" class="rounded-md bg-bad-surface px-3 py-2 text-[12.5px] text-bad">
            Could not read your sessions. Nothing has changed; try again in a moment.
          </p>
          <ul v-else class="border-t border-line-subtle">
            <li
              v-for="row in rows"
              :key="row.session_id"
              class="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2 border-b border-line-subtle py-3.5"
            >
              <!-- Same rule as the Sessions table: a revoked family dims its type, never
                   the whole row, so the rule between rows keeps its full weight. -->
              <div class="min-w-0">
                <p class="flex flex-wrap items-center gap-2">
                  <span :class="['mono text-[12.5px]', row.is_revoked ? 'text-ink-disabled' : 'text-ink']">{{ row.session_id }}</span>
                  <span v-if="row.is_current" :class="[MONO_LABEL, 'rounded bg-sunken px-1.5 py-px text-ink-muted']">this device</span>
                </p>
                <p :class="['mono mt-1 text-[12px]', row.is_revoked ? 'text-ink-disabled' : 'text-ink-muted']">
                  started {{ formatDateTime(row.started_at) }} · {{ row.rotations }} rotations · expires {{ expiryLabel(row) }}
                </p>
              </div>
              <div class="text-right">
                <span :class="['mono block text-[12.5px]', row.is_revoked ? 'text-ink-disabled' : 'text-ink']">{{ formatDateTime(row.last_used_at) }}</span>
                <StatusDot :tone="STATE_TONE[sessionState(row)] ?? 'muted'" quiet>{{ sessionState(row) }}</StatusDot>
              </div>
            </li>
          </ul>

          <p class="mt-4 max-w-[52ch] text-[12.5px] leading-relaxed text-ink-muted">
            Access tokens are not listed. They live about fifteen minutes, are never stored, and so cannot be revoked —
            cutting the family is what stops the next one being issued.
          </p>

          <div class="mt-5 flex flex-wrap items-center gap-3">
            <Btn variant="destructive" @click="confirmAll = true">Sign out everywhere</Btn>
            <!-- /sessions is everyone's own screen, but the product picker only offers the
                 identity console to admins, so without this link the only way to it was to
                 type the address. -->
            <NuxtLink
              to="/sessions"
              :class="[FOCUS, 'group/s inline-flex items-center gap-1.5 rounded text-[13px] font-medium text-ink transition-colors hover:text-ink-muted']"
            >
              End one session
              <Icon name="arrow" class="h-3.5 w-3.5 transition-transform group-hover/s:translate-x-0.5" />
            </NuxtLink>
            <span v-if="!sessions.isError.value" :class="[MONO_LABEL, 'text-ink-muted']">{{ live.length }} live · {{ rows.length }} total</span>
          </div>
        </div>
      </section>

      <div class="flex flex-wrap items-center justify-between gap-4 border-t border-line-subtle py-7">
        <!-- The key id is there to be compared against what JWKS publishes, so it reads as a
             value; `access 15 min` is a unit string and stays chrome. -->
        <p v-if="signingKey" :class="[MONO_LABEL, 'text-ink-faint']">
          <span class="text-ink-muted">{{ signingKey }}</span> · access 15 min
        </p>
        <NuxtLink to="/products" :class="[FOCUS, MONO_LABEL, 'rounded text-ink-muted transition-colors hover:text-ink']">
          All products
        </NuxtLink>
      </div>
    </main>

    <!-- No initialFocus: the dialog has no fields, so Modal's own rule puts focus on the
         first control that is not the close button — Cancel, not the destructive one. -->
    <Modal
      :open="confirmAll"
      title="Sign out everywhere?"
      description="Every device you are signed in on, including this one."
      :close-on-backdrop="false"
      @close="confirmAll = false"
    >
      <div class="space-y-3">
        <div class="flex items-start gap-2.5 rounded-md bg-warn-surface px-3 py-2.5">
          <span class="mt-0.5 shrink-0 text-warn"><Icon name="alert" class="h-3.5 w-3.5" /></span>
          <p class="text-[12px] leading-relaxed text-ink">
            <span class="font-medium">You will be signed out here too.</span>
            <span class="text-ink-muted">
              Every refresh-token family on your account is blacklisted and <span class="mono text-[12px]">token_version</span>
              is bumped, so no device can refresh again without signing in.
            </span>
          </p>
        </div>
        <p class="text-[12px] leading-relaxed text-ink-muted">
          An access token already in a browser's memory keeps working until it expires — under a minute at the outside — and
          cannot be recalled, because it was never stored anywhere to recall it from. After that minute, every product
          refuses it.
        </p>
        <p class="text-[12px] leading-relaxed text-ink-muted">
          Nothing is deleted and your password does not change. Worth doing if a laptop went missing or you signed in
          somewhere you should not have.
        </p>
      </div>
      <template #footer>
        <Btn size="sm" variant="secondary" @click="confirmAll = false">Cancel</Btn>
        <Btn size="sm" variant="destructive" @click="signOutEverywhere">
          Sign out {{ rows.length || "all" }} sessions
        </Btn>
      </template>
    </Modal>

    <Toast v-if="toast" :message="toast.message" :tone="toast.tone" @dismiss="clear" />
  </div>
</template>
