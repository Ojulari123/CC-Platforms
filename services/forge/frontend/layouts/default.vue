<script setup lang="ts">
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

// Forge's own routes. PRODUCT_NAV lists Overview alone because the prototype had a
// single screen; the shipped app has four, and a route with no way to reach it is a
// route nobody uses.
const NAV = [
  { label: "Overview", to: "/" },
  { label: "Datasets", to: "/datasets" },
  { label: "Learning", to: "/learning" },
  { label: "Canvas", to: "/canvas" },
];

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
    readout="upload live · paths week 6"
    :all-products-to="allProductsTo"
    @sign-out="onSignOut"
  >
    <slot />
  </ProductShell>
</template>
