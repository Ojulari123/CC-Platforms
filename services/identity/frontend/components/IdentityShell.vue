<script setup lang="ts">
import type { NavItem } from "@crescent/ui/types/ui";
import type { UserMeResponse } from "~/types/api";

/* The chrome every Identity console screen sits in. It exists because each screen also
   has to make sure /me is populated */
withDefaults(defineProps<{ readout?: string }>(), {});

const auth = useAuth();
const router = useRouter();
const { toast, clear } = useToast();

// The directory lives at /users in this app, not the /people PRODUCT_NAV assumes
const NAV: NavItem[] = [
  { label: "People", to: "/users" },
  { label: "Organisation", to: "/departments" },
  { label: "Access", to: "/access" },
  { label: "Sessions", to: "/sessions" },
];

const me = computed(() => auth.user.value as UserMeResponse | null);
const userName = computed(() => {
  const u = me.value;
  return u ? fullName(u.first_name, u.last_name, u.email) : "";
});

onMounted(async () => {
  auth.hydrate();
  if (auth.isAuthenticated.value && !auth.user.value) {
    try {
      await auth.fetchMe();
    } catch {
      // the screen still renders, it just cannot label the signed-in person.
    }
  }
});

function onSignOut() {
  auth.logout();
  router.push("/login");
}
</script>

<template>
  <ProductShell
    product="identity"
    :nav-items="NAV"
    :user-name="userName"
    :readout="readout"
    account-to="/account"
    @sign-out="onSignOut"
  >
    <slot :me="me" />
    <Toast v-if="toast" :message="toast.message" :tone="toast.tone" @dismiss="clear" />
  </ProductShell>
</template>
