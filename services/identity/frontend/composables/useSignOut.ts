// Signing out should end the session on the server too, not only in this browser: the
// shared useAuth().logout() clears local storage, which leaves the refresh family alive
// and usable by anyone holding a copy of the token.
export function useSignOut() {
  const auth = useAuth();
  const identityUrl = useRuntimeConfig().public.identityUrl;
  const router = useRouter();

  return async function signOut(): Promise<void> {
    const refreshToken = auth.refreshToken.value;
    if (refreshToken) {
      try {
        await $fetch(`${identityUrl}/auth/logout`, { method: "POST", body: { refresh_token: refreshToken } });
      } catch {
        // The local session goes either way; a failed revoke must not strand someone
        // signed in on a device they are trying to leave.
      }
    }
    auth.logout();
    await router.push("/login");
  };
}
