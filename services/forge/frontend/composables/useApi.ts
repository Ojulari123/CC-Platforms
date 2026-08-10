export function useApi() {
  return useApiClient(useRuntimeConfig().public.forgeUrl);
}
