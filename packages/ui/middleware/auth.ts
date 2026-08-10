export default defineNuxtRouteMiddleware((to) => {
  // Tokens live in localStorage, so deciding on the server would bounce the user
  // to /login before the client has had a chance to hydrate its session.
  if (import.meta.server) return;
  const auth = useAuth();
  // State is empty on a hard refresh, so read the persisted tokens before deciding.
  auth.hydrate();
  if (!auth.isAuthenticated.value && to.path !== "/login") {
    return navigateTo("/login");
  }
});
