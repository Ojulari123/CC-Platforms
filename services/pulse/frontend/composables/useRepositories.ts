import { useQuery } from "@tanstack/vue-query";
import type { Page, RepositoryResponse } from "~/types/api";

export function useRepositories() {
  const api = useApi();

  const query = useQuery({
    queryKey: ["repositories"],
    queryFn: () =>
      api.request<Page<RepositoryResponse>>("/github/repositories", {
        query: { limit: 200 },
      }),
  });

  const repositories = computed(() => query.data.value?.items ?? []);

  const nameById = computed(() => {
    const map = new Map<number, string>();
    for (const repo of repositories.value) map.set(repo.id, repo.full_name);
    return map;
  });

  // An id Pulse cannot resolve renders as an id. Never a fabricated name, and never a
  // bare number dressed up as one.
  function repoName(repoId: number): string {
    return nameById.value.get(repoId) ?? `repo_id ${repoId} · unresolved`;
  }

  return { ...query, repositories, repoName };
}
