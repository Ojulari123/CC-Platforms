import { useQuery } from "@tanstack/vue-query";

/* The key id printed on the auth screens. It is read from what identity actually
   publishes rather than written into the copy: a hard-coded kid stops being true the
   first time the key rotates, and this line exists to be checkable.

   No rotation history is shown — JWKS publishes the keys that verify today and nothing
   about when they were minted, so a "rotated 12 days ago" line would be invented. */
interface Jwk {
  kid?: string;
  alg?: string;
}

export function useSigningKey() {
  const identityUrl = useRuntimeConfig().public.identityUrl;

  const { data } = useQuery({
    queryKey: ["jwks"],
    queryFn: () => $fetch<{ keys: Jwk[] }>(`${identityUrl}/.well-known/jwks.json`),
    staleTime: 5 * 60_000,
    retry: false,
  });

  // Rendered nowhere if identity is unreachable: an unknown key id is better left unsaid.
  const label = computed(() => {
    const key = data.value?.keys?.[0];
    if (!key?.kid) return null;
    return `signing key ${key.kid.slice(0, 8)} · ${key.alg ?? "RS256"}`;
  });

  return { label };
}
