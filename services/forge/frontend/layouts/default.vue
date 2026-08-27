<script setup lang="ts">
import { PRODUCT_NAV } from "@crescent/ui/utils/ui";
// The chrome every signed-in Forge screen sits in. Login and signup opt out with
// `definePageMeta({ layout: false })`.
const auth = useAuth();
const config = useRuntimeConfig();

// One login covers all three products, so being inside Forge must not be a dead end.
// Identity's picker is another origin, so the link is absolute and comes from config.
const identityWebUrl = config.public.identityWebUrl as string;
const allProductsTo = identityWebUrl ? `${identityWebUrl}/products` : undefined;

// Revokes server-side before clearing this origin, then lands on identity signed out.
// Pass `:show-sign-out="false"` to ProductShell below to move signing out to the picker.
const onSignOut = useGlobalSignOut();

// Forge's own routes, from the shared layer so the sub-nav and PRODUCT_NAV cannot drift.
const NAV = PRODUCT_NAV.forge;

// The layout lives outside every page, so it is the one place that has to make sure
// /me is populated after a hard refresh.
onMounted(async () => {
  auth.hydrate();
  if (auth.isAuthenticated.value && !auth.user.value) {
    try {
      await auth.fetchMe();
    } catch {
      // non-fatal for the chrome
    }
  }
});

const displayName = computed(() => {
  const u = auth.user.value;
  if (!u) return undefined;
  const full = `${u.first_name ?? ""} ${u.last_name ?? ""}`.trim();
  return full || u.email;
});
</script>

<template>
  <ProductShell
    product="forge"
    :user-name="displayName"
    :nav-items="NAV"
    readout="canvas live · code export live"
    :all-products-to="allProductsTo"
    @sign-out="onSignOut"
  >
    <slot />
  </ProductShell>
</template>
