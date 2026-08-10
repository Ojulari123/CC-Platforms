export default defineNuxtRouteMiddleware((to) => {
  // Tokens live in localStorage (client-only), so the auth decision can only be made in the browser
  // Skip on the server to avoid a redirect before the client has hydrated its session
  if (import.meta.server) return;
  const auth = useAuth();
  // Read persisted tokens on the client before deciding (state may be empty on a fresh page load / hard refresh)
  auth.hydrate();
  if (!auth.isAuthenticated.value && to.path !== "/login") {
    return navigateTo("/login");
  }
});
