import { safeNextPath } from "./useSSO";

/* Signing out of a product has to end the session on the server, not only in this tab.

   A product holds one short-lived access token and no refresh token — the refresh family
   stays inside identity's origin and never crosses the handoff (see useSSO). So clearing
   this origin's localStorage leaves identity's session, and every other product's, alive:
   the control says "sign out" and does not. That is the bug this exists to remove.

   /auth/logout-all is the revocation a bearer of an access token can actually perform. It
   revokes every refresh family for the user and bumps token_version, which also kills the
   access tokens the other origins are still holding. It is wider than "this session" by
   design: a product cannot name its own session, because it never held the token that
   identifies one. /auth/logout is the narrow version and needs the refresh token, so it
   stays where the refresh token is — identity's own useSignOut. */

export function useGlobalSignOut() {
  const config = useRuntimeConfig();
  const auth = useAuth();
  const identityUrl = config.public.identityUrl as string;
  const identityWebUrl = (config.public.identityWebUrl ?? "") as string;

  /** `landing` is an in-app path on identity, supplied by the caller. Never a value off
      the query string: a sign-out that forwards wherever it is told is an open redirect
      pointed at someone who has just been logged out of everything. */
  return async function signOutEverywhere(landing = "/login"): Promise<void> {
    const token = auth.accessToken.value;
    if (token) {
      try {
        await $fetch(`${identityUrl}/auth/logout-all`, {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
        });
      } catch {
        // The local session goes either way: a failed revoke must not strand someone
        // signed in on a device they are trying to leave.
      }
    }
    auth.logout();

    const path = safeNextPath(landing, "/login");
    if (!identityWebUrl) {
      await navigateTo(path);
      return;
    }
    // Absolute, and built from runtimeConfig — the three apps are three origins, so
    // landing signed out means leaving this one.
    await navigateTo(new URL(path, identityWebUrl).toString(), { external: true });
  };
}
