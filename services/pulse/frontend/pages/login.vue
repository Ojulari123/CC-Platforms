<script setup lang="ts">
import { FOCUS, MONO_LABEL } from "@crescent/ui/utils/ui";

/* Pulse's front desk — and deliberately not a password form.

   Identity is the only service that stores a password, and it is now the only one that
   asks for one: a second password box on a second origin trains people to type their
   Meridian password wherever it is asked for, which is the whole shape of a phishing
   page. So this screen has one job — start the handoff at /auth/callback, which asks
   identity for a fifteen-minute access token and brings the browser back here.

   The fallback is a link to identity's own sign-in, not a form. If the handoff cannot
   run, the answer is "sign in at identity", never "type it here instead". */

definePageMeta({ layout: false });

const auth = useAuth();
const sso = useSSO();
const route = useRoute();
const router = useRouter();
const identityWebUrl = useRuntimeConfig().public.identityWebUrl as string;

const busy = ref(false);
const note = ref<string | null>(null);

// Where the guard was headed when it bounced someone here. Sanitised: this value ends up
// in a redirect, so anything but an in-app path is dropped.
const next = computed(() => safeNextPath(typeof route.query.next === "string" ? route.query.next : "/"));
const asked = computed(() => (next.value === "/" ? null : next.value));

const TRUST: [string, string][] = [
  ["01", "Password stays at identity"],
  ["02", "Access token · 15 min"],
  ["03", "Refresh token never leaves identity"],
  ["04", "Signature checked against a public key"],
];

onMounted(() => {
  auth.hydrate();
  if (auth.isAuthenticated.value) router.replace(next.value);
});

function onContinue() {
  if (!sso.configured.value) {
    note.value = "Cross-product sign-in is not configured for this deployment. Open Meridian and sign in there.";
    return;
  }
  busy.value = true;
  note.value = null;
  // The outbound leg starts at the callback route, not here: useSSO binds the handoff to
  // the address it will be returned to, and /auth/callback is the only one on the list.
  navigateTo({ path: "/auth/callback", query: { start: "1", next: next.value } });
}

useHead({ title: "Sign in" });
</script>

<template>
  <div class="min-h-screen w-full overflow-x-hidden bg-app font-sans text-ink">
    <TopBar :signed-in="false" breadcrumb="Pulse" :home-to="identityWebUrl" />
    <RulerStrip readout="session · not started" />

    <main id="main" class="relative mx-auto w-full max-w-[1200px] px-5 sm:px-8">
      <div class="grid lg:grid-cols-12">
        <!-- editorial column -->
        <div class="relative border-line-subtle py-12 lg:col-span-7 lg:border-l lg:py-20 lg:pl-10 lg:pr-14">
          <RuleTicks />
          <Cross class="absolute -left-[5px] -top-[5px] hidden lg:block" />

          <div class="sec flex items-center gap-3">
            <Eyebrow>Sign in required</Eyebrow>
            <span class="rule-draw h-px w-8 bg-line" style="animation-delay: 160ms" aria-hidden="true" />
            <span :class="[MONO_LABEL, 'text-ink-faint']">pulse.meridian</span>
          </div>

          <h1
            class="sec mt-6 max-w-[16ch] text-[clamp(2rem,4.6vw,3.2rem)] font-semibold leading-[0.98] tracking-[-0.04em]"
            style="animation-delay: 40ms"
          >
            One account.<br />
            <span class="text-ink-muted">Pulse is behind it.</span>
          </h1>

          <div class="sec mt-8 flex max-w-[48ch] gap-5" style="animation-delay: 80ms">
            <span class="rule-draw mt-1 h-px w-8 shrink-0 bg-line-strong" style="animation-delay: 240ms" aria-hidden="true" />
            <p class="text-[14px] leading-relaxed text-ink-muted">
              Pulse never asks for a password and never sees one. It sends you to identity, which checks the session it
              already holds and hands back a short-lived token for this product alone.
            </p>
          </div>

          <p
            v-if="asked"
            class="sec mono mt-8 inline-flex items-center gap-2 rounded-md bg-info-surface px-3 py-2 text-[11px] text-info"
            style="animation-delay: 120ms"
          >
            <Icon name="shield" class="h-3.5 w-3.5" />
            Sign in required · continuing to {{ asked }}
          </p>

          <ul class="sec mt-10 grid gap-px border-t border-line-subtle sm:grid-cols-2" style="animation-delay: 160ms">
            <li v-for="[n, t] in TRUST" :key="n" class="flex items-baseline gap-2.5 border-b border-line-subtle py-3">
              <span class="mono text-[11px] text-ink-faint">{{ n }}</span>
              <span :class="[MONO_LABEL, 'text-ink-muted']">{{ t }}</span>
            </li>
          </ul>
        </div>

        <!-- action column -->
        <div class="sec relative border-line-subtle pb-16 lg:col-span-5 lg:border-l lg:py-20 lg:pl-10" style="animation-delay: 120ms">
          <Cross class="absolute -left-[5px] -top-[5px] hidden lg:block" />

          <div class="flex items-center gap-2.5">
            <Mark />
            <div class="leading-none">
              <p class="text-[13px] font-medium tracking-tight">Meridian</p>
              <p :class="[MONO_LABEL, 'mt-1 text-ink-faint']">Pulse</p>
            </div>
          </div>

          <h2 class="mt-8 text-[15px] font-medium tracking-tight">Continue with your Meridian account</h2>
          <p class="mt-2 max-w-[42ch] text-[13px] leading-relaxed text-ink-muted">
            If you are already signed in on this browser, this takes a second and no password is asked for. If you are
            not, identity asks for one and brings you straight back here.
          </p>

          <p v-if="note" role="alert" class="mt-5 rounded-md bg-warn-surface px-3 py-2 text-[12.5px] leading-relaxed text-warn">
            {{ note }}
          </p>

          <div class="mt-6">
            <Btn full arrow :busy="busy" @click="onContinue">
              {{ busy ? "Taking you to Meridian…" : "Continue to Meridian" }}
            </Btn>
          </div>

          <p class="mt-6 text-[12px] leading-relaxed text-ink-muted">
            Trouble getting in?
            <a :href="`${identityWebUrl}/login`" :class="[FOCUS, 'rounded font-medium text-ink transition-colors hover:text-ink-muted']">
              Sign in at Meridian
            </a>
            and open Pulse from the product picker. Pulse accounts are created by your department admin — there is no
            sign-up here.
          </p>
        </div>
      </div>
    </main>

    <footer class="border-t border-line-subtle">
      <div class="mx-auto flex w-full max-w-[1200px] flex-wrap items-center justify-between gap-4 px-5 py-7 sm:px-8">
        <a :href="`${identityWebUrl}/products`" :class="[FOCUS, 'group/b inline-flex items-center gap-2 rounded text-[12.5px] text-ink-muted transition-colors hover:text-ink']">
          <Icon name="arrowLeft" class="h-3.5 w-3.5 transition-transform group-hover/b:-translate-x-0.5" />
          All products
        </a>
        <span :class="[MONO_LABEL, 'text-ink-faint']">access token · 15 min</span>
      </div>
    </footer>
  </div>
</template>
