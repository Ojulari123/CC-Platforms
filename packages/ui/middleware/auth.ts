import { isSafeNextPath, stripFragment } from "../composables/useSSO";

/** Where an unauthenticated request to a guarded route goes, carrying the intent. Sending
    everyone to a bare /login loses what they asked for, which on a deep link — a report,
    a department, an invite — means signing in and then having to find the page again.

    A `next` that leaves the app, or points back at the sign-in screen, is dropped rather
    than followed: this value ends up in a redirect, so anything but an in-app path is an
    open redirect. `isSafeNextPath` is the same check the SSO handoff uses.

    The fragment goes first. `to.fullPath` carries the hash, and the hash is where the SSO
    handoff puts an access token — so keeping it here would take a credential the browser
    holds privately and write it into a query string, where it reaches the server on every
    request and rides the Referer header out to every asset. Cut, not rejected: the route
    itself is still worth returning to, and the browser re-applies its own hash anyway. */
export function signInPath(intended: string): string {
  const route = stripFragment(intended);
  if (!isSafeNextPath(route) || route === "/" || route.startsWith("/login")) return "/login";
  return `/login?next=${encodeURIComponent(route)}`;
}

export default defineNuxtRouteMiddleware((to) => {
  // Tokens live in localStorage, so deciding on the server would bounce the user
  // to /login before the client has had a chance to hydrate its session.
  if (import.meta.server) return;
  const auth = useAuth();
  // State is empty on a hard refresh, so read the persisted tokens before deciding.
  auth.hydrate();
  if (auth.isAuthenticated.value) return;
  if (to.path === "/login") return;
  return navigateTo(signInPath(to.fullPath));
});
