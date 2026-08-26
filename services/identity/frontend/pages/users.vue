<script lang="ts">
import type { PlatformUserResponse } from "~/types/api";

/* The account directory.

   Exported rather than kept inside setup() because the filter, the sort and the delete
   guard are the behaviour of this screen, and they are tested directly. */

export interface Placement {
  deptId: number;
  deptName: string;
  role: string;
}

export interface DirectoryRow extends PlatformUserResponse {
  name: string;
  placements: Placement[];
}

export type PeopleFilter = "all" | "active" | "deactivated" | "unverified" | "admins";

export const PEOPLE_FILTERS: { id: PeopleFilter; label: string; match: (row: DirectoryRow) => boolean }[] = [
  { id: "all", label: "All", match: () => true },
  { id: "active", label: "Active", match: (r) => r.is_active },
  { id: "deactivated", label: "Deactivated", match: (r) => !r.is_active },
  { id: "unverified", label: "Unverified", match: (r) => !r.email_verified },
  { id: "admins", label: "Admins", match: (r) => r.is_platform_admin || r.placements.some((p) => p.role === "admin") },
];

export const FILTER_ECHO: Record<PeopleFilter, string> = {
  all: "every account",
  active: "active accounts",
  deactivated: "deactivated accounts",
  unverified: "accounts with an unverified email",
  admins: "admin accounts",
};

export function filterPeople(rows: DirectoryRow[], query: string, filter: PeopleFilter): DirectoryRow[] {
  const q = query.trim().toLowerCase();
  const match = PEOPLE_FILTERS.find((f) => f.id === filter)?.match ?? (() => true);
  return rows
    .filter(match)
    .filter((r) => q === "" || r.name.toLowerCase().includes(q) || r.email.toLowerCase().includes(q) || String(r.id).includes(q));
}

export function sortPeople(rows: DirectoryRow[], dir: "asc" | "desc"): DirectoryRow[] {
  return [...rows].sort((a, b) => (dir === "asc" ? a.name.localeCompare(b.name) : b.name.localeCompare(a.name)));
}

/** A selection only ever refers to rows that are still on screen — filtering to something
    else must not quietly act on rows nobody can see. */
export function visibleSelection(selected: number[], rows: DirectoryRow[]): number[] {
  return selected.filter((id) => rows.some((r) => r.id === id));
}

export function toggleSelection(selected: number[], id: number): number[] {
  return selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id];
}

/** Deleting is refused by the API (409) while the person still holds a membership — the
    row would be left pointing at nothing. Pre-empted here so the button explains itself
    rather than failing after the click; the 409 is still handled. */
export function canDeleteAccount(row: DirectoryRow): boolean {
  return row.placements.length === 0;
}
</script>

<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import type { RowMenuItem } from "~/components/RowMenu.vue";
import type { InvitePayload } from "~/components/InviteDialog.vue";
import type {
  DepartmentResponse,
  InviteResponse,
  MemberListResponse,
  PlatformUserListResponse,
  UserAccountResponse,
  UserMeResponse,
} from "~/types/api";
import { ROLES } from "~/types/api";

definePageMeta({ middleware: "auth", layout: false });

const api = useApi();
const auth = useAuth();
const queryClient = useQueryClient();
const say = useAnnounce();
const { show } = useToast();

const me = computed(() => auth.user.value as UserMeResponse | null);
const isPlatformAdmin = computed(() => me.value?.is_platform_admin === true);

const query = ref("");
const filter = ref<PeopleFilter>("all");
const sortDir = ref<"asc" | "desc">("asc");
const selected = ref<number[]>([]);
const menuFor = ref<number | null>(null);
const offset = ref(0);
// The server caps a page at 200. The tab counts below are counts of what is loaded, and
// the footer says so when there is more.
const LIMIT = 200;

watch([query, filter], () => {
  menuFor.value = null;
});
watch(query, () => {
  offset.value = 0;
});

// ── the directory ──────────────────────────────────────────────────────────
const accounts = useQuery({
  queryKey: computed(() => ["platform-users", query.value.trim(), offset.value]),
  enabled: isPlatformAdmin,
  queryFn: () =>
    api.request<PlatformUserListResponse>("/platform/users", {
      query: { limit: LIMIT, offset: offset.value, ...(query.value.trim() ? { q: query.value.trim() } : {}) },
    }),
});

// ── where each account sits ────────────────────────────────────────────────
// GET /platform/users carries no department and no role — those live on the membership
// row. A platform admin passes require_dept_role for every department, so the placement
// map is one read per department and nothing is guessed from an id.
const departments = useQuery({
  queryKey: ["departments"],
  enabled: isPlatformAdmin,
  queryFn: () => api.request<DepartmentResponse[]>("/departments"),
});

const placements = useQuery({
  queryKey: computed(() => ["placements", (departments.data.value ?? []).map((d) => d.id).join(",")]),
  enabled: computed(() => isPlatformAdmin.value && (departments.data.value?.length ?? 0) > 0),
  queryFn: async () => {
    const map: Record<number, Placement[]> = {};
    for (const dept of departments.data.value ?? []) {
      const page = await api.request<MemberListResponse>(`/departments/${dept.id}/members`, {
        query: { limit: 200 },
      });
      for (const m of page.items) {
        (map[m.user_id] ??= []).push({ deptId: dept.id, deptName: dept.name, role: m.role });
      }
    }
    return map;
  },
});

const rows = computed<DirectoryRow[]>(() =>
  (accounts.data.value?.items ?? []).map((u) => ({
    ...u,
    name: fullName(u.first_name, u.last_name, u.email),
    placements: placements.data.value?.[u.id] ?? [],
  })),
);

const shown = computed(() => sortPeople(filterPeople(rows.value, query.value, filter.value), sortDir.value));
const total = computed(() => accounts.data.value?.total ?? 0);
const unverified = computed(() => rows.value.filter((r) => !r.email_verified));

const tabItems = computed(() =>
  PEOPLE_FILTERS.map((f) => ({ id: f.id, label: f.label, hint: String(rows.value.filter(f.match).length) })),
);

const visible = computed(() => visibleSelection(selected.value, shown.value));
const allOn = computed(() => shown.value.length > 0 && visible.value.length === shown.value.length);
const allBox = ref<HTMLInputElement | null>(null);

watch([visible, allOn], () => {
  if (allBox.value) allBox.value.indeterminate = visible.value.length > 0 && !allOn.value;
});

function toggleRow(id: number) {
  selected.value = toggleSelection(selected.value, id);
}

function toggleAll() {
  selected.value = allOn.value ? [] : shown.value.map((r) => r.id);
}

// ── writes ─────────────────────────────────────────────────────────────────
const actionError = ref<string | null>(null);

function refreshDirectory() {
  queryClient.invalidateQueries({ queryKey: ["platform-users"] });
}

const setActive = useMutation({
  mutationFn: (vars: { userId: number; active: boolean }) =>
    api.request<UserAccountResponse>(
      `/platform/users/${vars.userId}/${vars.active ? "reactivate" : "deactivate"}`,
      { method: "POST" },
    ),
  onSuccess: (account) => {
    refreshDirectory();
    // The API answers with the posts they still hold, which is what an admin needs to
    // know next: deactivating does not hand over a headship.
    const posts = [...(account.still_heads ?? []), ...(account.still_leads ?? [])];
    show(
      account.is_active
        ? `${account.email} reactivated. They can sign in again.`
        : `${account.email} deactivated. Their sessions end within a minute.${posts.length ? ` Still holds: ${posts.join(", ")}.` : ""}`,
      account.is_active ? "ok" : "warn",
    );
  },
  onError: (err) => {
    actionError.value = apiMessage(err, "Could not change that account.");
  },
});

const setPlatformAdmin = useMutation({
  mutationFn: (vars: { userId: number; grant: boolean }) =>
    api.request<unknown>(`/platform/admins/${vars.userId}`, { method: vars.grant ? "PUT" : "DELETE" }),
  onSuccess: (_data, vars) => {
    refreshDirectory();
    show(
      vars.grant
        ? "Platform admin granted — that reaches every department."
        : "Platform admin revoked.",
      vars.grant ? "warn" : "muted",
    );
  },
  onError: (err) => {
    actionError.value = apiMessage(err, "Could not change platform admin.");
  },
});

const confirmDelete = ref<DirectoryRow | null>(null);
const deleteError = ref<string | null>(null);

const deleteAccount = useMutation({
  mutationFn: (userId: number) => api.request<void>(`/platform/users/${userId}`, { method: "DELETE" }),
  onSuccess: (_data, userId) => {
    const person = confirmDelete.value;
    confirmDelete.value = null;
    refreshDirectory();
    show(`${person?.name ?? "Account"} deleted. Anything they wrote stays, filed against user_id ${userId}.`, "bad");
  },
  onError: (err) => {
    deleteError.value =
      httpStatus(err) === 409
        ? apiMessage(err, "Refused: they still belong to a department. Remove the membership first.")
        : apiMessage(err, "Could not delete that account.");
  },
});

async function bulkSetActive(active: boolean) {
  actionError.value = null;
  const ids = [...visible.value];
  const results = await Promise.allSettled(
    ids.map((id) =>
      api.request<UserAccountResponse>(`/platform/users/${id}/${active ? "reactivate" : "deactivate"}`, {
        method: "POST",
      }),
    ),
  );
  const failed = results.filter((r) => r.status === "rejected").length;
  refreshDirectory();
  selected.value = [];
  const done = ids.length - failed;
  show(
    failed === 0
      ? `${done} ${done === 1 ? "account" : "accounts"} ${active ? "reactivated" : "deactivated"}.`
      : `${done} of ${ids.length} ${active ? "reactivated" : "deactivated"}; ${failed} refused.`,
    failed === 0 ? (active ? "ok" : "warn") : "bad",
  );
}

watch(
  () => visible.value.length,
  (n) => {
    if (n > 0) say(`${n} ${n === 1 ? "account" : "accounts"} selected`);
  },
);

// ── invite ─────────────────────────────────────────────────────────────────
const inviteOpen = ref(false);
const inviteError = ref<string | null>(null);

const sendInvite = useMutation({
  mutationFn: (payload: InvitePayload) =>
    api.request<InviteResponse>(`/departments/${payload.deptId}/invites`, {
      method: "POST",
      body: { email: payload.email, role: payload.role },
    }),
  onSuccess: (invite, payload) => {
    inviteOpen.value = false;
    const dept = (departments.data.value ?? []).find((d) => d.id === payload.deptId);
    queryClient.invalidateQueries({ queryKey: ["invites", payload.deptId] });
    show(`Invite sent to ${invite.email}${dept ? ` · ${dept.name}` : ""}. It lapses ${expiresIn(invite.expires_at)}.`, "ok");
  },
  onError: (err) => {
    inviteError.value = apiMessage(err, "Could not send that invite.");
  },
});

const deptOptions = computed(() =>
  (departments.data.value ?? []).map((d) => ({ value: String(d.id), label: d.name })),
);
const roleOptions = ROLES.map((r) => ({ value: r, label: r }));

// ── row menu ───────────────────────────────────────────────────────────────
function menuItems(row: DirectoryRow): RowMenuItem[] {
  return [
    { id: row.is_active ? "deactivate" : "reactivate", label: row.is_active ? "Deactivate" : "Reactivate" },
    {
      id: row.is_platform_admin ? "revoke-admin" : "grant-admin",
      label: row.is_platform_admin ? "Revoke platform admin" : "Make platform admin",
    },
    { id: "delete", label: "Delete account", tone: "bad", separatorBefore: true },
  ];
}

function onMenuSelect(row: DirectoryRow, id: string) {
  actionError.value = null;
  if (id === "deactivate" || id === "reactivate") {
    setActive.mutate({ userId: row.id, active: id === "reactivate" });
    return;
  }
  if (id === "grant-admin" || id === "revoke-admin") {
    setPlatformAdmin.mutate({ userId: row.id, grant: id === "grant-admin" });
    return;
  }
  deleteError.value = null;
  confirmDelete.value = row;
}

const readout = computed(() => `${total.value} ${total.value === 1 ? "account" : "accounts"}`);
</script>

<template>
  <IdentityShell :readout="readout">
    <header class="sec flex flex-wrap items-end justify-between gap-4">
      <div class="min-w-0">
        <Eyebrow>Identity · people</Eyebrow>
        <h1 class="mt-3 text-[clamp(1.5rem,2.2vw,1.9rem)] font-semibold leading-[1.05] tracking-[-0.035em]">
          Accounts
        </h1>
        <p class="mt-1.5 max-w-[68ch] text-[12.5px] leading-relaxed text-ink-muted">
          Every account in the workspace, whether or not it has been placed in a department. Identity is the
          only service that holds these records — the products reference them by
          <span class="mono text-[12.5px]">user_id</span>.
        </p>
      </div>
      <Btn v-if="isPlatformAdmin" size="sm" @click="inviteError = null; inviteOpen = true">
        <Icon name="plus" class="h-3.5 w-3.5" />
        Invite someone
      </Btn>
    </header>

    <!-- Not a permission check, just an honest door: /platform/users is 403 for
         anybody else and the whole screen would be empty. -->
    <section v-if="!isPlatformAdmin" class="sec mt-6 border-t border-line-subtle pt-5">
      <p class="text-[13.5px] font-medium text-ink">This directory is platform-admin only.</p>
      <p class="mt-1.5 max-w-[60ch] text-[12.5px] leading-relaxed text-ink-muted">
        An account belongs to the workspace, not to a department, so listing every one of them is not a
        department-level act. A department admin manages their own roster instead.
      </p>
      <div class="mt-4">
        <Btn size="sm" variant="secondary" @click="navigateTo('/departments')">Go to departments</Btn>
      </div>
    </section>

    <template v-else>
      <!-- ── search ── -->
      <div class="sec mt-5 flex flex-wrap items-center gap-2 border-t border-line-subtle pt-4" style="animation-delay: 40ms">
        <label class="flex min-w-[240px] flex-1 items-center gap-2 rounded-md bg-sunken px-2.5 py-2 ring-1 ring-inset ring-line-subtle">
          <Icon name="search" class="h-3.5 w-3.5 shrink-0 text-ink-faint" />
          <span class="sr-only">Search accounts</span>
          <input
            v-model="query"
            type="search"
            autocomplete="off"
            placeholder="Name, email or user_id"
            :class="[FOCUS, 'w-full bg-transparent text-[12.5px] text-ink placeholder:text-ink-faint']"
          />
          <button
            v-if="query !== ''"
            type="button"
            aria-label="Clear search"
            :class="[FOCUS, 'rounded p-0.5 text-ink-faint transition-colors hover:text-ink']"
            @click="query = ''"
          >
            <Icon name="x" class="h-3.5 w-3.5" />
          </button>
        </label>
        <p class="mono text-[12px] text-ink-muted">{{ shown.length }} of {{ rows.length }} shown</p>
      </div>

      <!-- ── filters ── -->
      <div class="sec mt-4" style="animation-delay: 40ms">
        <Tabs
          id="people"
          :model-value="filter"
          label="Filter accounts"
          :items="tabItems"
          @update:model-value="filter = $event as PeopleFilter"
        >
          <span class="hidden sm:flex">
            <StatusDot v-if="unverified.length" tone="warn">{{ unverified.length }} awaiting verification</StatusDot>
            <StatusDot v-else tone="ok">Every email verified</StatusDot>
          </span>
        </Tabs>
        <div class="mt-2 sm:hidden">
          <StatusDot v-if="unverified.length" tone="warn">{{ unverified.length }} awaiting verification</StatusDot>
          <StatusDot v-else tone="ok">Every email verified</StatusDot>
        </div>
      </div>

      <!-- ── the one thing here that somebody has to act on ── -->
      <div
        v-if="unverified.length > 0 && filter !== 'unverified'"
        class="sec mt-4 flex flex-wrap items-start gap-3 rounded-md bg-warn-surface px-4 py-3"
        style="animation-delay: 80ms"
      >
        <span class="mt-0.5 shrink-0 text-warn"><Icon name="alert" /></span>
        <p class="min-w-0 flex-1 text-[12.5px] leading-relaxed text-ink">
          <span class="font-medium">
            {{ unverified.length }} {{ unverified.length === 1 ? "person has" : "people have" }} never confirmed
            their email address.
          </span>
          <span class="text-ink-muted">
            They can sign in, but a password reset will not reach them. Accepting an emailed invite is the only
            thing that lifts this — there is no resend-verification endpoint, so a sign-up that skipped an
            invite stays here.
          </span>
        </p>
        <button
          type="button"
          :class="[FOCUS, 'shrink-0 rounded-md px-2.5 py-1 text-[12px] font-medium text-ink transition-colors hover:bg-surface-hover']"
          @click="filter = 'unverified'"
        >
          Review them
        </button>
      </div>

      <p v-if="actionError" role="alert" class="mt-4 rounded-md bg-bad-surface px-3 py-2 text-[12.5px] text-bad">
        {{ actionError }}
      </p>

      <!-- ── bulk bar ── -->
      <div
        v-if="visible.length > 0"
        class="xfade mt-4 flex flex-wrap items-center gap-2 rounded-md bg-surface-active px-3 py-2.5 ring-1 ring-inset ring-line"
      >
        <span class="mono text-[12px] text-ink">{{ visible.length }} selected</span>
        <!-- `--line` rather than `--line-subtle`: this rule is the one place in the
             platform where a hairline sits on `--surface-active`, where subtle measures
             1.65:1 and is effectively not drawn. -->
        <span class="h-4 w-px bg-line" aria-hidden="true" />
        <button
          type="button"
          :class="[FOCUS, TAP, 'rounded-md px-2.5 py-1.5 text-[12px] text-ink transition-colors hover:bg-surface-hover']"
          @click="bulkSetActive(false)"
        >
          Deactivate
        </button>
        <button
          type="button"
          :class="[FOCUS, TAP, 'rounded-md px-2.5 py-1.5 text-[12px] text-ink transition-colors hover:bg-surface-hover']"
          @click="bulkSetActive(true)"
        >
          Reactivate
        </button>
        <button
          type="button"
          :class="[FOCUS, TAP, 'ml-auto rounded-md px-2.5 py-1.5 text-[12px] text-ink-muted transition-colors hover:bg-surface-hover hover:text-ink']"
          @click="selected = []"
        >
          Clear
        </button>
      </div>

      <!-- ── loading / error / directory ── -->
      <div v-if="accounts.isPending.value" class="sec mt-4 space-y-2" role="status">
        <span class="sr-only">Loading the directory</span>
        <span v-for="i in 6" :key="i" class="block h-11 rounded-md bg-surface/40 ring-1 ring-inset ring-line-subtle" aria-hidden="true" />
      </div>

      <div
        v-else-if="accounts.isError.value"
        role="alert"
        class="sec mt-4 rounded-md bg-bad-surface px-4 py-3.5"
      >
        <p class="text-[13px] font-medium text-ink">The directory did not load.</p>
        <p class="mt-1 max-w-[60ch] text-[12.5px] leading-relaxed text-ink-muted">
          {{ apiMessage(accounts.error.value, "Identity did not answer.") }}
        </p>
        <div class="mt-3">
          <Btn size="sm" variant="secondary" @click="accounts.refetch()">Try again</Btn>
        </div>
      </div>

      <template v-else>
        <p
          v-if="placements.isError.value"
          role="alert"
          class="sec mt-4 rounded-md bg-warn-surface px-3 py-2 text-[12px] leading-relaxed text-ink"
        >
          Department and role could not be read, so those two columns are blank rather than guessed.
          {{ apiMessage(placements.error.value, "") }}
        </p>

        <div
          class="sec relative mt-4 overflow-x-auto rounded-md bg-surface/40 ring-1 ring-inset ring-line-subtle"
          style="animation-delay: 80ms"
        >
          <table class="w-full table-fixed border-collapse">
            <caption class="sr-only">
              Accounts, sorted by name {{ sortDir === "asc" ? "A to Z" : "Z to A" }}
            </caption>
            <thead>
              <tr class="border-b border-line-subtle">
                <th scope="col" class="w-9 px-3 py-2.5">
                  <input
                    ref="allBox"
                    type="checkbox"
                    :checked="allOn"
                    :disabled="shown.length === 0"
                    aria-label="Select every account shown"
                    :class="[FOCUS, 'h-3.5 w-3.5']"
                    style="accent-color: var(--ink)"
                    @change="toggleAll"
                  />
                </th>
                <th
                  scope="col"
                  :aria-sort="sortDir === 'asc' ? 'ascending' : 'descending'"
                  class="px-1 py-2.5 text-left"
                >
                  <button
                    type="button"
                    :class="[FOCUS, 'inline-flex items-center gap-1.5 rounded text-[12px] font-medium uppercase tracking-[0.08em] text-ink-faint transition-colors hover:text-ink']"
                    @click="sortDir = sortDir === 'asc' ? 'desc' : 'asc'"
                  >
                    Person
                    <Icon name="chevronDown" :class="['h-3 w-3 transition-transform', sortDir === 'desc' && 'rotate-180']" />
                  </button>
                </th>
                <th scope="col" class="hidden w-[160px] px-3 py-2.5 text-left text-[12px] font-medium uppercase tracking-[0.08em] text-ink-faint md:table-cell">
                  Department
                </th>
                <th scope="col" class="hidden w-[104px] px-3 py-2.5 text-left text-[12px] font-medium uppercase tracking-[0.08em] text-ink-faint sm:table-cell">
                  Role
                </th>
                <th scope="col" class="w-[124px] px-3 py-2.5 text-left text-[12px] font-medium uppercase tracking-[0.08em] text-ink-faint">
                  Status
                </th>
                <th scope="col" class="w-11 px-3 py-2.5"><span class="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(row, i) in shown"
                :key="row.id"
                :class="[
                  'group/row sec border-b border-line-subtle/70 transition-colors last:border-0 hover:bg-surface-hover/50',
                ]"
                :style="{ animationDelay: `${Math.min(i, 3) * 40}ms` }"
              >
                <td class="px-3 py-2.5 align-middle">
                  <input
                    type="checkbox"
                    :checked="selected.includes(row.id)"
                    :aria-label="`Select ${row.name}`"
                    :class="[
                      FOCUS,
                      'h-3.5 w-3.5 transition-opacity focus-visible:opacity-100 group-hover/row:opacity-100 [@media(hover:none)]:opacity-100',
                      selected.includes(row.id) ? 'opacity-100' : 'opacity-0',
                    ]"
                    style="accent-color: var(--ink)"
                    @change="toggleRow(row.id)"
                  />
                </td>
                <td class="px-1 py-2.5">
                  <div class="flex min-w-0 items-center gap-2.5">
                    <Avatar :name="row.name" size="sm" />
                    <div class="min-w-0">
                      <!-- A deactivated account dims its type rather than the whole row.
                           `opacity-60` faded the row rule with it: the hairline fell to
                           1.40:1 and the muted email to 3.20:1 in light, both unreadable.
                           `--ink-disabled` is the token the platform already uses for a
                           record that is not live, and leaves the border alone. -->
                      <p :class="['flex items-center gap-1.5 truncate text-[12.5px]', row.is_active ? 'text-ink' : 'text-ink-disabled']">
                        {{ row.name }}
                        <span
                          v-if="row.id === me?.id"
                          class="mono shrink-0 rounded bg-sunken px-1 py-px text-[12px] uppercase tracking-[0.08em] text-ink-muted"
                        >you</span>
                      </p>
                      <p :class="['mono mt-0.5 flex items-center gap-1 truncate text-[12px]', row.is_active ? 'text-ink-muted' : 'text-ink-disabled']">
                        <Icon v-if="!row.email_verified" name="alert" class="h-3 w-3 shrink-0 text-warn" />
                        <span class="truncate">{{ row.email }}</span>
                      </p>
                    </div>
                  </div>
                </td>
                <td class="hidden px-3 py-2.5 md:table-cell">
                  <!-- A tinted chip in every row outshouts the names beside it, so an
                       unplaced account carries the warning on its dot instead. -->
                  <StatusDot v-if="row.placements.length === 0" tone="warn" quiet>Unplaced</StatusDot>
                  <span
                    v-for="p in row.placements"
                    :key="p.deptId"
                    :class="['mono mr-1 inline-block max-w-full truncate rounded bg-sunken px-1.5 py-0.5 text-[12px]', row.is_active ? 'text-ink-muted' : 'text-ink-disabled']"
                  >{{ p.deptName }}</span>
                </td>
                <td class="hidden px-3 py-2.5 sm:table-cell">
                  <span :class="['text-[12px]', row.is_active ? 'text-ink-muted' : 'text-ink-disabled']">
                    {{ row.placements.map((p) => p.role).join(", ") || "—" }}
                  </span>
                  <span v-if="row.is_platform_admin" :class="['mono mt-0.5 block text-[12px] uppercase tracking-[0.08em]', row.is_active ? 'text-ink-muted' : 'text-ink-disabled']">
                    platform
                  </span>
                </td>
                <td class="px-3 py-2.5">
                  <StatusDot v-if="!row.is_active" tone="muted" quiet>Deactivated</StatusDot>
                  <StatusDot v-else-if="!row.email_verified" tone="warn" quiet>Unverified</StatusDot>
                  <StatusDot v-else tone="ok" quiet>Active</StatusDot>
                </td>
                <td class="relative px-3 py-2.5 text-right">
                  <RowMenu
                    v-if="row.id !== me?.id"
                    :open="menuFor === row.id"
                    :label="`Actions for ${row.name}`"
                    :items="menuItems(row)"
                    @update:open="menuFor = $event ? row.id : null"
                    @select="onMenuSelect(row, $event)"
                  />
                  <span v-else class="mono text-[12px] text-ink-muted">you</span>
                </td>
              </tr>
            </tbody>
          </table>

          <div v-if="shown.length === 0" class="px-6 py-14 text-center">
            <p class="text-[13.5px] font-medium text-ink">Nothing matches</p>
            <p class="mx-auto mt-1.5 max-w-[54ch] text-[12.5px] leading-relaxed text-ink-muted">
              No account matching
              <span v-if="query.trim()" class="mono text-[12.5px] text-ink">“{{ query.trim() }}”</span>
              <span v-else>anything</span>
              among {{ FILTER_ECHO[filter] }}.
            </p>
            <div class="mt-4 flex justify-center">
              <Btn size="sm" variant="secondary" @click="query = ''; filter = 'all'">Clear filters</Btn>
            </div>
          </div>
        </div>

        <div v-if="total > LIMIT" class="sec mt-3 flex flex-wrap items-center justify-between gap-3">
          <p class="mono text-[12px] text-ink-muted">
            {{ offset + 1 }}–{{ Math.min(offset + LIMIT, total) }} of {{ total }} · the filters above count this
            page
          </p>
          <div class="flex gap-2">
            <Btn size="sm" variant="secondary" :disabled="offset === 0" @click="offset = Math.max(0, offset - LIMIT)">
              Previous
            </Btn>
            <Btn size="sm" variant="secondary" :disabled="offset + LIMIT >= total" @click="offset = offset + LIMIT">
              Next
            </Btn>
          </div>
        </div>

        <p class="sec mt-3 text-[12px] leading-relaxed text-ink-faint" style="animation-delay: 120ms">
          Deactivating keeps the record and cuts the sessions. Deleting removes the account, and is refused while
          the person still belongs to a department — the membership row has to go first.
        </p>
      </template>

      <!-- ── delete ── -->
      <Modal
        :open="confirmDelete !== null"
        :title="confirmDelete ? `Delete ${confirmDelete.name}?` : 'Delete account'"
        description="This removes the account. Anything they wrote stays where it is, filed against their id."
        :close-on-backdrop="false"
        @close="confirmDelete = null"
      >
        <div v-if="confirmDelete" class="space-y-3">
          <p class="mono text-[12px] text-ink-muted">
            user_id {{ confirmDelete.id }} · {{ confirmDelete.email }}
          </p>
          <div
            v-if="!canDeleteAccount(confirmDelete)"
            class="flex items-start gap-2.5 rounded-md bg-warn-surface px-3 py-2.5"
          >
            <span class="mt-0.5 shrink-0 text-warn"><Icon name="alert" class="h-3.5 w-3.5" /></span>
            <p class="text-[12px] leading-relaxed text-ink">
              <span class="font-medium">
                They still belong to
                {{ confirmDelete.placements.map((p) => p.deptName).join(", ") }}, so the API refuses this.
              </span>
              <span class="text-ink-muted">
                Remove the membership on the Organisation screen first, or deactivate the account instead —
                that ends their sessions without breaking anything that points at them.
              </span>
            </p>
          </div>
          <p v-else class="text-[12px] leading-relaxed text-ink-muted">
            They belong to no department, so nothing in identity points at this record. Deleting cannot be
            undone.
          </p>
          <p v-if="deleteError" role="alert" class="rounded bg-bad-surface px-3 py-2 text-[12px] text-bad">
            {{ deleteError }}
          </p>
        </div>
        <template #footer>
          <Btn size="sm" variant="secondary" @click="confirmDelete = null">Cancel</Btn>
          <Btn
            size="sm"
            variant="destructive"
            :disabled="!confirmDelete || !canDeleteAccount(confirmDelete)"
            :busy="deleteAccount.isPending.value"
            @click="deleteAccount.mutate(confirmDelete!.id)"
          >
            Delete account
          </Btn>
        </template>
      </Modal>

      <InviteDialog
        :open="inviteOpen"
        :departments="deptOptions"
        :roles="roleOptions"
        :busy="sendInvite.isPending.value"
        :server-error="inviteError"
        @close="inviteOpen = false"
        @submit="inviteError = null; sendInvite.mutate($event)"
      />
    </template>
  </IdentityShell>
</template>
