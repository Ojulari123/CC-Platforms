export function useApi() {
  return useApiClient(useRuntimeConfig().public.pulseUrl);
}

export function useIdentityApi() {
  return useApiClient(useRuntimeConfig().public.identityUrl);
}
