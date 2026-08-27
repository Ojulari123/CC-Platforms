<script setup lang="ts">
import { computed } from "vue";
import Btn from "./Btn.vue";
import Eyebrow from "./Eyebrow.vue";
import RulerStrip from "./RulerStrip.vue";
import TopBar from "./TopBar.vue";
import { CONTENT, MONO_LABEL } from "../utils/ui";

/* What a product shows on an address that resolved to nothing. Without one of these Nuxt
   serves its own stock page: a gradient, the word 404 and a single "Go back home" button
   that ignores the session. Identity keeps a longer bespoke version of this; Pulse and
   Forge wrap this one, so the way out of a wrong address is the same in both.

   Every destination is a prop because only the product knows them: its own home is
   relative, and "All products" is another origin. */
const props = withDefaults(
  defineProps<{
    status: number;
    /** The product's own signed-in home. */
    homeTo: string;
    /** Reads as "Back to Pulse". */
    productName: string;
    /** Identity's picker, absolute. Left off when the product has no identity web URL. */
    allProductsTo?: string;
    /** Signed out, the product's screens are behind a wall, so sign-in is the only offer. */
    signedIn: boolean;
    /** Without it the bar draws an avatar with no name in it. */
    userName?: string;
    signInTo: string;
    /** Printed verbatim so a wrong address can be read back. */
    asked?: string;
  }>(),
  { allProductsTo: undefined, asked: undefined, userName: undefined },
);

const emit = defineEmits<{ go: [to: string] }>();

const notFound = computed(() => props.status === 404);
const crossProduct = computed(() => (props.signedIn ? props.allProductsTo : undefined));
</script>

<template>
  <div class="min-h-screen w-full overflow-x-hidden bg-app font-sans text-ink">
    <TopBar
      :breadcrumb="productName"
      :signed-in="signedIn"
      :user-name="userName"
      :home-to="signedIn ? homeTo : signInTo"
      :sign-in-to="signedIn ? undefined : signInTo"
      :all-products-to="crossProduct"
    />
    <RulerStrip :readout="notFound ? 'route · unresolved' : `error · ${status}`" />

    <main id="main" :class="['route-enter py-16', CONTENT]">
      <div class="flex items-center gap-3">
        <Eyebrow>{{ notFound ? "Not found" : "Failed" }}</Eyebrow>
        <span class="h-px w-8 bg-line" aria-hidden="true" />
        <span :class="[MONO_LABEL, 'text-ink-faint']">{{ status }}</span>
      </div>

      <h1 class="mt-6 max-w-[18ch] text-[clamp(1.75rem,3.6vw,2.6rem)] font-semibold leading-[1.02] tracking-[-0.035em]">
        <template v-if="notFound">
          There is nothing<br />
          <span class="text-ink-muted">at that address.</span>
        </template>
        <template v-else>
          That request<br />
          <span class="text-ink-muted">did not finish.</span>
        </template>
      </h1>

      <p v-if="notFound" class="mt-6 max-w-[52ch] text-[13.5px] leading-relaxed text-ink-muted">
        The route was asked for and no screen answered. Nothing was deleted and no permission was refused. A screen you
        are not allowed to open sends you to sign in and says so when it does.
      </p>
      <p v-else class="mt-6 max-w-[52ch] text-[13.5px] leading-relaxed text-ink-muted">
        Something failed on the way to drawing this screen. Nothing was saved twice and nothing was lost by landing
        here. Go back to a known place and try again.
      </p>

      <p v-if="asked" :class="[MONO_LABEL, 'mt-4 text-ink-faint']">requested {{ asked }} · nothing changed</p>

      <div class="mt-9 flex flex-wrap items-center gap-3">
        <Btn v-if="signedIn" arrow @click="emit('go', homeTo)">Back to {{ productName }}</Btn>
        <Btn v-else arrow @click="emit('go', signInTo)">Sign in</Btn>
        <Btn v-if="crossProduct" variant="secondary" @click="emit('go', crossProduct)">All products</Btn>
      </div>

      <p v-if="!signedIn" class="mt-6 max-w-[52ch] text-[12.5px] leading-relaxed text-ink-muted">
        There is no session in this browser, so {{ productName }} is behind the sign-in wall. One account covers every
        product on the platform.
      </p>
    </main>
  </div>
</template>
