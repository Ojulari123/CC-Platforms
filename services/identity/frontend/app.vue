<script setup lang="ts">
const auth = useAuth();

// One place for the session, because it has to be right on a page with no layout (the
// landing, the sign-in screen) as well as on the console pages that have one.
onMounted(async () => {
  auth.hydrate();
  if (auth.isAuthenticated.value && !auth.user.value) {
    try {
      await auth.fetchMe();
    } catch {
      // Non-fatal: the screen still works, it just can't label the signed-in person.
    }
  }
});

useHead({
  titleTemplate: (title) => (title ? `${title} · Meridian` : "Meridian"),
  htmlAttrs: { lang: "en" },
});
</script>

<template>
  <div class="min-h-screen w-full overflow-x-hidden bg-app font-sans text-ink antialiased">
    <NuxtLayout>
      <NuxtPage />
    </NuxtLayout>
  </div>
</template>
