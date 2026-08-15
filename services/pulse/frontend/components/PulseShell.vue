<script setup lang="ts">
import type { ToastMessage } from "@crescent/ui/types/ui";

// ProductShell takes `to` paths and renders NuxtLink, so what this has to wire is the
// pair of controls that leave Pulse. `readout` is the one part of the ruler a screen sets.
defineProps<{ readout?: string }>();

const auth = useAuth();
const config = useRuntimeConfig();
const { toast, clear } = useToast();

// One login covers all three products, so being inside Pulse must not be a dead end.
// Identity's picker is another origin, so the link is absolute and comes from config.
const identityWebUrl = config.public.identityWebUrl as string;
const allProductsTo = identityWebUrl ? `${identityWebUrl}/products` : undefined;

// Revokes server-side before clearing this origin, then lands on identity signed out.
// Pass `:show-sign-out="false"` to ProductShell below to move signing out to the picker.
const onSignOut = useGlobalSignOut();

const displayName = computed(() => {
  const user = auth.user.value;
  if (!user) return undefined;
  const full = `${user.first_name ?? ""} ${user.last_name ?? ""}`.trim();
  return full || user.email;
});
</script>

<template>
  <ProductShell
    product="pulse"
    :user-name="displayName"
    :readout="readout"
    :all-products-to="allProductsTo"
    @sign-out="onSignOut"
  >
    <slot />
  </ProductShell>

  <Toast
    v-if="toast"
    :message="(toast as ToastMessage).message"
    :tone="(toast as ToastMessage).tone"
    @dismiss="clear"
  />
</template>
