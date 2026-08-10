import { useQuery } from "@tanstack/vue-query";
import type { MemberListResponse, MemberResponse, UserMeResponse } from "~/types/api";

// People the caller could plausibly look at. Pulse holds no user directory of its
// own, so this comes from identity: the members of every department the caller
// belongs to. Someone with no department gets an empty list, which is why the
// picker says so instead of showing an empty dropdown.
export function useTeammates() {
  const auth = useAuth();
  const identity = useIdentityApi();

  const deptIds = computed(() => {
    const me = auth.user.value as UserMeResponse | null;
    return (me?.memberships ?? []).map((m) => m.dept_id);
  });

  const query = useQuery({
    queryKey: computed(() => ["teammates", deptIds.value.join(",")]),
    enabled: computed(() => deptIds.value.length > 0),
    queryFn: async () => {
      const byId = new Map<number, MemberResponse>();
      for (const deptId of deptIds.value) {
        try {
          const page = await identity.request<MemberListResponse>(
            `/departments/${deptId}/members`,
            { query: { limit: 200 } },
          );
          for (const member of page.items) byId.set(member.user_id, member);
        } catch {
          // One department being unreadable shouldn't blank the whole picker.
        }
      }
      return [...byId.values()].sort((a, b) =>
        `${a.first_name} ${a.last_name}`.localeCompare(`${b.first_name} ${b.last_name}`),
      );
    },
  });

  const selfId = computed(() => auth.user.value?.id ?? null);
  const others = computed(() =>
    (query.data.value ?? []).filter((m) => m.user_id !== selfId.value),
  );

  const hasDepartment = computed(() => deptIds.value.length > 0);

  return { ...query, others, hasDepartment };
}
