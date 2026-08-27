<script setup lang="ts">
import type { NuxtError } from "#app";

/* Where an unknown address lands. Nuxt's stock page has one button and no idea whether
   there is a session, so a wrong URL inside Forge read as a dead end. The screen itself is
   shared: packages/ui/components/ErrorScreen.vue. */

const props = defineProps<{ error: NuxtError }>();

const auth = useAuth();
const route = useRoute();
const config = useRuntimeConfig();

const identityWebUrl = config.public.identityWebUrl as string;
const allProductsTo = identityWebUrl ? `${identityWebUrl}/products` : undefined;

const signedIn = ref(false);

onMounted(async () => {
  auth.hydrate();
  signedIn.value = auth.isAuthenticated.value;
  // A bar that draws an avatar with no name in it is worse than no avatar.
  if (signedIn.value && !auth.user.value) {
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

const status = computed(() => props.error?.statusCode ?? 404);

// The address may be a mistyped invite or reset link, so it is truncated before it is shown.
const asked = computed(() => {
  const path = route.fullPath ?? "";
  return path.length > 24 ? `${path.slice(0, 24)}…` : path;
});

// clearError's `redirect` is an internal path, so an absolute URL through it becomes
// http://localhost:3001/http://localhost:3002/products. The picker is another origin.
async function go(to: string) {
  if (/^https?:\/\//.test(to)) {
    window.location.assign(to);
    return;
  }
  await clearError({ redirect: to });
}

useHead({ title: () => (status.value === 404 ? "Not found · Forge" : "Something went wrong · Forge") });
</script>

<template>
  <ErrorScreen
    :status="status"
    home-to="/"
    product-name="Forge"
    :all-products-to="allProductsTo"
    :signed-in="signedIn"
    :user-name="displayName"
    sign-in-to="/login"
    :asked="asked"
    @go="go"
  />
</template>
