<script setup lang="ts">
import type { InvitePreview, TokenPair } from "../../types/api";
import { CTA_LINK, CTA_LINK_SECONDARY, FOCUS, MONO_LABEL } from "../../utils/ui";

/* An invited person's first screen, and for most people the only way an account here
   ever gets made. Nothing is typed until the invite has been read back: GET
   /invites/preview turns the token into an email, a department, a role, who sent it and
   when it dies, so the visitor sees what they are joining before committing to it.

   An invitation ends in three different ways and each needs different advice, so the
   400 identity returns is sorted into a kind rather than printed on its own. */

definePageMeta({ layout: false });

const config = useRuntimeConfig();
const route = useRoute();
const router = useRouter();
const auth = useAuth();
const announce = useAnnounce();

// INVITE_EXPIRE_DAYS in services/identity/app/config.py.
const EXPIRE_DAYS = 7;

/* invited_by_name and expires_at were added to InvitePreview in
   services/identity/app/schemas/departments.py after types/api.ts was written. Declared
   here rather than there because this change does not own that file — fold them into
   InvitePreview when someone next touches it. */
type InvitePreviewFull = InvitePreview & {
  invited_by_name?: string | null;
  expires_at?: string;
};

type DeadKind = "invalid" | "expired" | "used";

const DEAD: Record<DeadKind, { eyebrow: string; headline: string; detail: string; advice: string }> = {
  invalid: {
    eyebrow: "Invitation closed",
    headline: "This invitation cannot be read",
    detail: "The token in this link does not match any invitation. Usually the link was cut short by an email client, or part of it was retyped.",
    advice: "Open the link straight from the email rather than copying it. If it still fails, ask the person who invited you to send a new one.",
  },
  expired: {
    eyebrow: "Expired",
    headline: "This invitation has expired",
    detail: `An invitation is good for ${EXPIRE_DAYS} days and this one is older. Nothing was created and no account is waiting.`,
    advice: "Ask your department admin to invite you again. The new link replaces this one entirely.",
  },
  used: {
    eyebrow: "Invitation closed",
    headline: "This invitation has already been used",
    detail: "An invitation works once, and this one was closed the moment it was taken up.",
    advice: "If that was you, sign in. If it was not, tell your department admin now — somebody else may have opened your link.",
  },
};

const token = ref(typeof route.query.token === "string" ? route.query.token : "");
const tokenSeen = ref(token.value);

const preview = ref<InvitePreviewFull | null>(null);
const loading = ref(true);
// Terminal state: invalid, expired, already taken up. Retrying can't fix any of them.
const deadKind = ref<DeadKind | null>(null);
const deadDetail = ref<string | null>(null);

const firstName = ref("");
const lastName = ref("");
const password = ref("");
const touched = ref({ first: false, last: false, password: false });
const { rules, valid, lengthError } = usePasswordRules(password);

const errorMessage = ref<string | null>(null);
const submitting = ref(false);

const firstField = ref<HTMLInputElement | null>(null);

const dead = computed(() => (deadKind.value ? DEAD[deadKind.value] : null));
const detail = computed(() => deadDetail.value ?? dead.value?.detail ?? "");
const fragment = computed(() => (tokenSeen.value ? `${tokenSeen.value.slice(0, 8)}…` : "none"));
const needsAccount = computed(() => preview.value?.needs_account ?? false);

const readout = computed(() => (deadKind.value ? "invite · dead" : loading.value ? "invite · checking" : "invite · not accepted"));

// expires_at is an ISO timestamp; what someone reads off an invitation is how long they
// have left, so it is turned into a distance rather than a date in a foreign timezone.
const expiresLabel = computed(() => {
  const raw = preview.value?.expires_at;
  if (!raw) return null;
  const at = new Date(raw).getTime();
  if (Number.isNaN(at)) return null;
  const minutes = Math.round((at - Date.now()) / 60000);
  if (minutes <= 0) return "any moment now";
  if (minutes < 60) return `in ${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `in ${hours} hours`;
  return `in ${Math.round(hours / 24)} days`;
});

const facts = computed(() => {
  const p = preview.value;
  if (!p) return [] as { label: string; value: string; mono: boolean }[];
  return [
    { label: "Email", value: p.email, mono: true },
    { label: "Department", value: p.dept_name, mono: false },
    { label: "Team", value: p.team_name ?? "No team yet — the admin can place you later", mono: false },
    { label: "Role", value: p.role, mono: false },
    { label: "Invited by", value: p.invited_by_name ?? "Your department admin", mono: false },
    ...(expiresLabel.value ? [{ label: "Link expires", value: expiresLabel.value, mono: true }] : []),
  ];
});

const firstErr = computed(() => (firstName.value.trim() ? null : "Enter your first name."));
const lastErr = computed(() => (lastName.value.trim() ? null : "Enter your last name."));
const passwordErr = computed(() => {
  if (!password.value) return "Choose a password.";
  // The ceiling is not in the rule list, so it has to speak for itself when crossed.
  return lengthError.value ?? (valid.value ? null : "That password does not meet the rules below yet.");
});
const showFirstErr = computed(() => touched.value.first && firstErr.value);
const showLastErr = computed(() => touched.value.last && lastErr.value);
const showPasswordErr = computed(() => touched.value.password && passwordErr.value);

function serverDetail(err: unknown): string | null {
  const d = (err as { data?: { detail?: unknown } })?.data?.detail;
  return typeof d === "string" ? d : null;
}

function statusOf(err: unknown): number | undefined {
  return (err as { statusCode?: number; status?: number })?.statusCode
    ?? (err as { status?: number })?.status;
}

/* identity's own wording, from services/identity/app/services/invites.py:
     "Invalid invite link"
     "This invite has already been used"
     "This invite has expired, so ask for a new one"
   A 409 (already a member) and a 403 (deactivated account) end the same way for the
   person holding the link, so they land on `used` with the server's own sentence. */
function classify(message: string | null): DeadKind {
  if (!message) return "invalid";
  if (/expired/i.test(message)) return "expired";
  if (/already/i.test(message)) return "used";
  return "invalid";
}

function markDead(kind: DeadKind, message: string | null) {
  deadKind.value = kind;
  deadDetail.value = message && kind !== "expired" ? message : null;
  errorMessage.value = null;
  announce("This invitation cannot be used.");
}

onMounted(async () => {
  if (!token.value) {
    deadKind.value = "invalid";
    deadDetail.value = "This link has no token in it at all. Open the link straight from the email rather than retyping the address.";
    loading.value = false;
    announce("This invitation cannot be used.");
    return;
  }
  try {
    preview.value = await $fetch<InvitePreviewFull>(`${config.public.identityUrl}/invites/preview`, {
      query: { token: token.value },
    });
  } catch (err: unknown) {
    if (statusOf(err) === 400) {
      markDead(classify(serverDetail(err)), serverDetail(err));
    } else {
      deadKind.value = "invalid";
      deadDetail.value = "Could not check this invitation. Is the identity service running?";
    }
  } finally {
    loading.value = false;
  }

  if (!preview.value?.needs_account) return;
  const coarse = window.matchMedia?.("(pointer: coarse)").matches ?? false;
  if (coarse || window.innerWidth < 768) return;
  await nextTick();
  firstField.value?.focus();
});

async function onAccept() {
  errorMessage.value = null;
  if (needsAccount.value) {
    touched.value = { first: true, last: true, password: true };
    if (firstErr.value || lastErr.value || passwordErr.value) return;
  }

  submitting.value = true;
  try {
    const pair = await $fetch<TokenPair>(`${config.public.identityUrl}/invites/accept`, {
      method: "POST",
      body: needsAccount.value
        ? {
            token: token.value,
            first_name: firstName.value.trim(),
            last_name: lastName.value.trim(),
            password: password.value,
          }
        : { token: token.value },
    });
    token.value = "";
    password.value = "";
    await auth.adoptSession(pair);
    announce("Invitation accepted. You are signed in.");
    // replace, not push: the entry holding the token leaves the history too.
    await router.replace("/");
  } catch (err: unknown) {
    const status = statusOf(err);
    const message = serverDetail(err);
    if (status === 400 && message && /password/i.test(message)) {
      errorMessage.value = message;
    } else if (status === 400) {
      markDead(classify(message), message);
    } else if (status === 409 || status === 403) {
      markDead("used", message);
    } else if (status === 422) {
      errorMessage.value = "Check the details above and try again.";
    } else if (status === 429) {
      errorMessage.value = "Too many attempts. Wait a minute and try again.";
    } else {
      errorMessage.value = "Could not accept the invitation. Is the identity service running?";
    }
  } finally {
    submitting.value = false;
  }
}

useHead({ title: "Accept your invitation" });
</script>

<template>
  <div class="w-full overflow-x-hidden bg-app font-sans text-ink">
    <TopBar :signed-in="false" home-to="/" sign-in-to="/login" />
    <RulerStrip :readout="readout" />

    <main id="main" class="relative mx-auto w-full max-w-[1200px] px-5 sm:px-8">
      <div class="grid lg:grid-cols-12">
        <!-- editorial column: what the invitation says, before anything is typed -->
        <div class="relative border-line-subtle py-12 lg:col-span-7 lg:border-l lg:py-20 lg:pl-10 lg:pr-14">
          <RuleTicks />
          <Cross class="absolute -left-[5px] -top-[5px] hidden lg:block" />

          <div class="sec flex items-center gap-3">
            <Eyebrow>{{ dead ? dead.eyebrow : "Invitation" }}</Eyebrow>
            <span class="rule-draw h-px w-8 bg-line" style="animation-delay: 160ms" aria-hidden="true" />
            <span :class="[MONO_LABEL, 'text-ink-faint']">identity.meridian</span>
          </div>

          <h1
            class="sec mt-6 max-w-[16ch] text-[clamp(2rem,4.6vw,3.2rem)] font-semibold leading-[0.98] tracking-[-0.04em]"
            style="animation-delay: 40ms"
          >
            <template v-if="dead">
              This invitation<br />
              <span class="text-ink-muted">is finished.</span>
            </template>
            <template v-else>
              You were invited<br />
              <span class="text-ink-muted">by name.</span>
            </template>
          </h1>

          <div class="sec mt-8 flex max-w-[48ch] gap-5" style="animation-delay: 80ms">
            <span class="rule-draw mt-1 h-px w-8 shrink-0 bg-line-strong" style="animation-delay: 240ms" aria-hidden="true" />
            <p class="text-[14px] leading-relaxed text-ink-muted">
              Accounts here are not opened by anybody who finds the address — an admin invites one email into one
              department, and the link that arrives is the only way to take it up. Opening it is how identity knows the
              mailbox is yours, which is why the address comes out verified.
            </p>
          </div>

          <dl v-if="preview" class="sec mt-10 grid gap-px border-t border-line-subtle" style="animation-delay: 160ms" data-testid="invite-facts">
            <div
              v-for="fact in facts"
              :key="fact.label"
              class="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 border-b border-line-subtle py-3"
            >
              <dt :class="[MONO_LABEL, 'text-ink-faint']">{{ fact.label }}</dt>
              <dd :class="[fact.mono ? 'mono text-[12px]' : 'text-[13px]', 'text-ink']">{{ fact.value }}</dd>
            </div>
          </dl>

          <p v-if="preview" class="sec mt-6 max-w-[52ch] text-[12.5px] leading-relaxed text-ink-muted" style="animation-delay: 200ms">
            A role is set by the department, not chosen here, and it can be changed later without touching your account.
          </p>

          <p class="mono mt-6 text-[11px] tracking-[0.08em] text-ink-muted">invite {{ fragment }} · never shown in full</p>
        </div>

        <!-- action column -->
        <div class="sec relative border-line-subtle pb-16 lg:col-span-5 lg:border-l lg:py-20 lg:pl-10" style="animation-delay: 120ms">
          <Cross class="absolute -left-[5px] -top-[5px] hidden lg:block" />

          <div class="flex items-center gap-2.5">
            <Mark />
            <div class="leading-none">
              <p class="text-[13px] font-medium tracking-tight">Meridian</p>
              <p :class="[MONO_LABEL, 'mt-1 text-ink-faint']">One login</p>
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
              <NuxtLink to="/login" :class="[FOCUS, CTA_LINK, 'group/cta']">
                Go to sign in
                <Icon name="arrow" class="h-4 w-4 transition-transform group-hover/cta:translate-x-0.5" />
              </NuxtLink>
              <NuxtLink to="/forgot-password" :class="[FOCUS, CTA_LINK_SECONDARY]">
                I have an account but not the password
              </NuxtLink>
            </div>
          </div>

          <div v-else-if="loading" class="mt-6" data-testid="checking">
            <h2 class="text-[17px] font-semibold tracking-tight">Checking this invitation</h2>
            <p role="status" class="mt-3 text-[13.5px] leading-relaxed text-ink-muted">
              Reading the token back before anything is typed, so you can see what you are joining first.
            </p>
            <div class="mt-5 space-y-2.5" aria-hidden="true">
              <span class="block h-2.5 w-2/3 rounded bg-sunken" />
              <span class="block h-2.5 w-full rounded bg-sunken" />
              <span class="block h-2.5 w-1/2 rounded bg-sunken" />
            </div>
          </div>

          <div v-else-if="preview" data-testid="invite-form">
            <div class="mt-6 flex flex-wrap items-center gap-x-3 gap-y-2">
              <h2 class="text-[17px] font-semibold tracking-tight">
                {{ needsAccount ? "Activate your account" : "Join the department" }}
              </h2>
              <StatusDot tone="info">{{ needsAccount ? "new account" : "existing account" }}</StatusDot>
            </div>
            <p class="mt-2 text-[13.5px] leading-relaxed text-ink-muted">
              <template v-if="needsAccount">
                Joining as <span class="mono text-[12px] text-ink">{{ preview.email }}</span>. The address is fixed by
                the invitation and cannot be swapped here.
              </template>
              <template v-else>
                <span class="mono text-[12px] text-ink">{{ preview.email }}</span> already has an account, so this only
                adds the membership. Your password does not change.
              </template>
            </p>

            <form class="mt-6 space-y-4" novalidate @submit.prevent="onAccept">
              <template v-if="needsAccount">
                <div class="grid gap-4 sm:grid-cols-2">
                  <div>
                    <label for="invite-first" :class="[MONO_LABEL, 'mb-1.5 block text-ink-faint']">First name</label>
                    <input
                      id="invite-first"
                      ref="firstField"
                      v-model="firstName"
                      name="given-name"
                      type="text"
                      autocomplete="given-name"
                      spellcheck="false"
                      :aria-invalid="showFirstErr ? true : undefined"
                      :aria-describedby="showFirstErr ? 'invite-first-err' : undefined"
                      :class="[FOCUS, 'w-full rounded-md bg-app px-3 py-2.5 text-[13px] text-ink ring-1 ring-inset transition-colors hover:ring-line-strong', showFirstErr ? 'ring-bad' : 'ring-line']"
                      @blur="touched.first = true"
                    />
                    <p
                      v-if="showFirstErr"
                      id="invite-first-err"
                      role="alert"
                      class="mt-1.5 rounded-md bg-bad-surface px-2.5 py-1.5 text-[12.5px] text-bad"
                    >
                      {{ firstErr }}
                    </p>
                  </div>
                  <div>
                    <label for="invite-last" :class="[MONO_LABEL, 'mb-1.5 block text-ink-faint']">Last name</label>
                    <input
                      id="invite-last"
                      v-model="lastName"
                      name="family-name"
                      type="text"
                      autocomplete="family-name"
                      spellcheck="false"
                      :aria-invalid="showLastErr ? true : undefined"
                      :aria-describedby="showLastErr ? 'invite-last-err' : undefined"
                      :class="[FOCUS, 'w-full rounded-md bg-app px-3 py-2.5 text-[13px] text-ink ring-1 ring-inset transition-colors hover:ring-line-strong', showLastErr ? 'ring-bad' : 'ring-line']"
                      @blur="touched.last = true"
                    />
                    <p
                      v-if="showLastErr"
                      id="invite-last-err"
                      role="alert"
                      class="mt-1.5 rounded-md bg-bad-surface px-2.5 py-1.5 text-[12.5px] text-bad"
                    >
                      {{ lastErr }}
                    </p>
                  </div>
                </div>

                <div>
                  <PasswordField
                    id="invite-pw"
                    v-model="password"
                    name="new-password"
                    label="Password"
                    tone="faint"
                    autocomplete="new-password"
                    :invalid="Boolean(showPasswordErr)"
                    :describedby="showPasswordErr ? 'invite-pw-err invite-pw-rules' : 'invite-pw-rules'"
                    :busy="submitting"
                    @blur="touched.password = true"
                  />
                  <p
                    v-if="showPasswordErr"
                    id="invite-pw-err"
                    role="alert"
                    class="mt-1.5 rounded-md bg-bad-surface px-2.5 py-1.5 text-[12.5px] leading-relaxed text-bad"
                  >
                    {{ passwordErr }}
                  </p>
                  <ul id="invite-pw-rules" class="mt-2.5 space-y-1.5">
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
              </template>

              <p
                v-if="errorMessage"
                role="alert"
                class="rounded-md bg-warn-surface px-3 py-2 text-[12.5px] leading-relaxed text-warn"
              >
                {{ errorMessage }}
              </p>

              <Btn type="submit" full arrow :busy="submitting">
                {{ submitting ? "Joining…" : needsAccount ? "Create account and join" : "Accept invitation" }}
              </Btn>
            </form>

            <div class="mt-5 border-t border-line-subtle pt-4">
              <p class="text-[12.5px] leading-relaxed text-ink-muted">
                Accepting places you in {{ preview.dept_name }} as {{ preview.role }} and marks
                <span class="mono text-[12px] text-ink-muted">{{ preview.email }}</span> verified, because opening this
                link proved you can read that mailbox.
              </p>
            </div>

            <p class="mt-6 text-[11px] leading-relaxed text-ink-muted">
              Not expecting this? Close the page and tell the sender. Nothing is created until the button above is
              pressed.
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
          I already have an account
        </NuxtLink>
        <span :class="[MONO_LABEL, 'text-ink-faint']">invite · {{ EXPIRE_DAYS }} days · one use</span>
      </div>
    </footer>
  </div>
</template>
