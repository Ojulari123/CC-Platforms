// Wrap this once per backend a product talks to. On a 401 it refreshes exactly once
// and retries, so a product never writes its own token-refresh handling.

export interface ApiOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  query?: Record<string, unknown>;
}

export function useApiClient(baseUrl: string) {
  const auth = useAuth();

  async function raw<T>(path: string, opts: ApiOptions): Promise<T> {
    return await $fetch<T>(`${baseUrl}${path}`, {
      method: opts.method ?? "GET",
      body: opts.body as never,
      query: opts.query,
      headers: auth.accessToken.value
        ? { Authorization: `Bearer ${auth.accessToken.value}` }
        : {},
    });
  }

  async function request<T>(path: string, opts: ApiOptions = {}): Promise<T> {
    try {
      return await raw<T>(path, opts);
    } catch (err: unknown) {
      const status = (err as { statusCode?: number; status?: number })?.statusCode
        ?? (err as { status?: number })?.status;
      if (status === 401) {
        const refreshed = await auth.refresh();
        if (refreshed) {
          return await raw<T>(path, opts);
        }
        auth.logout();
        if (import.meta.client) {
          await navigateTo("/login");
        }
      }
      throw err;
    }
  }

  return { request };
}
