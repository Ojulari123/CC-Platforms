<script setup lang="ts">
import { FOCUS, MONO_LABEL } from "@crescent/ui/utils/ui";
import type { TokenPair } from "~/types/api";

/* Identity's side of the cross-product handoff.

   A product with no session sends the browser here. If there is a session on this origin,
   this screen hands back ONE short-lived access token in the URL fragment of a return
   address that is on the configured allowlist — nothing else, and nowhere else. If there
   is no session, it falls through to /login carrying this URL as `next`, so signing in
   finishes the handoff rather than dropping it.

   The refresh token deliberately does not travel: see packages/ui/composables/useSSO.ts. */

definePageMeta({ layout: false });

const auth = useAuth();
const sso = useSSO();
const route = useRoute();
const router = useRouter();
const identityUrl = useRuntimeConfig().public.identityUrl;

const refused = ref<string | null>(null);
const destination = ref<string | null>(null);

onMounted(async () => {
  const request = sso.readRequest(route.query as Record<string, unknown>);
  if (!request) {
    // Either the return address is not one this platform hands tokens to, or the product
    // did not send a state to bind the handoff to a browser. Both are refusals, and
    // neither redirects anywhere: an error page that redirects is a second open redirect.
    refused.value =
      "That sign-in request did not name a destination this platform hands tokens to. Nothing was shared. Open the product directly and sign in there.";
    return;
  }

  destination.value = new URL(request.returnTo).host;

  auth.hydrate();
  if (!auth.isAuthenticated.value) {
    await router.replace(signInPath(route.fullPath));
    return;
  }

  /* Rotate first, so the product starts with a full fifteen minutes rather than whatever
     is left of this tab's token. Identity keeps the new refresh token; only the access
     token crosses. */
  let pair: TokenPair | null = null;
  if (auth.refreshToken.value) {
    try {
      pair = await $fetch<TokenPair>(`${identityUrl}/auth/refresh`, {
        method: "POST",
        body: { refresh_token: auth.refreshToken.value },
      });
      auth.accessToken.value = pair.access_token;
      auth.refreshToken.value = pair.refresh_token;
      useTokenStorage().write({ accessToken: pair.access_token, refreshToken: pair.refresh_token });
    } catch {
      pair = null;
    }
  }

  if (!pair) {
    // No usable refresh: the session here is gone or was never rotatable. Sign in again
    // rather than handing over a token that may be seconds from expiring.
    auth.logout();
    await router.replace(signInPath(route.fullPath));
    return;
  }

  window.location.replace(sso.completeHandoff(request, pair));
});

useHead({ title: "Signing in" });
</script>

<template>
  <div class="min-h-screen w-full overflow-x-hidden bg-app font-sans text-ink">
    <main id="main" class="mx-auto flex min-h-screen w-full max-w-[1200px] flex-col justify-center px-5 py-20 sm:px-8">
      <p :class="[MONO_LABEL, 'text-ink-faint']">{{ refused ? "Handoff refused" : "One login" }}</p>

      <template v-if="refused">
        <h1 class="mt-4 max-w-[20ch] text-[clamp(1.75rem,3.6vw,2.5rem)] font-semibold leading-[1.02] tracking-[-0.035em]">
          That destination is not on the list.
        </h1>
        <p role="alert" class="mt-5 max-w-[52ch] text-[13.5px] leading-relaxed text-ink-muted">{{ refused }}</p>
        <p class="mt-6">
          <NuxtLink to="/products" :class="[FOCUS, 'rounded text-[13px] font-medium text-ink hover:text-ink-muted']">
            Back to your products
          </NuxtLink>
        </p>
      </template>

      <template v-else>
        <h1 class="mt-4 max-w-[20ch] text-[clamp(1.75rem,3.6vw,2.5rem)] font-semibold leading-[1.02] tracking-[-0.035em]">
          Handing you over.
        </h1>
        <p role="status" class="mt-5 max-w-[52ch] text-[13.5px] leading-relaxed text-ink-muted">
          Issuing a fifteen-minute access token for
          <span class="mono text-[12.5px] text-ink">{{ destination ?? "the product you asked for" }}</span
          >. Your password and your refresh token stay here.
        </p>
      </template>
    </main>
  </div>
</template>
