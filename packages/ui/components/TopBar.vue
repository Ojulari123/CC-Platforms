<script setup lang="ts">
import Avatar from "./Avatar.vue";
import Icon from "./Icon.vue";
import Mark from "./Mark.vue";
import ThemeToggle from "./ThemeToggle.vue";
import type { NavItem } from "../types/ui";
import { CONTENT, FOCUS, TAP } from "../utils/ui";

/* Sticky, 56px. Every control here is a real link or a real button — a control whose
   destination is not supplied is not rendered at all rather than wired to a no-op. */
withDefaults(
  defineProps<{
    signedIn: boolean;
    /** Renders as "Meridian / Pulse". Omit on the umbrella pages. */
    breadcrumb?: string;
    userName?: string;
    navItems?: NavItem[];
    homeTo?: string;
    signInTo?: string;
    getStartedTo?: string;
    /** Cross-product hop. Absolute while the three apps hold separate token namespaces. */
    allProductsTo?: string;
    /** Makes the name and avatar the way into the account screen. Left off they stay a
        label — signing out keeps its own control either way. */
    accountTo?: string;
    showSignOut?: boolean;
    /** Target of the skip link. */
    skipTo?: string;
  }>(),
  { homeTo: "/", skipTo: "#main", showSignOut: false },
);

const emit = defineEmits<{ signOut: [] }>();
</script>

<template>
  <!-- `sr-only` is position:absolute, so the skip link needs a positioned ancestor — this
       sticky header — or it anchors to the page and widens it. -->
  <header class="sticky top-0 z-40 border-b border-line-subtle bg-app/85 backdrop-blur-xl">
    <a
      :href="skipTo"
      :class="[FOCUS, 'sr-only rounded-md bg-surface px-3 py-2 text-[13px] text-ink ring-1 ring-line focus:not-sr-only focus:absolute focus:left-4 focus:top-2 focus:z-50']"
    >
      Skip to content
    </a>

    <!-- The nav between these two clusters is `md:flex`, so below that this gap is just
         the space between the brand and the account controls, and 24px of it was the last
         thing keeping "Pulse" from fitting at 390px. -->
    <div :class="['flex h-14 items-center gap-3 md:gap-6', CONTENT]">
      <div class="flex min-w-0 items-center gap-2.5">
        <!-- `shrink-0` is load-bearing. Without it the flex algorithm squeezed this link's
             box (to 64.5px at 390px wide) while its 94.7px of content carried on painting,
             so the wordmark ran 6.2px under the theme toggle on Pulse at 390 and 36.2px at
             360. The box now keeps its content, and the breadcrumb beside it — which has
             `truncate` and a `min-w-0` parent — is the one thing that gives. -->
        <NuxtLink :to="homeTo" :class="[FOCUS, TAP, 'flex shrink-0 items-center gap-2.5 rounded']" aria-label="Meridian home">
          <Mark />
          <!-- Same rule as "All products" below: the label folds on a narrow screen, the
               link does not. The Mark is still the way home, and on a phone the product
               name is the more useful of the two words. -->
          <span class="hidden text-[14px] font-semibold tracking-tight min-[490px]:inline">Meridian</span>
        </NuxtLink>
        <template v-if="breadcrumb">
          <!-- The separator goes with the word it separates from. Left in while the
               wordmark is folded it read "/ Pulse", and cost the 18px that was the
               difference between the product name fitting at 390px and truncating to
               "P.". -->
          <span class="hidden text-[14px] text-ink-faint min-[490px]:inline" aria-hidden="true">/</span>
          <span class="truncate text-[14px] font-medium tracking-tight text-ink-muted">{{ breadcrumb }}</span>
        </template>
      </div>

      <nav v-if="navItems && navItems.length" class="hidden items-center gap-1 md:flex" aria-label="Primary">
        <NuxtLink
          v-for="item in navItems"
          :key="item.label"
          :to="item.to"
          :aria-current="item.active ? 'page' : undefined"
          :class="[
            FOCUS,
            TAP,
            'rounded-md px-2.5 py-1.5 text-[13px] transition-colors hover:bg-surface-hover hover:text-ink',
            item.active ? 'text-ink' : 'text-ink-muted',
          ]"
        >
          {{ item.label }}
        </NuxtLink>
      </nav>

      <div class="ml-auto flex shrink-0 items-center gap-2">
        <!-- Ahead of the account cluster, and outside the signed-in branch: a login
             screen is a screen someone reads too. -->
        <ThemeToggle />

        <template v-if="signedIn">
          <NuxtLink
            v-if="allProductsTo"
            :to="allProductsTo"
            :class="[FOCUS, TAP, 'group/all inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[13px] text-ink-muted transition-colors hover:bg-surface-hover hover:text-ink']"
            aria-label="All products"
          >
            <Icon name="arrowLeft" class="h-3.5 w-3.5 transition-transform group-hover/all:-translate-x-0.5" />
            <!-- The way out of a product is the one control that must survive a narrow
                 screen, so only its label folds away, not the link. -->
            <span class="hidden sm:inline">All products</span>
          </NuxtLink>

          <NuxtLink
            v-if="accountTo"
            :to="accountTo"
            :class="[FOCUS, TAP, 'ml-1 flex items-center gap-2 rounded-md border-l border-line-subtle py-1 pl-3 pr-1.5 text-left transition-colors hover:bg-surface-hover']"
            :aria-label="`Your account, ${userName ?? ''}`"
          >
            <Avatar :name="userName ?? ''" />
            <span class="hidden text-[13px] text-ink sm:inline">{{ userName }}</span>
          </NuxtLink>
          <span v-else class="flex items-center gap-2 border-l border-line-subtle pl-3">
            <Avatar :name="userName ?? ''" />
            <span class="hidden text-[13px] text-ink sm:inline">{{ userName }}</span>
          </span>

          <button
            v-if="showSignOut"
            type="button"
            :class="[FOCUS, TAP, 'rounded-md px-2.5 py-1.5 text-[13px] text-ink-muted transition-colors hover:bg-surface-hover hover:text-ink']"
            @click="emit('signOut')"
          >
            Sign out
          </button>
        </template>

        <template v-else>
          <NuxtLink
            v-if="signInTo"
            :to="signInTo"
            :class="[FOCUS, TAP, 'rounded-md px-3 py-1.5 text-[13px] text-ink-muted transition-colors hover:bg-surface-hover hover:text-ink']"
          >
            Sign in
          </NuxtLink>
          <NuxtLink
            v-if="getStartedTo"
            :to="getStartedTo"
            :class="[FOCUS, TAP, 'group/cta inline-flex items-center gap-1.5 rounded-md bg-ink px-3 py-1.5 text-[13px] font-medium text-app transition-[transform,filter] duration-100 ease-out hover:brightness-90 active:scale-[0.98]']"
          >
            Get started
            <Icon name="arrow" class="h-3.5 w-3.5 transition-transform group-hover/cta:translate-x-0.5" />
          </NuxtLink>
        </template>
      </div>
    </div>
  </header>
</template>
