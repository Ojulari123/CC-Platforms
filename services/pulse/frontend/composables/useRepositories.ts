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

  function repoName(repoId: number): string {
    return nameById.value.get(repoId) ?? `Repository #${repoId}`;
  }

  return { ...query, repositories, repoName };
}
