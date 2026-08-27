<script lang="ts">
import { safeNextPath } from "@crescent/ui/composables/useSSO";

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

/* Forge's front desk, and deliberately not a password form.

   Identity is the only service that stores a password, so it is the only one that asks
   for one. A second password box on a second origin teaches people to type their Meridian
   password wherever it is asked for, which is the shape of a phishing page, and it splits
   sign-out and token revocation across two doors instead of one.

   So this screen has one job: start the handoff at /auth/callback, which asks identity for
   a fifteen-minute access token and brings the browser back here. When the handoff cannot
   run the answer is "sign in at identity", never "type it here instead". */

definePageMeta({ layout: false });

const auth = useAuth();
const route = useRoute();
const router = useRouter();
const identityWebUrl = useRuntimeConfig().public.identityWebUrl as string;

// Forge's own guard sends people here without a `next`, so this is usually "/" — it is
// read anyway so a link that carries one keeps working through the handoff.
const next = computed(() => safeNextPath(typeof route.query.next === "string" ? route.query.next : "/"));
const handoff = computed(() => handoffPath(next.value));
const asked = computed(() => (next.value === "/" ? null : next.value));

const GUARANTEES: [string, string][] = [
  ["01", "One login, both products"],
  ["02", "Access token · 15 min"],
  ["03", "Password held only by identity"],
  ["04", "Verified against a public key"],
];

const FORGE_STATE: { tone: Tone; label: string }[] = [
  { tone: "ok", label: "Upload, canvas, runs and code export are live" },
  { tone: "muted", label: "Guided learning paths are still written down" },
];

onMounted(() => {
  auth.hydrate();
  if (auth.isAuthenticated.value) router.replace(next.value);
});

useHead({ title: "Sign in · Forge" });
</script>

<template>
  <div class="w-full overflow-x-hidden">
    <TopBar :signed-in="false" breadcrumb="Forge" home-to="/" :get-started-to="`${identityWebUrl}/login?mode=signup`" />
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
              Forge stores datasets and refers to you by an id. It has no accounts of its own and never asks
              for a password: signing in through Meridian hands it one short-lived token, which is the whole
              of what it knows about you until that token expires.
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

        <!-- action column -->
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

          <h2 class="mt-8 text-[15px] font-medium tracking-tight">Continue with your Meridian account</h2>
          <p class="mt-2 max-w-[42ch] text-[13px] leading-relaxed text-ink-muted">
            If you are already signed in on this browser, this takes a second and no password is asked for.
            If you are not, identity asks for one and brings you straight back here.
          </p>

          <!-- A link rather than a <Btn>: it is a navigation, and a navigation wearing a
               button loses middle-click and open-in-new-tab. -->
          <NuxtLink :to="handoff" :class="[CTA_LINK, FOCUS, TAP, 'mt-6']">
            <Icon name="shield" class="h-4 w-4" />
            Continue with Meridian
          </NuxtLink>

          <p class="mt-6 text-[12px] leading-relaxed text-ink-muted">
            Trouble getting in?
            <a
              :href="`${identityWebUrl}/login`"
              :class="[FOCUS, 'rounded font-medium text-ink transition-colors hover:text-ink-muted']"
            >
              Sign in at Meridian
            </a>
            and open Forge from the product picker. No account yet?
            <a
              :href="`${identityWebUrl}/login?mode=signup`"
              :class="[FOCUS, 'rounded font-medium text-ink transition-colors hover:text-ink-muted']"
            >
              Create one at Meridian</a>, or accept the invitation your department admin sent you. Accounts are
            made where they live; Forge never takes a password.
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
