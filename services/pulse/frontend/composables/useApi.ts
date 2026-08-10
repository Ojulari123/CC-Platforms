export function useApi() {
  return useApiClient(useRuntimeConfig().public.pulseUrl);
}

// Pulse reads a couple of things straight from identity that it isn't allowed to
// hold itself — the department list and its members, for the "whose activity?" picker.
export function useIdentityApi() {
  return useApiClient(useRuntimeConfig().public.identityUrl);
}
