<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import RulerStrip from "./RulerStrip.vue";
import TopBar from "./TopBar.vue";
import type { NavItem, ProductKey } from "../types/ui";
import { CONTENT, FOCUS, PRODUCT_LABEL, PRODUCT_NAV, TAP, navMatch } from "../utils/ui";
import { LIVE_REGION_ID } from "../composables/useAnnounce";

// The chrome every product screen sits in.
const props = withDefaults(
  defineProps<{
    product: ProductKey;
    userName?: string;
    readout?: string;
    /** Defaults to PRODUCT_NAV[product]. */
    navItems?: NavItem[];
    /** Defaults to the open route's path. */
    current?: string;
    accountTo?: string;
    allProductsTo?: string;
    homeTo?: string;
    /** Set false for "sign out lives on the product picker only" — the bar then offers
        the way out to identity ("All products") and nothing that ends the session. */
    showSignOut?: boolean;
  }>(),
  { homeTo: "/", showSignOut: true },
);

const emit = defineEmits<{ signOut: [] }>();

const route = useRoute();
const items = computed(() => props.navItems ?? PRODUCT_NAV[props.product]);
const active = computed(() => navMatch(props.current ?? route.path, items.value));

/* The sub-nav is a scrolling strip, not a wrap: six Pulse entries need 485px and a phone
   gives 390, and wrapping them onto a second line moves the page down by a row on the one
   screen size with the least of it. Scrolling costs nothing on desktop, where they fit.

   What a strip has to earn is that nothing hides in it: `scroll-px` keeps the gutter, the
   open section is pulled on screen (landing on /sync otherwise shows a nav whose underline
   is off the right edge, which reads as no section being open at all), and so is whatever
   Tab reaches — Chromium leaves a partly-visible link where it is, and a 5px-clipped entry
   is an entry whose focus ring has no left edge. */
const rail = ref<HTMLElement | null>(null);

// scrollLeft by hand rather than scrollIntoView: that one walks every scrollable ancestor,
// so on a restored back-navigation it can drag the whole page up to show a nav that was
// deliberately scrolled past. Nothing outside the strip should move.
function reveal(link: HTMLElement | null | undefined) {
  const strip = rail.value;
  if (!strip || !link || strip.scrollWidth <= strip.clientWidth) return;
  const gutter = Number.parseFloat(getComputedStyle(strip).scrollPaddingLeft) || 0;
  const box = strip.getBoundingClientRect();
  const item = link.getBoundingClientRect();
  const pastRight = item.right - (box.right - gutter);
  const pastLeft = box.left + gutter - item.left;
  if (pastRight > 0) strip.scrollLeft += pastRight;
  else if (pastLeft > 0) strip.scrollLeft -= pastLeft;
}

function revealActive() {
  reveal(rail.value?.querySelector<HTMLElement>('[aria-current="page"]'));
}

function onNavFocus(event: FocusEvent) {
  reveal((event.target as HTMLElement | null)?.closest?.("a"));
}

onMounted(revealActive);
watch(active, () => nextTick(revealActive));
</script>

<template>
  <div class="min-h-screen w-full overflow-x-hidden bg-app font-sans text-ink">
    <TopBar
      :breadcrumb="PRODUCT_LABEL[product]"
      signed-in
      :show-sign-out="showSignOut"
      :user-name="userName"
      :home-to="homeTo"
      :account-to="accountTo"
      :all-products-to="allProductsTo"
      @sign-out="emit('signOut')"
    />
    <RulerStrip v-bind="readout === undefined ? {} : { readout }" />

    <div class="border-b border-line-subtle">
      <nav
        ref="rail"
        :aria-label="`${PRODUCT_LABEL[product]} sections`"
        :class="['flex items-center gap-1 overflow-x-auto overscroll-x-contain scroll-px-5 sm:scroll-px-8', CONTENT]"
        @focusin="onNavFocus"
      >
        <NuxtLink
          v-for="item in items"
          :key="item.to"
          :to="item.to"
          :aria-current="item.to === active ? 'page' : undefined"
          :class="[
            FOCUS,
            TAP,
            'relative shrink-0 px-2.5 py-3 text-[13px] transition-colors',
            item.to === active ? 'font-medium text-ink' : 'text-ink-faint hover:text-ink-muted',
          ]"
        >
          {{ item.label }}
          <span v-if="item.to === active" class="rule-draw absolute inset-x-0 bottom-0 h-px bg-ink" />
        </NuxtLink>
        <span class="mono ml-auto hidden shrink-0 pl-4 text-[12px] uppercase tracking-[0.08em] text-ink-faint sm:inline">
          {{ PRODUCT_LABEL[product] }} console
        </span>
      </nav>
    </div>

    <!-- The entrance belongs to the content. The bar and the ruler are the frame the
         content moves inside, so they must not re-animate. -->
    <main id="main" :class="['route-enter pb-20 pt-12', CONTENT]">
      <slot />
    </main>

    <!-- Empty, and mounted for the life of the screen: see composables/useAnnounce. -->
    <div :id="LIVE_REGION_ID" role="status" aria-live="polite" class="sr-only" />
  </div>
</template>
