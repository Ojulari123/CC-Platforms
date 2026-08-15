<script lang="ts">
import type { MemberResponse } from "~/types/api";

/** null means the caller is not a member and the API will not list it, which is a
    different thing from an empty department and is rendered as such. */
export interface Roster {
  total: number;
  members: MemberResponse[];
}
</script>

<script setup lang="ts">
import { ref } from "vue";
import Avatar from "@crescent/ui/components/Avatar.vue";
import Icon from "@crescent/ui/components/Icon.vue";
import { FOCUS } from "@crescent/ui/utils/ui";
import { fullName } from "~/utils/format";
import type { DepartmentResponse } from "~/types/api";

/* The structure rail, on both /departments and /departments/:id. It stays a rail of
   links rather than local state, because a department already has a deep-linkable URL
   and people send those to each other. */
const props = withDefaults(
  defineProps<{
    departments: DepartmentResponse[];
    rosters: Record<number, Roster | null>;
    selectedId?: number | null;
  }>(),
  { selectedId: null },
);

const expanded = ref<number[]>(props.selectedId === null ? [] : [props.selectedId]);

function toggle(id: number) {
  expanded.value = expanded.value.includes(id)
    ? expanded.value.filter((x) => x !== id)
    : [...expanded.value, id];
}

function headName(dept: DepartmentResponse): string | null {
  if (dept.head_user_id === null) return null;
  if (dept.head_name) return dept.head_name;
  const member = props.rosters[dept.id]?.members.find((m) => m.user_id === dept.head_user_id);
  // Never a fabricated name: an id that will not resolve says so.
  return member ? fullName(member.first_name, member.last_name, member.email) : `user_id ${dept.head_user_id} · unresolved`;
}
</script>

<template>
  <ul class="space-y-2">
    <li
      v-for="dept in departments"
      :key="dept.id"
      :class="[
        'overflow-hidden rounded-md ring-1 ring-inset transition-colors',
        dept.id === selectedId ? 'bg-surface-active ring-line' : 'bg-surface/40 ring-line-subtle hover:ring-line',
      ]"
    >
      <div class="flex items-start gap-2 px-3 py-2.5">
        <button
          type="button"
          :aria-expanded="expanded.includes(dept.id)"
          :aria-label="`${expanded.includes(dept.id) ? 'Collapse' : 'Expand'} ${dept.name}`"
          :class="[FOCUS, 'mt-0.5 shrink-0 rounded p-0.5 text-ink-faint transition-colors hover:text-ink']"
          @click="toggle(dept.id)"
        >
          <Icon name="chevron" :class="['h-3.5 w-3.5 transition-transform', expanded.includes(dept.id) && 'rotate-90']" />
        </button>
        <NuxtLink
          :to="`/departments/${dept.id}`"
          :aria-current="dept.id === selectedId ? 'page' : undefined"
          :class="[FOCUS, 'min-w-0 flex-1 rounded text-left']"
        >
          <span class="flex flex-wrap items-baseline gap-x-2">
            <span class="text-[13px] font-medium text-ink">{{ dept.name }}</span>
            <span class="mono text-[11px] text-ink-muted">dept_id {{ dept.id }} · {{ dept.slug }}</span>
          </span>
          <span class="mono mt-0.5 block text-[11px] text-ink-muted">
            <template v-if="rosters[dept.id]">
              {{ rosters[dept.id]!.total }} {{ rosters[dept.id]!.total === 1 ? "member" : "members" }}
            </template>
            <template v-else>roster not visible to you</template>
          </span>
        </NuxtLink>
      </div>

      <div v-if="expanded.includes(dept.id)" class="xfade border-t border-line-subtle px-3 py-2.5">
        <div v-if="headName(dept)" class="flex items-center gap-2.5">
          <Avatar :name="headName(dept) ?? ''" size="sm" />
          <div class="min-w-0">
            <p class="truncate text-[12px] text-ink">{{ headName(dept) }}</p>
            <p class="mono text-[11px] text-ink-muted">head · user_id {{ dept.head_user_id }}</p>
          </div>
        </div>
        <p v-else class="flex items-start gap-2 text-[12px] leading-relaxed text-warn">
          <span class="mt-0.5 shrink-0"><Icon name="alert" class="h-3.5 w-3.5" /></span>
          <span>
            No head.
            <span class="text-ink-muted">
              <span class="mono text-[11px]">head_user_id</span> is null, and the department works anyway —
              the field names a person, it does not grant anything.
            </span>
          </span>
        </p>

        <div v-if="rosters[dept.id] && rosters[dept.id]!.members.length" class="mt-3 flex items-center gap-2">
          <div class="flex">
            <span v-for="(m, i) in rosters[dept.id]!.members.slice(0, 6)" :key="m.user_id" :class="i === 0 ? '' : '-ml-1.5'">
              <Avatar :name="fullName(m.first_name, m.last_name, m.email)" size="sm" />
            </span>
          </div>
          <span v-if="rosters[dept.id]!.total > 6" class="mono text-[11px] text-ink-muted">
            +{{ rosters[dept.id]!.total - 6 }}
          </span>
        </div>
        <p v-else-if="rosters[dept.id]" class="mt-3 text-[12.5px] leading-relaxed text-ink-muted">
          Nobody has been placed here yet.
        </p>
      </div>
    </li>
  </ul>
</template>
