/* The layer's `auth` middleware bounces to /login and forgets what you asked for. This one
   carries the intent, so signing in lands you where you were going rather than at a home
   page you did not choose. Named differently so the shared one is left alone. */
export default defineNuxtRouteMiddleware((to) => {
  // Tokens live in localStorage, so deciding on the server would bounce the visitor
  // before the client has had a chance to hydrate its session.
  if (import.meta.server) return;
  const auth = useAuth();
  // State is empty on a hard refresh, so read the persisted tokens before deciding.
  auth.hydrate();
  if (auth.isAuthenticated.value) return;
  return navigateTo(signInPath(to.fullPath));
});
