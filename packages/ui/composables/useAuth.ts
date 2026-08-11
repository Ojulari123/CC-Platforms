import type { SignupPayload, TokenPair, UserResponse, UserMeResponse } from "../types/api";

export function useAuth() {
  const config = useRuntimeConfig();
  const identityUrl = config.public.identityUrl;
  const storage = useTokenStorage();

  const accessToken = useState<string | null>("auth.access", () => null);
  const refreshToken = useState<string | null>("auth.refresh", () => null);
  const user = useState<UserResponse | UserMeResponse | null>("auth.user", () => null);

  function hydrate() {
    if (!import.meta.client) return;
    const stored = storage.read();
    accessToken.value = stored.accessToken;
    refreshToken.value = stored.refreshToken;
  }

  function persist(pair: TokenPair) {
    accessToken.value = pair.access_token;
    refreshToken.value = pair.refresh_token;
    user.value = pair.user;
    storage.write({
      accessToken: pair.access_token,
      refreshToken: pair.refresh_token,
    });
  }

  function clear() {
    accessToken.value = null;
    refreshToken.value = null;
    user.value = null;
    storage.clear();
  }

  async function login(email: string, password: string): Promise<void> {
    const pair = await $fetch<TokenPair>(`${identityUrl}/auth/login`, {
      method: "POST",
      body: { email, password },
    });
    persist(pair);
    // Best-effort: /me adds memberships and the platform-admin flag. Login already
    // returned the basics, so a failure here shouldn't block the session.
    try {
      await fetchMe();
    } catch {
      // keep the UserResponse from the token pair
    }
  }

  // Identity's /auth/signup returns the same token pair as /auth/login, so a new
  // account is signed in immediately. It has no department until an admin places them.
  async function signup(payload: SignupPayload): Promise<void> {
    const pair = await $fetch<TokenPair>(`${identityUrl}/auth/signup`, {
      method: "POST",
      body: payload,
    });
    persist(pair);
    try {
      await fetchMe();
    } catch {
      // keep the UserResponse from the token pair
    }
  }

  // For flows that get a token pair from somewhere other than login/signup:
  // invite acceptance returns one, so the invitee lands already signed in.
  async function adoptSession(pair: TokenPair): Promise<void> {
    persist(pair);
    try {
      await fetchMe();
    } catch {
      // keep the UserResponse from the token pair
    }
  }

  async function refresh(): Promise<boolean> {
    if (!refreshToken.value) return false;
    try {
      const pair = await $fetch<TokenPair>(`${identityUrl}/auth/refresh`, {
        method: "POST",
        // Body field name matches identity RefreshRequest.refresh_token.
        body: { refresh_token: refreshToken.value },
      });
      persist(pair);
      return true;
    } catch {
      clear();
      return false;
    }
  }

  async function fetchMe(): Promise<void> {
    if (!accessToken.value) return;
    const me = await $fetch<UserMeResponse>(`${identityUrl}/me`, {
      headers: { Authorization: `Bearer ${accessToken.value}` },
    });
    user.value = me;
  }

  function logout(): void {
    clear();
  }

  const isAuthenticated = computed(() => !!accessToken.value);

  return {
    accessToken,
    refreshToken,
    user,
    isAuthenticated,
    hydrate,
    login,
    signup,
    adoptSession,
    refresh,
    fetchMe,
    logout,
  };
}
