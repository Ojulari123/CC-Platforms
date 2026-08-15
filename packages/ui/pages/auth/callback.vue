<script setup lang="ts">
import { CONTENT, FOCUS, MONO_LABEL } from "../../utils/ui";

/* Both ends of the cross-product handoff, on one route, because they are one round trip:
     /auth/callback?start=1&next=/reports   → no session here, go and ask identity
     /auth/callback#access_token=…&state=…  → identity answered, take the token and carry on

   Inherited by every product on this layer, so a product gets the return landing without
   writing one. See composables/useSSO.ts for what does and does not cross the origin.

   Every way out of here that is not a signed-in session ends on the failure screen with a
   reason, and writes one line to the console. There used to be a path that quietly sent
   the person to the product's home instead; the product's own guard then bounced them to
   /login, and the whole thing read as "it signed me out" rather than "the handoff never
   started". A wrong story is worse than an error. */

definePageMeta({ layout: false });

const auth = useAuth();
const sso = useSSO();
const storage = useTokenStorage();
const route = useRoute();

const failure = ref<{ code: string; text: string; outbound: boolean } | null>(null);

/* The outbound leg leaves through window.location.replace, so this document has normally
   stopped existing well before this elapses. If it has not, the leg went nowhere — and a
   spinner that never resolves is the least legible failure of the lot. */
const STALL_MS = 6000;
let stallTimer: ReturnType<typeof setTimeout> | null = null;
let hadSession = false;

const REASONS: Record<string, string> = {
  "no-handoff": "This address only means something in the middle of signing in. There is nothing here to finish.",
  "no-token": "Identity sent you back without a token. Nothing was signed in and nothing was changed.",
  "state-mismatch": "This browser did not start this sign-in, so the token was refused. If you followed a link from a message, ignore it and sign in from the product itself.",
  denied: "Identity did not recognise a session, so there was nothing to hand over.",
  unconfigured: "Cross-product sign-in is not configured for this product yet, so there was nothing to hand the sign-in to. Signing in here still works.",
  "handoff-failed": "This product could not hand the sign-in over to identity. Nothing was started and nothing was changed.",
  "handoff-stalled": "Identity was asked to take over the sign-in and nothing came back. Nothing was signed in.",
};

function describe(reason: string): string {
  return REASONS[reason] ?? "The sign-in handoff did not complete. Nothing was changed.";
}

const status = computed(() => {
  if (!failure.value) return "Signing in";
  return failure.value.outbound ? "Handoff did not start" : "Handoff refused";
});

function clearStall() {
  if (stallTimer !== null) {
    clearTimeout(stallTimer);
    stallTimer = null;
  }
}

/* One line, one shape, on every path that ends in a failure. Inputs only: the reason code,
   the config state, and whether the two things that decide the branch were there. Never the
   token and never the state value — both are credential material, and a console line
   outlives the fragment it came from. */
function fail(code: string, where: string, detail?: unknown) {
  clearStall();
  failure.value = { code, text: describe(code), outbound: where.startsWith("outbound") };
  console.warn("[sso] callback did not complete", {
    branch: where,
    reason: code,
    configured: sso.configured.value,
    start: route.query.start !== undefined,
    hadSession,
    ...(detail === undefined ? {} : { detail: detail instanceof Error ? detail.message : String(detail) }),
  });
}

onBeforeUnmount(clearStall);

onMounted(async () => {
  auth.hydrate();
  hadSession = auth.isAuthenticated.value;

  const result = sso.consumeHandoff();

  if (result.ok) {
    /* Only the access token crosses, so the product holds no refresh token of its own and
       writes an empty one rather than a copy of identity's — see useSSO. When this token
       expires the product asks identity again; it does not try to rotate what it has. */
    auth.accessToken.value = result.tokens.accessToken;
    storage.write({ accessToken: result.tokens.accessToken, refreshToken: "" });
    try {
      await auth.fetchMe();
    } catch {
      // Non-fatal: the token is good enough to make requests with; only the name is missing.
    }
    await navigateTo(result.next, { replace: true });
    return;
  }

  // Nothing to consume: this is the outbound leg, or somebody opened the URL by hand.
  if (result.reason === "no-handoff") {
    const next = safeNextPath(typeof route.query.next === "string" ? route.query.next : "/");
    if (hadSession) {
      await navigateTo(next, { replace: true });
      return;
    }
    if (route.query.start !== undefined) {
      // A product that has not been given the SSO config cannot start anything, so say
      // that, here, rather than landing on a page whose guard will tell a different story.
      if (!sso.configured.value) {
        fail("unconfigured", "outbound:unconfigured");
        return;
      }
      try {
        sso.startHandoff(next);
      } catch (err: unknown) {
        // startHandoff throws on missing config and on a return URL the far end would
        // reject. Uncaught, that left this screen on "One moment." for good.
        fail("handoff-failed", "outbound:threw", err);
        return;
      }
      stallTimer = setTimeout(() => {
        stallTimer = null;
        fail("handoff-stalled", "outbound:stalled");
      }, STALL_MS);
      return;
    }
  }

  fail(result.reason, "return");
});
</script>

<template>
  <div class="min-h-screen bg-app font-sans text-ink">
    <main id="main" :class="['flex min-h-screen flex-col justify-center py-20', CONTENT]">
      <p :class="[MONO_LABEL, 'text-ink-faint']">{{ status }}</p>

      <template v-if="failure">
        <h1 class="mt-4 max-w-[18ch] text-[clamp(1.75rem,3.6vw,2.5rem)] font-semibold leading-[1.02] tracking-[-0.035em]">
          That did not complete.
        </h1>
        <p role="alert" class="mt-5 max-w-[52ch] text-[13.5px] leading-relaxed text-ink-muted">{{ failure.text }}</p>
        <!-- The code, verbatim, so it can be read out or pasted into a message. It is the
             same string the console line carries. -->
        <p class="mono mt-3 text-[11px] tracking-[0.06em] text-ink-muted">Reason: {{ failure.code }}</p>
        <p class="mt-6">
          <NuxtLink to="/login" :class="[FOCUS, 'inline-flex items-center gap-1.5 rounded text-[13px] font-medium text-ink hover:text-ink-muted']">
            Sign in here instead
          </NuxtLink>
        </p>
      </template>

      <template v-else>
        <h1 class="mt-4 max-w-[18ch] text-[clamp(1.75rem,3.6vw,2.5rem)] font-semibold leading-[1.02] tracking-[-0.035em]">
          One moment.
        </h1>
        <p role="status" class="mt-5 max-w-[52ch] text-[13.5px] leading-relaxed text-ink-muted">
          Checking your session with identity, then taking you where you were going.
        </p>
      </template>
    </main>
  </div>
</template>
