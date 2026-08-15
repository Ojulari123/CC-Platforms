import type { UserMeResponse } from "~/types/api";

// Pulse holds no user record of its own, so who you are comes from identity's /me. Every
// list scoped to "yours" needs the id from it, which means identity being unreachable is
// a state screens have to render rather than sit in a spinner over.
export function useMe() {
  const auth = useAuth();
  const settled = useState("pulse.me-settled", () => false);

  const me = computed(() => auth.user.value as UserMeResponse | null);
  const unavailable = computed(() => settled.value && me.value === null);

  async function load() {
    if (!auth.isAuthenticated.value) return;
    try {
      await auth.fetchMe();
    } catch {
      // Rendered by the screens, not swallowed.
    } finally {
      settled.value = true;
    }
  }

  async function retry() {
    settled.value = false;
    await load();
  }

  return { me, unavailable, settled, load, retry };
}
