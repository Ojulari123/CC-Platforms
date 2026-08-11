// The only place tokens are read or written, for every product on this layer. Moving
// them (httpOnly cookies, sessionStorage, memory) should touch this file and nothing else.

export interface StoredTokens {
  accessToken: string | null;
  refreshToken: string | null;
}

export function useTokenStorage() {
  const prefix = useRuntimeConfig().public.authStoragePrefix;
  // The build-time check in the layer's nuxt.config can't see a runtime env override
  // (NUXT_PUBLIC_AUTH_STORAGE_PREFIX=""), so refuse to touch unprefixed keys here too.
  if (!prefix) {
    throw new Error(
      "[@crescent/ui] runtimeConfig.public.authStoragePrefix is empty, so reading or writing unprefixed token keys is refused.",
    );
  }
  const accessKey = `${prefix}.access_token`;
  const refreshKey = `${prefix}.refresh_token`;

  function read(): StoredTokens {
    if (!import.meta.client) return { accessToken: null, refreshToken: null };
    return {
      accessToken: localStorage.getItem(accessKey),
      refreshToken: localStorage.getItem(refreshKey),
    };
  }

  function write(tokens: { accessToken: string; refreshToken: string }): void {
    if (!import.meta.client) return;
    localStorage.setItem(accessKey, tokens.accessToken);
    localStorage.setItem(refreshKey, tokens.refreshToken);
  }

  function clear(): void {
    if (!import.meta.client) return;
    localStorage.removeItem(accessKey);
    localStorage.removeItem(refreshKey);
  }

  return { read, write, clear };
}
