<script setup lang="ts">
const auth = useAuth();
const route = useRoute();
const router = useRouter();

const links = [
  { to: "/", label: "Dashboard" },
  { to: "/datasets", label: "Datasets" },
  { to: "/learning", label: "Learning" },
  { to: "/canvas", label: "Canvas" },
];

// The header lives outside every page, so it's the one place that needs to make
// sure /me is populated after a hard refresh.
onMounted(async () => {
  auth.hydrate();
  if (auth.isAuthenticated.value && !auth.user.value) {
    try {
      await auth.fetchMe();
    } catch {
      // non-fatal for the header
    }
  }
});

const displayName = computed(() => {
  const u = auth.user.value;
  if (!u) return null;
  const full = `${u.first_name ?? ""} ${u.last_name ?? ""}`.trim();
  return full || u.email;
});

function isActive(to: string): boolean {
  return to === "/" ? route.path === "/" : route.path.startsWith(to);
}

function onLogout() {
  auth.logout();
  router.push("/login");
}
</script>

<template>
  <div>
    <header class="border-b border-gray-200 bg-white">
      <div class="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-4 px-4 py-3">
        <div class="flex items-center gap-6">
          <NuxtLink to="/" class="text-sm font-semibold">Forge</NuxtLink>
          <nav class="flex items-center gap-4">
            <NuxtLink
              v-for="link in links"
              :key="link.to"
              :to="link.to"
              class="text-sm hover:text-gray-900"
              :class="isActive(link.to) ? 'font-medium text-gray-900' : 'text-gray-500'"
            >
              {{ link.label }}
            </NuxtLink>
          </nav>
        </div>

        <div class="flex items-center gap-3">
          <span v-if="displayName" class="hidden text-sm text-gray-500 sm:inline">
            {{ displayName }}
          </span>
          <button
            class="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium hover:bg-gray-100"
            @click="onLogout"
          >
            Log out
          </button>
        </div>
      </div>
    </header>

    <slot />
  </div>
</template>
