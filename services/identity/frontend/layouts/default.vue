<script setup lang="ts">
import type { NavItem } from "@crescent/ui/types/ui";
import { PRODUCT_NAV } from "@crescent/ui/utils/ui";
import type { UserMeResponse } from "~/types/api";

/* The console chrome: top bar, ruler, product sub-nav. The umbrella screens (/, /login,
   /products, /account) are not console screens and set `layout: false` — they carry their
   own TopBar, because none of them belongs under an "Identity console" sub-nav. */

const auth = useAuth();
const router = useRouter();
const signOut = useSignOut();

const me = computed(() => auth.user.value as UserMeResponse | null);

const displayName = computed(() => {
  const user = me.value;
  return user ? fullName(user.first_name, user.last_name, user.email) : undefined;
});

// The console routes land over several pull requests, so the sub-nav offers what is
// actually registered rather than a fixed list with dead links in it. `/users` is the
// address People sits at today.
const navItems = computed<NavItem[]>(() => {
  const paths = new Set(router.getRoutes().map((route) => route.path));
  return PRODUCT_NAV.identity.flatMap((item) => {
    if (paths.has(item.to)) return [item];
    if (item.to === "/people" && paths.has("/users")) return [{ ...item, to: "/users" }];
    return [];
  });
});

const readout = computed(() => (me.value ? `user_id ${me.value.id}` : undefined));
</script>

<template>
  <ProductShell
    product="identity"
    :user-name="displayName"
    :nav-items="navItems"
    :readout="readout"
    home-to="/products"
    account-to="/account"
    all-products-to="/products"
    @sign-out="signOut"
  >
    <slot />
  </ProductShell>
</template>
