<script setup lang="ts">
import type { NuxtError } from "#app";
import { FOCUS, MONO_LABEL } from "@crescent/ui/utils/ui";

/* Where an unknown route lands. Not a joke and not a dead end: the only useful thing a
   404 can do is say plainly what was not found and hand back the two or three places
   worth going. What it offers depends on whether there is a session — signed out, a list
   of product links is an invitation to bounce off a sign-in wall; signed in, the front
   page is the least useful link on the site. */

const props = defineProps<{ error: NuxtError }>();

const auth = useAuth();
const route = useRoute();
const signedIn = ref(false);

onMounted(() => {
  auth.hydrate();
  signedIn.value = auth.isAuthenticated.value;
});

const status = computed(() => props.error?.statusCode ?? 404);
const notFound = computed(() => status.value === 404);

// The address may be a mistyped invite or reset link, so it is truncated on the way to
// the screen rather than printed whole.
const asked = computed(() => {
  const path = route.fullPath ?? "";
  return path.length > 24 ? `${path.slice(0, 24)}…` : path;
});

async function go(to: string) {
  await clearError({ redirect: to });
}

useHead({ title: () => (notFound.value ? "Not found" : "Something went wrong") });
</script>

<template>
  <div class="min-h-screen w-full overflow-x-hidden bg-app font-sans text-ink antialiased">
    <TopBar
      :signed-in="signedIn"
      :home-to="signedIn ? '/products' : '/'"
      :sign-in-to="signedIn ? undefined : '/login'"
      :get-started-to="signedIn ? undefined : '/login?mode=signup'"
      :all-products-to="signedIn ? '/products' : undefined"
      :account-to="signedIn ? '/account' : undefined"
    />
    <RulerStrip :readout="notFound ? 'route · unresolved' : `error · ${status}`" />

    <main id="main" class="relative mx-auto w-full max-w-[1200px] px-5 sm:px-8">
      <div class="grid lg:grid-cols-12">
        <!-- editorial column -->
        <div class="relative border-line-subtle py-12 lg:col-span-7 lg:border-l lg:py-20 lg:pl-10 lg:pr-14">
          <RuleTicks />
          <Cross class="absolute -left-[5px] -top-[5px] hidden lg:block" />

          <div class="sec flex items-center gap-3">
            <Eyebrow>{{ notFound ? "Not found" : "Failed" }}</Eyebrow>
            <span class="rule-draw h-px w-8 bg-line" style="animation-delay: 160ms" aria-hidden="true" />
            <span :class="[MONO_LABEL, 'text-ink-faint']">{{ status }}</span>
          </div>

          <h1
            class="sec mt-6 max-w-[18ch] text-[clamp(2rem,4.6vw,3.2rem)] font-semibold leading-[0.98] tracking-[-0.04em]"
            style="animation-delay: 40ms"
          >
            <template v-if="notFound">
              There is nothing<br />
              <span class="text-ink-muted">at that address.</span>
            </template>
            <template v-else>
              That request<br />
              <span class="text-ink-muted">did not finish.</span>
            </template>
          </h1>

          <div class="sec mt-8 flex max-w-[48ch] gap-5" style="animation-delay: 80ms">
            <span class="rule-draw mt-1 h-px w-8 shrink-0 bg-line-strong" style="animation-delay: 240ms" aria-hidden="true" />
            <p v-if="notFound" class="text-[14px] leading-relaxed text-ink-muted">
              The route was asked for and no screen answered. That is all this means — nothing was deleted, nothing was
              hidden from you, and no permission was refused. A page you are not allowed to open sends you to sign in
              instead, and says so when it does.
            </p>
            <p v-else class="text-[14px] leading-relaxed text-ink-muted">
              Something failed on the way to rendering this screen. Nothing you did was saved twice and nothing was lost by
              landing here; the safe move is to go back to a known place and try again.
            </p>
          </div>

          <ul v-if="notFound" class="sec mt-10 grid gap-px border-t border-line-subtle" style="animation-delay: 160ms">
            <li
              v-for="entry in [
                ['A link from an email', 'Long links get cut in half by some mail clients. Copy the whole thing, or open it from the message rather than pasting it.'],
                ['A bookmark from before', 'Screens move as the platform is built. The product still exists even when the old address does not.'],
                ['Something typed by hand', 'One wrong character is enough. There is no guessing here — an address either resolves or it does not.'],
              ]"
              :key="entry[0]"
              class="border-b border-line-subtle py-3.5"
            >
              <p class="text-[13px] font-medium tracking-tight">{{ entry[0] }}</p>
              <p class="mt-1 max-w-[52ch] text-[12.5px] leading-relaxed text-ink-muted">{{ entry[1] }}</p>
            </li>
          </ul>

          <p :class="[MONO_LABEL, 'mt-6 text-ink-faint']">requested {{ asked }} · nothing changed</p>
        </div>

        <!-- routes column -->
        <div class="sec relative border-line-subtle pb-16 lg:col-span-5 lg:border-l lg:py-20 lg:pl-10" style="animation-delay: 120ms">
          <Cross class="absolute -left-[5px] -top-[5px] hidden lg:block" />

          <h2 class="mt-12 text-[17px] font-semibold tracking-tight lg:mt-0">Where to go instead</h2>

          <template v-if="signedIn">
            <p class="mt-2 max-w-[38ch] text-[13.5px] leading-relaxed text-ink-muted">
              Your session is fine. Only the address was wrong.
            </p>
            <div class="mt-6 space-y-2.5">
              <Btn full arrow @click="go('/products')">All products</Btn>
              <Btn full variant="secondary" @click="go('/account')">Your account</Btn>
            </div>
          </template>

          <template v-else>
            <p class="mt-2 max-w-[38ch] text-[13.5px] leading-relaxed text-ink-muted">
              There is no session on this browser, so most of the platform is behind the front desk anyway. Start at one of
              these.
            </p>
            <div class="mt-6 space-y-2.5">
              <Btn full arrow @click="go('/')">The front page</Btn>
              <Btn full variant="secondary" @click="go('/login')">Sign in</Btn>
            </div>

            <div class="mt-6 border-t border-line-subtle pt-4">
              <p class="text-[12.5px] leading-relaxed text-ink-muted">
                If you were opening an invitation or a reset link and it broke on the way, the link itself is the problem
                rather than this page.
              </p>
              <button
                type="button"
                :class="[FOCUS, 'group/a mt-2.5 inline-flex items-center gap-1.5 rounded text-[12px] font-medium text-ink transition-colors hover:text-ink-muted']"
                @click="go('/forgot-password')"
              >
                Ask for a new reset link
                <Icon name="arrow" class="h-3.5 w-3.5 transition-transform group-hover/a:translate-x-0.5" />
              </button>
            </div>
          </template>
        </div>
      </div>
    </main>

    <footer class="border-t border-line-subtle">
      <div class="mx-auto flex w-full max-w-[1200px] flex-wrap items-center justify-between gap-4 px-5 py-7 sm:px-8">
        <button
          type="button"
          :class="[FOCUS, 'group/b inline-flex items-center gap-2 rounded text-[12.5px] text-ink-muted transition-colors hover:text-ink']"
          @click="go(signedIn ? '/products' : '/')"
        >
          <Icon name="arrowLeft" class="h-3.5 w-3.5 transition-transform group-hover/b:-translate-x-0.5" />
          {{ signedIn ? "All products" : "Back to Meridian" }}
        </button>
        <span :class="[MONO_LABEL, 'text-ink-faint']">{{ notFound ? "no screen · no error" : "error · logged" }}</span>
      </div>
    </footer>
  </div>
</template>
