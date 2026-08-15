<script lang="ts">
/* Identity — Access.

   A permission screen is usually a grid of ticks nobody can read a sentence out of. This
   one starts from the question people actually ask — can this person do this thing — and
   answers it with the reason and the guard in the API that enforces it.

   Both views are computed by verdict(). There is no second table of answers that could
   drift away from the first: if the person view says no, the capability view says no,
   because it is the same call. That is what the tests check. */

export type CapId =
  | "report_own"
  | "report_decide"
  | "repo_file"
  | "report_read"
  | "invite"
  | "place"
  | "role"
  | "dept_rename"
  | "dept_create"
  | "dept_head"
  | "directory"
  | "deactivate";

/** 0 their own work · 1 repos they lead · 2 their department · 3 the whole workspace. */
export type Scope = 0 | 1 | 2 | 3;

/** 1 routine · 2 changes access · 3 irreversible. */
export type Weight = 1 | 2 | 3;

export interface Cap {
  id: CapId;
  label: string;
  scope: Scope;
  weight: Weight;
  /** The dependency in the API that actually refuses the request. */
  guard: string;
  note?: string;
}

export interface AccessPerson {
  id: number;
  name: string;
  firstName: string;
  active: boolean;
  platformAdmin: boolean;
  /** Strongest role they hold, and where. Null when they are in no department. */
  role: string | null;
  deptName: string | null;
  /** More than one membership, which the sentences below have to admit to. */
  deptCount: number;
}

export interface Verdict {
  allowed: boolean;
  reason: string;
  guard: string;
  /** Something identity cannot see from here. Rendered, never silently dropped. */
  caveat?: string;
}

export const CAPS: Cap[] = [
  { id: "report_own", label: "Write their own weekly report", scope: 0, weight: 1, guard: "_may_report_on" },
  {
    id: "report_decide",
    label: "Approve or reject a report",
    scope: 1,
    weight: 2,
    guard: "_can_approve",
    note: "Never their own. Authorship is checked before any admin power, so a platform admin is refused on their own report like anyone else.",
  },
  { id: "repo_file", label: "File a repo and name its lead", scope: 2, weight: 2, guard: "_require_can_admin_repo" },
  { id: "report_read", label: "Read every report in their department", scope: 2, weight: 1, guard: "role == manager" },
  { id: "invite", label: "Invite someone into their department", scope: 2, weight: 2, guard: "dept_admin" },
  { id: "place", label: "Place or remove a member", scope: 2, weight: 2, guard: "dept_admin" },
  { id: "role", label: "Change someone's role", scope: 2, weight: 2, guard: "dept_admin" },
  { id: "dept_rename", label: "Rename their department", scope: 2, weight: 1, guard: "dept_admin" },
  { id: "dept_create", label: "Create or delete a department", scope: 3, weight: 3, guard: "require_platform_admin" },
  {
    id: "dept_head",
    label: "Name a department head",
    scope: 3,
    weight: 2,
    guard: "require_platform_admin",
    note: "The person named has to already hold admin in that department.",
  },
  { id: "directory", label: "See every account in the workspace", scope: 3, weight: 1, guard: "require_platform_admin" },
  { id: "deactivate", label: "Deactivate or delete an account", scope: 3, weight: 3, guard: "require_platform_admin" },
];

export const SCOPE_LABEL: Record<Scope, string> = {
  0: "their own work",
  1: "repos they lead",
  2: "their department",
  3: "the whole workspace",
};

export const RUNGS: { scope: Scope; label: string; extent: number }[] = [
  { scope: 0, label: "Their own work", extent: 46 },
  { scope: 1, label: "Repos they lead", extent: 64 },
  { scope: 2, label: "Their department", extent: 82 },
  { scope: 3, label: "The whole workspace", extent: 100 },
];

// Repository leadership lives in Pulse and identity cannot read it, so the one answer
// that would need it says so instead of being invented.
const LEAD_CAVEAT =
  "Identity cannot see which repositories they lead — that record lives in Pulse — so this answer covers only the department route. Pulse's own check may still say yes.";

function isDeptAdmin(person: AccessPerson): boolean {
  return person.role === "admin" && person.deptName !== null;
}

/** The single source of truth for both views. */
export function verdict(person: AccessPerson, cap: Cap): Verdict {
  const guard = cap.guard;
  const here = person.deptName ?? "no department";

  if (!person.active) {
    return {
      allowed: false,
      reason: `The account is deactivated, so the request is refused before any permission is read. ${person.firstName}'s role is never consulted.`,
      guard,
    };
  }

  const deptAdmin = isDeptAdmin(person);

  switch (cap.id) {
    case "report_own":
      return {
        allowed: true,
        reason:
          "Everybody writes their own. Nothing is granted for this — the week is assembled from the activity Pulse already synced, so no role is looked at.",
        guard,
      };

    case "report_decide":
      if (deptAdmin) {
        return {
          allowed: true,
          reason: `They administer ${here}, which covers reports filed in it. Their own is still refused: authorship is checked first.`,
          guard,
          caveat: LEAD_CAVEAT,
        };
      }
      return {
        allowed: false,
        reason: `They administer no department, so there is no report that is theirs to decide on identity's side. ${person.role === "manager" ? "Manager reads the department; it does not approve." : "Writing reports and deciding them are separate."}`,
        guard,
        caveat: LEAD_CAVEAT,
      };

    case "repo_file":
      if (person.platformAdmin) {
        return {
          allowed: true,
          reason: "Platform admin reaches into every department, so filing a repository anywhere is allowed.",
          guard,
        };
      }
      if (deptAdmin) {
        return {
          allowed: true,
          reason: `Filing a repository puts it under a department and names who decides its reports, so it takes admin in ${here} — which they hold.`,
          guard,
        };
      }
      return {
        allowed: false,
        reason: `Filing a repository decides which department its work counts towards and who approves it. That needs admin in the department; ${person.firstName} is ${person.role ?? "in no department"}${person.deptName ? ` in ${here}` : ""}.`,
        guard,
      };

    case "report_read":
      if (person.role === "manager") {
        return {
          allowed: true,
          reason: `Manager is the reading role: every report filed in ${here}, whether or not they lead the repository it came from.`,
          guard,
        };
      }
      return {
        allowed: false,
        reason: deptAdmin
          ? `The guard names the role exactly. An admin sees the reports they are asked to decide — the department-wide read belongs to manager, and administering ${here} does not include it.`
          : `The department-wide read is the manager's. ${person.firstName} sees their own work, and any report they were asked to decide.`,
        guard,
      };

    case "invite":
      return deptAdmin
        ? {
            allowed: true,
            reason: `Admin in ${here}, so they can bring someone into ${here} — and nowhere else. The invite carries the department with it.`,
            guard,
          }
        : {
            allowed: false,
            reason: `Inviting places an account somewhere, which is why it takes admin in that department. ${person.firstName} is ${person.role ?? "unplaced"}${person.deptName ? ` in ${here}` : " and belongs to no department"}.`,
            guard,
          };

    case "place":
      return deptAdmin
        ? {
            allowed: true,
            reason: `Membership in ${here} is theirs to change. Nothing in another department is.`,
            guard,
          }
        : {
            allowed: false,
            reason: "Placing or removing a member changes what somebody else can see, so it sits with the department's admin.",
            guard,
          };

    case "role":
      return deptAdmin
        ? {
            allowed: true,
            reason: `They set roles inside ${here}, including making another admin. They cannot grant platform admin — that is a different guard entirely.`,
            guard,
          }
        : {
            allowed: false,
            reason: "A role is what the rest of this page is computed from, so changing one takes admin in the department it applies to.",
            guard,
          };

    case "dept_rename":
      return deptAdmin
        ? {
            allowed: true,
            reason: `Cosmetic, and still department-scoped: the id does not change, so nothing filed against ${here} moves.`,
            guard,
          }
        : {
            allowed: false,
            reason: "Renaming is harmless but still belongs to whoever administers the department.",
            guard,
          };

    case "dept_create":
      return person.platformAdmin
        ? {
            allowed: true,
            reason:
              "Platform admin. Deleting one is the irreversible half — the API refuses while anybody is still a member, so the roster has to be emptied first.",
            guard,
          }
        : {
            allowed: false,
            reason: `Departments are the top-level grouping, so only a platform admin makes or unmakes one. Admin in ${here} stops at its edge.`,
            guard,
          };

    case "dept_head":
      return person.platformAdmin
        ? {
            allowed: true,
            reason:
              "Platform admin names heads. The person named must already hold admin there — naming somebody head does not give them anything.",
            guard,
          }
        : {
            allowed: false,
            reason: `Naming a head is a workspace-level act, even when the department is their own. ${person.firstName} cannot name one for ${here}.`,
            guard,
          };

    case "directory":
      return person.platformAdmin
        ? {
            allowed: true,
            reason: "Platform admin sees every account, including the ones placed in no department at all.",
            guard,
          }
        : {
            allowed: false,
            reason: `They see the people in ${here}. Accounts outside it — including the unplaced ones — are not theirs to list.`,
            guard,
          };

    case "deactivate":
      return person.platformAdmin
        ? {
            allowed: true,
            reason:
              "Platform admin. Deactivating cuts every session within about a minute; deleting cannot be undone, and is refused while the person still belongs to a department.",
            guard,
          }
        : {
            allowed: false,
            reason: "An account belongs to the workspace, not to a department, so removing one is never a department-level act.",
            guard,
          };
  }
}

/** Furthest scope this person reaches at all, or -1 if they reach nothing. */
export function maxScope(person: AccessPerson): number {
  let out = -1;
  for (const cap of CAPS) if (verdict(person, cap).allowed && cap.scope > out) out = cap.scope;
  return out;
}

export function capsAllowed(person: AccessPerson): Cap[] {
  return CAPS.filter((c) => verdict(person, c).allowed);
}

export function capsRefused(person: AccessPerson): Cap[] {
  return CAPS.filter((c) => !verdict(person, c).allowed);
}

export function peopleAllowed(people: AccessPerson[], cap: Cap): AccessPerson[] {
  return people.filter((p) => verdict(p, cap).allowed);
}

/** admin beats manager beats engineer: the strongest membership is the one the sentences
    on this screen are written about. */
export const ROLE_RANK: Record<string, number> = { admin: 3, manager: 2, engineer: 1 };

export function names(list: AccessPerson[], cap = 3): string {
  const shown = list.slice(0, cap).map((p) => p.name);
  const rest = list.length - shown.length;
  return rest > 0 ? `${shown.join(", ")} +${rest}` : shown.join(", ");
}
</script>

<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import type {
  DepartmentResponse,
  MemberListResponse,
  PlatformAdminResponse,
  PlatformUserListResponse,
  UserMeResponse,
} from "~/types/api";

definePageMeta({ middleware: "auth", layout: false });

const route = useRoute();
const router = useRouter();
const api = useApi();
const auth = useAuth();

const me = computed(() => auth.user.value as UserMeResponse | null);
const isPlatformAdmin = computed(() => me.value?.is_platform_admin === true);

const departments = useQuery({
  queryKey: ["departments"],
  queryFn: () => api.request<DepartmentResponse[]>("/departments"),
});

const readable = computed(() => {
  const all = departments.data.value ?? [];
  if (isPlatformAdmin.value) return all;
  const mine = new Set((me.value?.memberships ?? []).map((m) => m.dept_id));
  return all.filter((d) => mine.has(d.id));
});

const rosters = useQuery({
  queryKey: computed(() => ["dept-rosters", readable.value.map((d) => d.id).join(",")]),
  enabled: computed(() => readable.value.length > 0),
  queryFn: async () => {
    const map: Record<number, { total: number; members: MemberListResponse["items"] }> = {};
    for (const dept of readable.value) {
      const page = await api.request<MemberListResponse>(`/departments/${dept.id}/members`, {
        query: { limit: 200 },
      });
      map[dept.id] = { total: page.total, members: page.items };
    }
    return map;
  },
});

// Only a platform admin can read either of these, so for anybody else the list is their
// own departments and nothing is guessed about the rest of the workspace.
const platformAdmins = useQuery({
  queryKey: ["platform-admins"],
  enabled: isPlatformAdmin,
  queryFn: () => api.request<PlatformAdminResponse[]>("/platform/admins"),
});

const accounts = useQuery({
  queryKey: ["platform-users", "", 0],
  enabled: isPlatformAdmin,
  queryFn: () => api.request<PlatformUserListResponse>("/platform/users", { query: { limit: 200, offset: 0 } }),
});

const adminIds = computed(() => new Set((platformAdmins.data.value ?? []).map((a) => a.id)));

const people = computed<AccessPerson[]>(() => {
  const byId = new Map<number, AccessPerson>();
  const deptName = new Map<number, string>((departments.data.value ?? []).map((d) => [d.id, d.name]));

  for (const [id, roster] of Object.entries(rosters.data.value ?? {})) {
    const dept = deptName.get(Number(id)) ?? `dept_id ${id} · unresolved`;
    for (const m of roster?.members ?? []) {
      const existing = byId.get(m.user_id);
      const stronger = !existing || (ROLE_RANK[m.role] ?? 0) > (ROLE_RANK[existing.role ?? ""] ?? 0);
      byId.set(m.user_id, {
        id: m.user_id,
        name: fullName(m.first_name, m.last_name, m.email),
        firstName: m.first_name || m.email,
        active: m.is_active,
        platformAdmin: adminIds.value.has(m.user_id) || (m.user_id === me.value?.id && isPlatformAdmin.value),
        role: stronger ? m.role : (existing?.role ?? m.role),
        deptName: stronger ? dept : (existing?.deptName ?? dept),
        deptCount: (existing?.deptCount ?? 0) + 1,
      });
    }
  }

  // A platform admin also sees the accounts in no department — the ladder is about where
  // a person's reach runs out, and "nowhere" is one of the answers.
  for (const u of accounts.data.value?.items ?? []) {
    if (byId.has(u.id)) continue;
    byId.set(u.id, {
      id: u.id,
      name: fullName(u.first_name, u.last_name, u.email),
      firstName: u.first_name || u.email,
      active: u.is_active,
      platformAdmin: u.is_platform_admin,
      role: null,
      deptName: null,
      deptCount: 0,
    });
  }

  return [...byId.values()].sort((a, b) => a.name.localeCompare(b.name));
});

const loading = computed(
  () => departments.isPending.value || rosters.isFetching.value || (isPlatformAdmin.value && accounts.isPending.value),
);
const failed = computed(() => departments.isError.value || rosters.isError.value || accounts.isError.value);
const failure = computed(() =>
  apiMessage(
    departments.error.value ?? rosters.error.value ?? accounts.error.value,
    "Identity did not answer, so nothing on this page can be computed.",
  ),
);

// ── the question ───────────────────────────────────────────────────────────
// In the query string, so "look at what Femi can do" is a link somebody can send.
const personId = computed({
  get: () => Number(route.query.person ?? me.value?.id ?? 0),
  set: (value: number) => router.replace({ query: { ...route.query, person: String(value) } }),
});

const capId = computed({
  get: () => (CAPS.some((c) => c.id === route.query.cap) ? (route.query.cap as CapId) : "report_decide"),
  set: (value: CapId) => router.replace({ query: { ...route.query, cap: value } }),
});

const mode = ref<"person" | "capability">("person");

const person = computed<AccessPerson | null>(
  () => people.value.find((p) => p.id === personId.value) ?? people.value[0] ?? null,
);
const cap = computed(() => CAPS.find((c) => c.id === capId.value) ?? CAPS[1]!);
const answer = computed(() => (person.value ? verdict(person.value, cap.value) : null));

const can = computed(() => (person.value ? capsAllowed(person.value) : []));
const cannot = computed(() => (person.value ? capsRefused(person.value) : []));

const stopsAt = computed(() => {
  const out: Record<number, AccessPerson[]> = { [-1]: [], 0: [], 1: [], 2: [], 3: [] };
  for (const p of people.value) out[maxScope(p)]!.push(p);
  return out;
});

const ranked = [...CAPS].sort((a, b) => b.weight - a.weight || b.scope - a.scope);

const personOptions = computed(() =>
  people.value.map((p) => ({ value: String(p.id), label: `${p.name}${p.id === me.value?.id ? " (you)" : ""}` })),
);
const capOptions = CAPS.map((c) => ({ value: c.id, label: c.label.toLowerCase() }));

function rungHeld(scope: Scope) {
  const here = CAPS.filter((c) => c.scope === scope);
  const held = person.value ? here.filter((c) => verdict(person.value!, c).allowed) : [];
  return { held: held.length, of: here.length, frac: here.length === 0 ? 0 : held.length / here.length };
}

const RAMP = ["bg-line-subtle", "bg-line", "bg-line-strong", "bg-ink"];
</script>

<template>
  <IdentityShell :readout="`${CAPS.length} capabilities`">
    <header class="sec min-w-0">
      <Eyebrow>Identity · access</Eyebrow>
      <h1 class="mt-3 text-[clamp(1.5rem,2.2vw,1.9rem)] font-semibold leading-[1.05] tracking-[-0.035em]">
        Who can do what
      </h1>
      <p class="mt-1.5 max-w-[74ch] text-[12.5px] leading-relaxed text-ink-muted">
        Roles are carried in the access token, so each product decides on its own without asking identity. This
        page shows the same answer the products get, with the guard in the code that produces it.
      </p>
    </header>

    <div v-if="failed" role="alert" class="sec mt-6 rounded-md bg-bad-surface px-4 py-3.5">
      <p class="text-[13px] font-medium text-ink">Nothing can be answered right now.</p>
      <p class="mt-1 max-w-[60ch] text-[12.5px] leading-relaxed text-ink-muted">{{ failure }}</p>
      <div class="mt-3">
        <Btn size="sm" variant="secondary" @click="departments.refetch(); rosters.refetch()">Try again</Btn>
      </div>
    </div>

    <div v-else-if="loading" class="sec mt-6 space-y-2" role="status">
      <span class="sr-only">Reading roles</span>
      <span v-for="i in 4" :key="i" class="block h-14 rounded-md bg-surface/40 ring-1 ring-inset ring-line-subtle" aria-hidden="true" />
    </div>

    <div v-else-if="!person" class="sec mt-6 border-t border-line-subtle pt-5">
      <p class="text-[13.5px] font-medium text-ink">There is nobody to ask about yet.</p>
      <p class="mt-1.5 max-w-[60ch] text-[12.5px] leading-relaxed text-ink-muted">
        This page is computed from department memberships, and none are readable by you. A department admin
        sees their own roster; a platform admin sees every account.
      </p>
    </div>

    <template v-else>
      <!-- ── the question ── -->
      <section
        aria-label="Ask about one person and one capability"
        class="sec mt-6 rounded-md bg-surface/40 p-4 ring-1 ring-inset ring-line-subtle sm:p-5"
        style="animation-delay: 40ms"
      >
        <div class="flex flex-col gap-2 text-[15px] tracking-tight text-ink sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-2">
          <div class="flex items-center gap-2">
            Can
            <div class="min-w-0 flex-1 sm:w-[200px] sm:flex-none">
              <Select
                :model-value="String(personId)"
                label="Person"
                :options="personOptions"
                @update:model-value="personId = Number($event)"
              />
            </div>
          </div>
          <div class="flex min-w-0 items-center gap-2 sm:flex-1">
            <div class="min-w-0 flex-1">
              <Select
                :model-value="capId"
                label="Capability"
                :options="capOptions"
                @update:model-value="capId = $event as CapId"
              />
            </div>
            <span aria-hidden="true">?</span>
          </div>
        </div>

        <div
          :key="`${person.id}-${cap.id}`"
          class="xfade mt-4 flex flex-wrap items-start gap-4 border-t border-line-subtle pt-4"
        >
          <div class="flex shrink-0 items-center gap-2.5">
            <Avatar :name="person.name" />
            <span
              :class="[
                'text-[26px] font-semibold leading-none tracking-[-0.03em]',
                answer!.allowed ? 'text-ok' : 'text-bad',
              ]"
            >
              {{ answer!.allowed ? "Yes" : "No" }}
            </span>
          </div>
          <div class="min-w-0 flex-1">
            <p class="max-w-[80ch] text-[12.5px] leading-relaxed text-ink-muted">{{ answer!.reason }}</p>
            <div class="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
              <span class="mono text-[11px] uppercase tracking-[0.08em] text-ink-faint">enforced by</span>
              <GuardTag :name="answer!.guard" />
              <ScopeMark :scope="cap.scope" />
              <span class="mono text-[11px] text-ink-muted">{{ SCOPE_LABEL[cap.scope] }}</span>
              <WeightMark :weight="cap.weight" />
            </div>
            <p v-if="answer!.caveat" class="mt-2 max-w-[80ch] text-[12.5px] leading-relaxed text-ink-muted">
              {{ answer!.caveat }}
            </p>
            <p v-if="cap.note" class="mt-2 max-w-[80ch] text-[12.5px] leading-relaxed text-ink-muted">
              {{ cap.note }}
            </p>
          </div>
        </div>
      </section>

      <!-- ── mode ── -->
      <div class="sec mt-6" style="animation-delay: 40ms">
        <Tabs
          id="access"
          :model-value="mode"
          label="How to read this"
          has-panel
          :items="[
            { id: 'person', label: 'By person' },
            { id: 'capability', label: 'By capability' },
          ]"
          @update:model-value="mode = $event as 'person' | 'capability'"
        >
          <span class="mono hidden text-[11px] uppercase tracking-[0.08em] text-ink-faint sm:inline">
            one verdict() behind both
          </span>
        </Tabs>
        <p class="mono mt-2 text-[11px] uppercase tracking-[0.08em] text-ink-faint sm:hidden">
          one verdict() behind both
        </p>
      </div>

      <TabPanel v-if="mode === 'person'" id="access" tab="person" class="sec mt-5" style="animation-delay: 80ms">
        <section :aria-label="`How far ${person.name} reaches`">
          <div class="flex flex-wrap items-baseline justify-between gap-2">
            <h2 class="text-[14px] font-medium tracking-tight">How far {{ person.firstName }} reaches</h2>
            <p class="mono text-[11px] text-ink-muted">
              user_id {{ person.id }} · {{ person.role ?? "no role" }} · {{ person.deptName ?? "unplaced" }}
              <template v-if="person.deptCount > 1"> · +{{ person.deptCount - 1 }} more</template>
              <template v-if="person.platformAdmin"> · platform admin</template>
            </p>
          </div>
          <p class="mt-1.5 max-w-[80ch] text-[12px] leading-relaxed text-ink-muted">
            Each rung is wider than the last because it covers more of the workspace. The filled part is how much
            of that rung {{ person.firstName }} actually holds.
          </p>

          <ul class="mt-4 space-y-3">
            <li
              v-for="rung in RUNGS"
              :key="rung.scope"
              class="grid gap-1.5 sm:grid-cols-[minmax(0,1fr)_minmax(0,220px)] sm:items-center sm:gap-4"
            >
              <div class="min-w-0">
                <div class="flex items-baseline justify-between gap-3">
                  <span :class="['text-[12.5px]', rungHeld(rung.scope).frac > 0 ? 'text-ink' : 'text-ink-muted']">
                    {{ rung.label }}
                  </span>
                  <span class="mono shrink-0 text-[11px] text-ink-muted">
                    {{ rungHeld(rung.scope).held }}/{{ rungHeld(rung.scope).of }}
                  </span>
                </div>
                <div
                  class="mt-1.5 h-2 rounded-sm bg-app ring-1 ring-inset ring-line-subtle"
                  :style="{ width: `${rung.extent}%` }"
                >
                  <div
                    :class="['h-full rounded-sm transition-[width] duration-500 ease-out', RAMP[rung.scope]]"
                    :style="{ width: `${Math.round(rungHeld(rung.scope).frac * 100)}%` }"
                  />
                </div>
              </div>
              <p class="mono text-[11px] leading-relaxed text-ink-muted">
                {{ (stopsAt[rung.scope] ?? []).length === 0 ? "nobody stops here" : `stops here: ${names(stopsAt[rung.scope] ?? [])}` }}
              </p>
            </li>
          </ul>
        </section>

        <div class="mt-6 grid items-start gap-x-6 gap-y-5 lg:grid-cols-2">
          <section class="min-w-0 border-t border-line-strong pt-2.5" :aria-label="`Can: ${person.name}`">
            <header class="flex items-center gap-2.5 pb-1.5">
              <h3 class="mono text-[11px] uppercase tracking-[0.08em] text-ok">Can</h3>
              <span class="mono text-[11px] text-ink-muted">{{ can.length }} of {{ CAPS.length }}</span>
            </header>
            <p v-if="can.length === 0" class="py-3 text-[12px] text-ink-muted">
              Nothing at all — the account is deactivated.
            </p>
            <ul v-else class="divide-y divide-line-subtle">
              <li v-for="(c, i) in can" :key="c.id" class="sec py-2.5" :style="{ animationDelay: `${Math.min(i, 3) * 40}ms` }">
                <button type="button" :class="[FOCUS, 'w-full rounded text-left transition-opacity hover:opacity-80']" @click="capId = c.id">
                  <span class="block text-[12.5px] text-ink">{{ c.label }}</span>
                  <span class="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1">
                    <ScopeMark :scope="c.scope" />
                    <span class="mono text-[11px] text-ink-muted">{{ SCOPE_LABEL[c.scope] }}</span>
                    <WeightMark :weight="c.weight" />
                    <GuardTag :name="c.guard" />
                  </span>
                </button>
              </li>
            </ul>
          </section>

          <section class="min-w-0 border-t border-line-strong pt-2.5" :aria-label="`Cannot: ${person.name}`">
            <header class="flex items-center gap-2.5 pb-1.5">
              <h3 class="mono text-[11px] uppercase tracking-[0.08em] text-bad">Cannot</h3>
              <span class="mono text-[11px] text-ink-muted">{{ cannot.length }} of {{ CAPS.length }}</span>
            </header>
            <p v-if="cannot.length === 0" class="py-3 text-[12px] text-ink-muted">Nothing is out of reach.</p>
            <ul v-else class="divide-y divide-line-subtle">
              <li v-for="(c, i) in cannot" :key="c.id" class="sec py-2.5" :style="{ animationDelay: `${Math.min(i, 3) * 40}ms` }">
                <button type="button" :class="[FOCUS, 'w-full rounded text-left transition-opacity hover:opacity-80']" @click="capId = c.id">
                  <span class="block text-[12.5px] text-ink">{{ c.label }}</span>
                  <span class="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1">
                    <ScopeMark :scope="c.scope" />
                    <span class="mono text-[11px] text-ink-muted">{{ SCOPE_LABEL[c.scope] }}</span>
                    <WeightMark :weight="c.weight" />
                    <GuardTag :name="c.guard" />
                  </span>
                </button>
              </li>
            </ul>
          </section>
        </div>
      </TabPanel>

      <TabPanel v-else id="access" tab="capability" class="sec mt-5" style="animation-delay: 80ms">
        <div class="flex flex-wrap items-baseline justify-between gap-2">
          <h2 class="text-[14px] font-medium tracking-tight">Ranked by what it costs if it is wrong</h2>
          <p class="mono text-[11px] text-ink-muted">irreversible first</p>
        </div>
        <p class="mt-1.5 max-w-[80ch] text-[12px] leading-relaxed text-ink-muted">
          Not by how often it is used. The order asks a different question — if this were granted to the wrong
          person, how much of it could be taken back.
        </p>

        <ul class="mt-4 space-y-2.5">
          <li
            v-for="(c, i) in ranked"
            :key="c.id"
            class="sec rounded-md bg-surface/40 px-4 py-3.5 ring-1 ring-inset ring-line-subtle"
            :style="{ animationDelay: `${Math.min(i, 3) * 40}ms` }"
          >
            <div class="flex flex-wrap items-center gap-x-3 gap-y-1.5">
              <span :class="['h-4 w-1 shrink-0 rounded-sm', RAMP[c.weight]]" aria-hidden="true" />
              <h3 class="text-[13px] font-medium text-ink">{{ c.label }}</h3>
              <span class="ml-auto flex flex-wrap items-center gap-x-2.5 gap-y-1">
                <ScopeMark :scope="c.scope" />
                <span class="mono text-[11px] text-ink-muted">{{ SCOPE_LABEL[c.scope] }}</span>
                <WeightMark :weight="c.weight" />
                <GuardTag :name="c.guard" />
              </span>
            </div>

            <dl class="mt-2.5 grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
              <div class="flex gap-2">
                <dt class="mono w-[52px] shrink-0 text-[11px] uppercase tracking-[0.08em] text-ok">can</dt>
                <dd class="min-w-0 flex-1 text-[12px] leading-relaxed text-ink-muted">
                  {{ peopleAllowed(people, c).length === 0 ? "nobody" : names(peopleAllowed(people, c), 4) }}
                </dd>
              </div>
              <div class="flex gap-2">
                <dt class="mono w-[52px] shrink-0 text-[11px] uppercase tracking-[0.08em] text-ink-faint">cannot</dt>
                <dd class="min-w-0 flex-1 text-[12px] leading-relaxed text-ink-muted">
                  {{
                    people.length - peopleAllowed(people, c).length === 0
                      ? "nobody"
                      : names(people.filter((p) => !verdict(p, c).allowed), 4)
                  }}
                </dd>
              </div>
            </dl>

            <p v-if="c.note" class="mt-2 max-w-[84ch] text-[12.5px] leading-relaxed text-ink-muted">{{ c.note }}</p>

            <button
              type="button"
              :class="[FOCUS, 'mt-2.5 rounded text-[12.5px] text-ink-muted underline-offset-2 transition-colors hover:text-ink']"
              @click="capId = c.id; mode = 'person'"
            >
              Ask this about one person
            </button>
          </li>
        </ul>
      </TabPanel>

      <!-- ── the two rules worth stating outright ── -->
      <section aria-label="Rules" class="sec mt-8 grid gap-3 border-t border-line-subtle pt-5 sm:grid-cols-2" style="animation-delay: 120ms">
        <div class="flex gap-2.5">
          <Cross class="mt-1 shrink-0" />
          <p class="min-w-0 text-[12.5px] leading-relaxed text-ink-muted">
            <span class="font-medium text-ink">Being head of a department grants nothing on its own.</span>
            <span class="mono text-[12px]">head_user_id</span> names a person. Every check on this page reads the
            role in the membership row, never that field.
          </p>
        </div>
        <div class="flex gap-2.5">
          <Cross class="mt-1 shrink-0" />
          <p class="min-w-0 text-[12.5px] leading-relaxed text-ink-muted">
            <span class="font-medium text-ink">Nobody approves their own report.</span>
            Authorship is checked before any admin power, so a platform admin gets the same refusal on their own
            report as an engineer does.
          </p>
        </div>
      </section>

      <p class="mt-5 flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-line-subtle pt-3 text-[11px] text-ink-faint">
        <Icon name="shield" class="h-3.5 w-3.5 shrink-0" />
        Products verify the token with the published public key and read these claims locally. The signing key
        never leaves identity.
      </p>
    </template>
  </IdentityShell>
</template>
