<script setup lang="ts">
// The chrome moved into <PulseShell>, which each screen renders itself so it can set
// its own ruler readout. What is left here is the session: tokens live in localStorage,
// so they have to be read back before anything asks who the user is.
const auth = useAuth();
const { me, load } = useMe();

onMounted(async () => {
  auth.hydrate();
  if (auth.isAuthenticated.value && !me.value) await load();
});
</script>

<template>
  <slot />
</template>
