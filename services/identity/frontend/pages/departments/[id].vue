<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { z } from "zod";
import type { InvitePayload } from "~/components/InviteDialog.vue";
import type { Roster } from "~/components/DeptRail.vue";
import type {
  DepartmentResponse,
  InviteResponse,
  MemberListResponse,
  MemberResponse,
  PlatformAdminResponse,
  PlatformUserListResponse,
  Role,
  UserMeResponse,
} from "~/types/api";
import { ROLES } from "~/types/api";

/* Organisation — the detail half. Same rail as /departments, so the two URLs are one
   screen with a selection rather than two designs. */
definePageMeta({ middleware: "auth", layout: false });

const route = useRoute();
const api = useApi();
const auth = useAuth();
const queryClient = useQueryClient();
const { show } = useToast();
const say = useAnnounce();

const deptId = computed(() => Number(route.params.id));
const me = computed(() => auth.user.value as UserMeResponse | null);
const isPlatformAdmin = computed(() => me.value?.is_platform_admin === true);
const canAdmin = computed(
  () =>
    isPlatformAdmin.value ||
    (me.value?.memberships ?? []).some((m) => m.dept_id === deptId.value && m.role === "admin"),
);

// ── the rail ───────────────────────────────────────────────────────────────
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

const ROSTER_PAGE = 200;

const rosters = useQuery({
  queryKey: computed(() => ["dept-rosters", readable.value.map((d) => d.id).join(",")]),
  enabled: computed(() => readable.value.length > 0),
  queryFn: async () => {
    const map: Record<number, Roster | null> = {};
    for (const dept of readable.value) {
      const page = await api.request<MemberListResponse>(`/departments/${dept.id}/members`, {
        query: { limit: ROSTER_PAGE },
      });
      map[dept.id] = { total: page.total, members: page.items };
    }
    return map;
  },
});

// ── this department ────────────────────────────────────────────────────────
const dept = useQuery({
  queryKey: computed(() => ["department", deptId.value]),
  queryFn: () => api.request<DepartmentResponse>(`/departments/${deptId.value}`),
  retry: false,
});

const rosterQuery = ref("");
const roleFilter = ref<"" | Role>("");
const offset = ref(0);
const LIMIT = 50;

watch([rosterQuery, roleFilter, deptId], () => {
  offset.value = 0;
  openRow.value = null;
});

const members = useQuery({
  queryKey: computed(() => ["members", deptId.value, rosterQuery.value.trim(), roleFilter.value, offset.value]),
  queryFn: () =>
    api.request<MemberListResponse>(`/departments/${deptId.value}/members`, {
      query: {
        limit: LIMIT,
        offset: offset.value,
        ...(rosterQuery.value.trim() ? { q: rosterQuery.value.trim() } : {}),
        ...(roleFilter.value ? { role: roleFilter.value } : {}),
      },
    }),
});

const shown = computed(() => members.data.value?.items ?? []);
const total = computed(() => members.data.value?.total ?? 0);
const openRow = ref<number | null>(null);

// Which of these people also hold platform admin. Only a platform admin can read it, so
// for anybody else the workspace-wide line is left off rather than guessed.
const platformAdmins = useQuery({
  queryKey: ["platform-admins"],
  enabled: isPlatformAdmin,
  queryFn: () => api.request<PlatformAdminResponse[]>("/platform/admins"),
});

const adminIds = computed(() => new Set((platformAdmins.data.value ?? []).map((a) => a.id)));

function roleCount(role: Role): number {
  return shown.value.filter((m) => m.role === role).length;
}

function invalidateDept() {
  queryClient.invalidateQueries({ queryKey: ["members", deptId.value] });
  queryClient.invalidateQueries({ queryKey: ["department", deptId.value] });
  queryClient.invalidateQueries({ queryKey: ["departments"] });
  queryClient.invalidateQueries({ queryKey: ["dept-rosters"] });
}

// ── role ───────────────────────────────────────────────────────────────────
const memberError = ref<string | null>(null);

const changeRole = useMutation({
  mutationFn: (vars: { userId: number; role: Role }) =>
    api.request<MemberResponse>(`/departments/${deptId.value}/members/${vars.userId}`, {
      method: "PATCH",
      body: { role: vars.role },
    }),
  onSuccess: (member) => {
    invalidateDept();
    say(`Role changed to ${member.role}`);
  },
  onError: (err) => {
    memberError.value =
      httpStatus(err) === 409
        ? apiMessage(err, "That demotion would leave a team or the department without anyone in charge.")
        : apiMessage(err, "Could not change that role.");
  },
});

// ── remove ─────────────────────────────────────────────────────────────────
const removing = ref<MemberResponse | null>(null);
const replacement = ref("");
const removeError = ref<string | null>(null);
const removeBlocked = ref(false);

const removeMember = useMutation({
  mutationFn: (vars: { userId: number; replacementUserId?: number; allowUnled?: boolean }) =>
    api.request<void>(`/departments/${deptId.value}/members/${vars.userId}`, {
      method: "DELETE",
      query: {
        ...(vars.replacementUserId ? { replacement_user_id: vars.replacementUserId } : {}),
        ...(vars.allowUnled ? { allow_unled: true } : {}),
      },
    }),
  onSuccess: (_data, vars) => {
    const person = removing.value;
    removing.value = null;
    replacement.value = "";
    removeBlocked.value = false;
    openRow.value = null;
    invalidateDept();
    show(
      `${person ? fullName(person.first_name, person.last_name, person.email) : `user_id ${vars.userId}`} removed from ${dept.data.value?.name ?? "the department"}. The account stays, unplaced.`,
      "warn",
    );
  },
  onError: (err) => {
    removeBlocked.value = httpStatus(err) === 409;
    removeError.value = removeBlocked.value
      ? apiMessage(err, "Removing them would leave a team or the department without anyone in charge.")
      : apiMessage(err, "Could not remove that person.");
  },
});

function submitRemove(allowUnled = false) {
  removeError.value = null;
  removeMember.mutate({
    userId: removing.value!.user_id,
    replacementUserId: replacement.value ? Number(replacement.value) : undefined,
    allowUnled,
  });
}

const replacementOptions = computed(() =>
  shown.value
    .filter((m) => m.user_id !== removing.value?.user_id)
    .map((m) => ({ value: String(m.user_id), label: `${fullName(m.first_name, m.last_name, m.email)} · ${m.role}` })),
);

// ── head ───────────────────────────────────────────────────────────────────
// The API refuses a head who does not already hold admin here, so only admins are offered.
const deptAdmins = useQuery({
  queryKey: computed(() => ["members", deptId.value, "admins"]),
  enabled: isPlatformAdmin,
  queryFn: () =>
    api.request<MemberListResponse>(`/departments/${deptId.value}/members`, {
      query: { role: "admin", limit: 200 },
    }),
});

const headChoice = ref("");
const headError = ref<string | null>(null);

watch(
  () => dept.data.value,
  (d) => {
    headChoice.value = d?.head_user_id === null || d?.head_user_id === undefined ? "" : String(d.head_user_id);
  },
  { immediate: true },
);

const headOptions = computed(() => [
  { value: "", label: "Nobody" },
  ...(deptAdmins.data.value?.items ?? []).map((m) => ({
    value: String(m.user_id),
    label: fullName(m.first_name, m.last_name, m.email),
  })),
]);

const saveHead = useMutation({
  mutationFn: (userId: string) =>
    userId === ""
      ? api.request<DepartmentResponse>(`/departments/${deptId.value}/head`, { method: "DELETE" })
      : api.request<DepartmentResponse>(`/departments/${deptId.value}/head/${userId}`, { method: "PUT" }),
  onSuccess: (updated) => {
    invalidateDept();
    show(updated.head_name ? `${updated.head_name} is head of ${updated.name}.` : `${updated.name} has no head.`, "ok");
  },
  onError: (err) => {
    headError.value = apiMessage(err, "Could not set the head.");
  },
});

const headDirty = computed(() => headChoice.value !== (dept.data.value?.head_user_id === null || dept.data.value?.head_user_id === undefined ? "" : String(dept.data.value.head_user_id)));

// ── rename ─────────────────────────────────────────────────────────────────
const renaming = ref(false);
const renameValue = ref("");
const renameError = ref<string | null>(null);
const renameField = ref<HTMLInputElement | null>(null);

const rename = useMutation({
  mutationFn: (name: string) =>
    api.request<DepartmentResponse>(`/departments/${deptId.value}`, { method: "PATCH", body: { name } }),
  onSuccess: (updated) => {
    renaming.value = false;
    invalidateDept();
    show(`Renamed to ${updated.name}. The id and the slug do not change, so nothing filed against it moves.`, "ok");
  },
  onError: (err) => {
    renameError.value = apiMessage(err, "Could not rename it.");
  },
});

function submitRename() {
  renameError.value = null;
  const parsed = z.string().trim().min(1, "Give it a name.").max(200).safeParse(renameValue.value);
  if (!parsed.success) {
    renameError.value = parsed.error.issues[0]?.message ?? "Check the name.";
    return;
  }
  rename.mutate(parsed.data);
}

// ── invites ────────────────────────────────────────────────────────────────
const invites = useQuery({
  queryKey: computed(() => ["invites", deptId.value]),
  enabled: canAdmin,
  queryFn: () => api.request<InviteResponse[]>(`/departments/${deptId.value}/invites`),
});

const inviteOpen = ref(false);
const inviteError = ref<string | null>(null);

const sendInvite = useMutation({
  mutationFn: (payload: InvitePayload) =>
    api.request<InviteResponse>(`/departments/${payload.deptId}/invites`, {
      method: "POST",
      body: { email: payload.email, role: payload.role },
    }),
  onSuccess: (invite) => {
    inviteOpen.value = false;
    queryClient.invalidateQueries({ queryKey: ["invites", deptId.value] });
    show(`Invite sent to ${invite.email}. It lapses ${expiresIn(invite.expires_at)}.`, "ok");
  },
  onError: (err) => {
    inviteError.value =
      httpStatus(err) === 409
        ? apiMessage(err, "That address has already been invited here, or already belongs to this department.")
        : apiMessage(err, "Could not send that invite.");
  },
});

const revokeInvite = useMutation({
  mutationFn: (inviteId: number) =>
    api.request<void>(`/departments/${deptId.value}/invites/${inviteId}`, { method: "DELETE" }),
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: ["invites", deptId.value] });
    show("Invite revoked. The link in that email stops working.", "muted");
  },
});

const roleOptions = ROLES.map((r) => ({ value: r, label: r }));

// ── place an existing account ──────────────────────────────────────────────
// Searching every account is platform-admin only, so a department admin brings people in
// by invite. This is for an account that already signed up and needs placing.
const placing = ref(false);
const placeQuery = ref("");
const placeRole = ref<Role>("engineer");
const placeError = ref<string | null>(null);

const candidates = useQuery({
  queryKey: computed(() => ["platform-users", "place", placeQuery.value.trim()]),
  enabled: computed(() => placing.value && isPlatformAdmin.value),
  queryFn: () =>
    api.request<PlatformUserListResponse>("/platform/users", {
      query: { limit: 10, is_active: true, ...(placeQuery.value.trim() ? { q: placeQuery.value.trim() } : {}) },
    }),
});

const addMember = useMutation({
  mutationFn: (vars: { userId: number; role: Role }) =>
    api.request<MemberResponse>(`/departments/${deptId.value}/members`, {
      method: "POST",
      body: { user_id: vars.userId, role: vars.role },
    }),
  onSuccess: (member) => {
    placing.value = false;
    placeQuery.value = "";
    invalidateDept();
    show(`${fullName(member.first_name, member.last_name, member.email)} placed as ${member.role}.`, "ok");
  },
  onError: (err) => {
    placeError.value =
      httpStatus(err) === 409
        ? apiMessage(err, "They already belong to this department.")
        : apiMessage(err, "Could not add them.");
  },
});

// ── delete ─────────────────────────────────────────────────────────────────
const confirmingDelete = ref(false);
const deleteError = ref<string | null>(null);

const deleteDept = useMutation({
  mutationFn: () => api.request<void>(`/departments/${deptId.value}`, { method: "DELETE" }),
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: ["departments"] });
    show("Department deleted.", "bad");
    navigateTo("/departments");
  },
  onError: (err) => {
    deleteError.value = apiMessage(err, "Could not delete this department.");
  },
});

const readout = computed(() => `dept_id ${deptId.value} · ${total.value} ${total.value === 1 ? "member" : "members"}`);
</script>

<template>
  <IdentityShell :readout="readout">
    <header class="sec min-w-0">
      <Eyebrow>Identity · organisation</Eyebrow>
      <h1 class="mt-3 text-[clamp(1.5rem,2.2vw,1.9rem)] font-semibold leading-[1.05] tracking-[-0.035em]">
        {{ dept.data.value?.name ?? "Department" }}
      </h1>
      <p v-if="dept.data.value" class="mono mt-1.5 text-[12px] text-ink-muted">
        dept_id {{ dept.data.value.id }} · {{ dept.data.value.slug }}
      </p>
    </header>

    <div class="mt-6 grid gap-5 lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
      <!-- ── rail ── -->
      <div class="sec min-w-0" style="animation-delay: 40ms">
        <div class="flex items-center gap-2">
          <Cross />
          <Eyebrow>Structure</Eyebrow>
        </div>
        <div class="mt-3">
          <DeptRail
            :departments="departments.data.value ?? []"
            :rosters="rosters.data.value ?? {}"
            :selected-id="deptId"
          />
        </div>
      </div>

      <!-- ── detail ── -->
      <div class="sec min-w-0" style="animation-delay: 80ms">
        <div v-if="dept.isPending.value" class="space-y-2" role="status">
          <span class="sr-only">Loading the department</span>
          <span v-for="i in 4" :key="i" class="block h-12 rounded-md bg-surface/40 ring-1 ring-inset ring-line-subtle" aria-hidden="true" />
        </div>

        <div v-else-if="dept.isError.value" role="alert" class="rounded-md bg-bad-surface px-4 py-3.5">
          <p class="text-[13px] font-medium text-ink">This department is not open to you.</p>
          <p class="mt-1 max-w-[60ch] text-[12.5px] leading-relaxed text-ink-muted">
            {{ apiMessage(dept.error.value, "A department is readable by its own members and by a platform admin.") }}
          </p>
          <div class="mt-3">
            <Btn size="sm" variant="secondary" @click="navigateTo('/departments')">Back to departments</Btn>
          </div>
        </div>

        <template v-else-if="dept.data.value">
          <!-- ── head ── -->
          <section aria-label="Department head" class="rounded-md bg-surface/40 px-4 py-3.5 ring-1 ring-inset ring-line-subtle">
            <div class="flex flex-wrap items-start justify-between gap-3">
              <div class="min-w-0">
                <h2 class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">Head</h2>
                <p class="mt-1 max-w-[64ch] text-[12.5px] leading-relaxed text-ink-muted">
                  One named person. Being head grants nothing on its own — every permission check reads the role
                  on the membership row, never this field.
                </p>
              </div>
              <p v-if="!isPlatformAdmin" class="shrink-0 text-[12.5px]">
                <span v-if="dept.data.value.head_name" class="text-ink">{{ dept.data.value.head_name }}</span>
                <StatusDot v-else tone="warn" quiet>No head</StatusDot>
              </p>
            </div>

            <div v-if="isPlatformAdmin" class="mt-3 flex flex-wrap items-end gap-2 border-t border-line-subtle pt-3">
              <div class="min-w-[220px]">
                <span :class="[MONO_LABEL, 'text-ink-faint']">Head</span>
                <div class="mt-1.5">
                  <Select v-model="headChoice" label="Department head" :options="headOptions" />
                </div>
              </div>
              <Btn
                size="sm"
                variant="secondary"
                :disabled="!headDirty"
                :busy="saveHead.isPending.value"
                @click="headError = null; saveHead.mutate(headChoice)"
              >
                Save head
              </Btn>
              <p v-if="!(deptAdmins.data.value?.items ?? []).length" class="text-[12px] leading-relaxed text-ink-muted">
                Nobody here holds <span class="mono text-[12px]">admin</span>, so there is nobody who may be head yet.
              </p>
            </div>
            <p v-if="headError" role="alert" class="mt-3 rounded bg-bad-surface px-3 py-2 text-[12px] text-bad">
              {{ headError }}
            </p>
          </section>

          <!-- ── roster ── -->
          <section aria-label="Roster" class="mt-5 overflow-hidden rounded-md bg-surface/40 ring-1 ring-inset ring-line-subtle">
            <header class="flex flex-wrap items-center gap-3 border-b border-line-subtle px-4 py-3">
              <div class="min-w-0">
                <h2 class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">Roster</h2>
                <p class="mono mt-0.5 text-[12px] text-ink-muted">
                  {{ roleCount("admin") }} admin · {{ roleCount("manager") }} manager ·
                  {{ roleCount("engineer") }} engineer
                </p>
              </div>
              <label class="ml-auto flex min-w-[180px] items-center gap-2 rounded-md bg-sunken px-2.5 py-1.5 ring-1 ring-inset ring-line-subtle">
                <Icon name="search" class="h-3.5 w-3.5 shrink-0 text-ink-faint" />
                <span class="sr-only">Search this department</span>
                <input
                  v-model="rosterQuery"
                  type="search"
                  autocomplete="off"
                  placeholder="Search this department"
                  :class="[FOCUS, 'w-full bg-transparent text-[12px] text-ink placeholder:text-ink-faint']"
                />
                <button
                  v-if="rosterQuery !== ''"
                  type="button"
                  aria-label="Clear"
                  :class="[FOCUS, 'rounded p-0.5 text-ink-faint transition-colors hover:text-ink']"
                  @click="rosterQuery = ''"
                >
                  <Icon name="x" class="h-3 w-3" />
                </button>
              </label>
            </header>

            <div v-if="members.isPending.value" class="space-y-px p-3" role="status">
              <span class="sr-only">Loading the roster</span>
              <span v-for="i in 4" :key="i" class="block h-10 rounded bg-sunken" aria-hidden="true" />
            </div>

            <div v-else-if="members.isError.value" role="alert" class="px-4 py-6">
              <p class="text-[13px] font-medium text-ink">The roster did not load.</p>
              <p class="mt-1 text-[12.5px] leading-relaxed text-ink-muted">
                {{ apiMessage(members.error.value, "Identity did not answer.") }}
              </p>
              <div class="mt-3">
                <Btn size="sm" variant="secondary" @click="members.refetch()">Try again</Btn>
              </div>
            </div>

            <div v-else-if="shown.length === 0" class="px-6 py-14 text-center">
              <p class="text-[13.5px] font-medium text-ink">
                {{ rosterQuery || roleFilter ? "Nobody here matches" : `Nobody is in ${dept.data.value.name}` }}
              </p>
              <p class="mx-auto mt-1.5 max-w-[52ch] text-[12.5px] leading-relaxed text-ink-muted">
                <template v-if="rosterQuery || roleFilter">
                  No member matches that filter.
                </template>
                <template v-else>
                  The department exists and is empty. That is a real state, not a loading one — a department is
                  created before anybody is placed in it.
                </template>
              </p>
              <div v-if="rosterQuery || roleFilter" class="mt-4 flex justify-center">
                <Btn size="sm" variant="secondary" @click="rosterQuery = ''; roleFilter = ''">Clear search</Btn>
              </div>
            </div>

            <ul v-else>
              <li
                v-for="(m, i) in shown"
                :key="m.user_id"
                class="sec border-b border-line-subtle/70 last:border-0"
                :style="{ animationDelay: `${Math.min(i, 3) * 40}ms` }"
              >
                <button
                  type="button"
                  :aria-expanded="openRow === m.user_id"
                  :aria-controls="`member-${m.user_id}`"
                  :class="[
                    FOCUS,
                    'flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-surface-hover/60',
                  ]"
                  @click="openRow = openRow === m.user_id ? null : m.user_id"
                >
                  <Avatar :name="fullName(m.first_name, m.last_name, m.email)" size="sm" />
                  <!-- An inactive member dims its type, not the row. This row is the
                       disclosure control, so `opacity-60` faded a live button — and the
                       `<li>` rule with it, at 1.40:1. `--ink-disabled` marks the record
                       without dimming the affordance. -->
                  <span class="min-w-0 flex-1">
                    <span class="flex items-center gap-1.5">
                      <span :class="['truncate text-[12.5px]', m.is_active ? 'text-ink' : 'text-ink-disabled']">
                        {{ fullName(m.first_name, m.last_name, m.email) }}
                      </span>
                      <span
                        v-if="dept.data.value.head_user_id === m.user_id"
                        class="mono shrink-0 rounded bg-sunken px-1 py-px text-[12px] uppercase tracking-[0.08em] text-ink-muted"
                      >head</span>
                      <span
                        v-if="m.user_id === me?.id"
                        class="mono shrink-0 rounded bg-sunken px-1 py-px text-[12px] uppercase tracking-[0.08em] text-ink-muted"
                      >you</span>
                    </span>
                    <span :class="['mono mt-0.5 block truncate text-[12px]', m.is_active ? 'text-ink-muted' : 'text-ink-disabled']">{{ m.email }}</span>
                  </span>
                  <span :class="['hidden w-[74px] shrink-0 text-[12px] sm:block', m.is_active ? 'text-ink-muted' : 'text-ink-disabled']">{{ m.role }}</span>
                  <Icon
                    name="chevronDown"
                    :class="['h-3.5 w-3.5 shrink-0 text-ink-faint transition-transform', openRow === m.user_id && 'rotate-180']"
                  />
                </button>

                <div :id="`member-${m.user_id}`" class="sec-collapse" :data-open="openRow === m.user_id ? 'true' : 'false'">
                  <div>
                    <div class="space-y-3 border-t border-line-subtle bg-sunken/60 px-4 py-3.5">
                      <p class="max-w-[76ch] text-[12.5px] leading-relaxed text-ink">
                        <span class="font-medium">In {{ dept.data.value.name }}: </span>
                        <span class="text-ink-muted">{{ roleBlurb(m.role) }}</span>
                      </p>
                      <p v-if="isPlatformAdmin" class="max-w-[76ch] text-[12.5px] leading-relaxed text-ink-muted">
                        <span class="font-medium text-ink">Workspace-wide: </span>
                        <template v-if="adminIds.has(m.user_id)">
                          they are a platform admin, so they also create and delete departments, name heads, see
                          every account and deactivate people — in every department, not only this one.
                        </template>
                        <template v-else>
                          nothing. Their reach stops at the edge of {{ dept.data.value.name }}.
                        </template>
                      </p>
                      <p
                        v-if="dept.data.value.head_user_id === m.user_id"
                        class="max-w-[76ch] text-[12.5px] leading-relaxed text-ink-muted"
                      >
                        <span class="font-medium text-ink">Being head grants nothing on its own. </span>
                        {{ m.first_name }} can do the above because their role here is
                        <span class="mono text-[12.5px]">{{ m.role }}</span>. Clearing
                        <span class="mono text-[12.5px]">head_user_id</span> would take away the label and change
                        no permission.
                      </p>

                      <div class="flex flex-wrap items-end gap-2 pt-0.5">
                        <div v-if="canAdmin" class="min-w-[160px]">
                          <span :class="[MONO_LABEL, 'text-ink-faint']">Role</span>
                          <div class="mt-1.5">
                            <Select
                              :model-value="m.role"
                              label="Role in this department"
                              :options="roleOptions"
                              :disabled="openRow !== m.user_id || changeRole.isPending.value"
                              @update:model-value="memberError = null; changeRole.mutate({ userId: m.user_id, role: $event as Role })"
                            />
                          </div>
                        </div>
                        <Btn
                          size="sm"
                          variant="secondary"
                          :disabled="openRow !== m.user_id"
                          @click="navigateTo(`/access?person=${m.user_id}`)"
                        >
                          See what they can do
                        </Btn>
                        <Btn
                          v-if="canAdmin"
                          size="sm"
                          variant="destructive"
                          :disabled="openRow !== m.user_id"
                          @click="removing = m; removeError = null; removeBlocked = false; replacement = ''"
                        >
                          Remove from {{ dept.data.value.name }}
                        </Btn>
                      </div>
                    </div>
                  </div>
                </div>
              </li>
            </ul>
          </section>

          <p v-if="memberError" role="alert" class="mt-3 rounded-md bg-bad-surface px-3 py-2 text-[12.5px] text-bad">
            {{ memberError }}
          </p>

          <div v-if="total > LIMIT" class="mt-3 flex flex-wrap items-center justify-between gap-3">
            <p class="mono text-[12px] text-ink-muted">
              {{ offset + 1 }}–{{ Math.min(offset + LIMIT, total) }} of {{ total }}
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

          <div class="mt-4 flex flex-wrap gap-2">
            <Btn
              v-if="canAdmin"
              size="sm"
              variant="secondary"
              @click="renaming = true; renameValue = dept.data.value!.name; renameError = null"
            >
              Rename
            </Btn>
            <Btn v-if="canAdmin" size="sm" @click="inviteError = null; inviteOpen = true">
              <Icon name="plus" class="h-3.5 w-3.5" />
              Invite someone
            </Btn>
            <Btn v-if="isPlatformAdmin" size="sm" variant="secondary" @click="placeError = null; placing = true">
              Place an existing account
            </Btn>
          </div>

          <!-- ── invites ── -->
          <section v-if="canAdmin" aria-label="Pending invites" class="mt-8 border-t border-line-subtle pt-5">
            <div class="flex items-center gap-2">
              <Cross />
              <Eyebrow>Pending invites</Eyebrow>
            </div>
            <p class="mt-2 max-w-[70ch] text-[12.5px] leading-relaxed text-ink-muted">
              An invite emails a link that creates the account and places it here. Accepting it also proves the
              person can read that mailbox, which is the only thing that marks an address verified.
            </p>

            <p v-if="invites.isError.value" role="alert" class="mt-3 text-[12.5px] text-ink-muted">
              {{ apiMessage(invites.error.value, "Invites did not load.") }}
            </p>
            <p v-else-if="invites.isPending.value" class="mt-3 text-[12.5px] text-ink-muted" role="status">
              Loading invites…
            </p>
            <p v-else-if="!invites.data.value?.length" class="mt-3 text-[12.5px] leading-relaxed text-ink-muted">
              Nothing outstanding. Everybody invited has either accepted or had their invite revoked.
            </p>
            <ul v-else class="mt-3 divide-y divide-line-subtle">
              <li v-for="invite in invites.data.value" :key="invite.id" class="flex items-center gap-3 py-2.5">
                <span class="min-w-0 flex-1">
                  <span class="mono block truncate text-[12px] text-ink-muted">{{ invite.email }}</span>
                  <span class="mono mt-0.5 block text-[12px] text-ink-muted">
                    {{ invite.role }} · {{ expiresIn(invite.expires_at) }}
                  </span>
                </span>
                <Btn size="sm" variant="ghost" @click="revokeInvite.mutate(invite.id)">Revoke</Btn>
              </li>
            </ul>
          </section>

          <!-- ── delete ── -->
          <section v-if="isPlatformAdmin" aria-label="Delete this department" class="mt-8 border-t border-line-strong pt-5">
            <h2 class="mono text-[12px] uppercase tracking-[0.08em] text-ink-faint">Delete this department</h2>
            <p class="mt-2 max-w-[70ch] text-[12.5px] leading-relaxed text-ink-muted">
              Only for one created by mistake. Everybody has to be removed first — the API refuses while anyone
              is still a member rather than leaving membership rows pointing at nothing.
            </p>
            <p v-if="deleteError" role="alert" class="mt-3 rounded bg-bad-surface px-3 py-2 text-[12px] text-bad">
              {{ deleteError }}
            </p>
            <div class="mt-3 flex flex-wrap gap-2">
              <Btn v-if="!confirmingDelete" size="sm" variant="destructive" @click="confirmingDelete = true; deleteError = null">
                Delete {{ dept.data.value.name }}
              </Btn>
              <template v-else>
                <Btn size="sm" variant="destructive" :busy="deleteDept.isPending.value" @click="deleteDept.mutate()">
                  Delete for good
                </Btn>
                <Btn size="sm" variant="ghost" @click="confirmingDelete = false">Keep it</Btn>
              </template>
            </div>
          </section>
        </template>
      </div>
    </div>

    <!-- ── rename ── -->
    <Modal :open="renaming" title="Rename department" :initial-focus="renameField" @close="renaming = false">
      <div class="space-y-4">
        <label class="block">
          <span :class="[MONO_LABEL, 'text-ink-faint']">Name</span>
          <input
            ref="renameField"
            v-model="renameValue"
            type="text"
            autocomplete="off"
            :aria-invalid="renameError !== null"
            :class="[FOCUS, 'mt-1.5 w-full rounded-md bg-sunken px-2.5 py-2 text-[12.5px] text-ink ring-1 ring-inset ring-line']"
            @keydown.enter.prevent="submitRename"
          />
          <span class="mt-1.5 block text-[12px] leading-relaxed text-ink-faint">
            The id and the slug stay as they are, so nothing that already points here breaks.
          </span>
        </label>
        <p v-if="renameError" role="alert" class="rounded bg-bad-surface px-3 py-2 text-[12px] text-bad">
          {{ renameError }}
        </p>
      </div>
      <template #footer>
        <Btn size="sm" variant="secondary" @click="renaming = false">Cancel</Btn>
        <Btn size="sm" :busy="rename.isPending.value" @click="submitRename">Save name</Btn>
      </template>
    </Modal>

    <!-- ── remove ── -->
    <Modal
      :open="removing !== null"
      :title="removing ? `Remove ${fullName(removing.first_name, removing.last_name, removing.email)}?` : 'Remove member'"
      description="The account is kept. Only the membership row goes."
      :close-on-backdrop="false"
      @close="removing = null"
    >
      <div v-if="removing" class="space-y-3">
        <p class="mono text-[12px] text-ink-muted">
          user_id {{ removing.user_id }} · {{ removing.role }} · dept_id {{ deptId }}
        </p>
        <p class="text-[12px] leading-relaxed text-ink-muted">
          They keep signing in and keep writing their own weekly report. What they lose is everything the role
          gave them inside {{ dept.data.value?.name }}, and no manager here sees their reports again.
        </p>
        <div v-if="dept.data.value?.head_user_id === removing.user_id" class="flex items-start gap-2.5 rounded-md bg-warn-surface px-3 py-2.5">
          <span class="mt-0.5 shrink-0 text-warn"><Icon name="alert" class="h-3.5 w-3.5" /></span>
          <p class="text-[12px] leading-relaxed text-ink">
            <span class="font-medium">They are the head of {{ dept.data.value?.name }}.</span>
            <span class="text-ink-muted">
              The department is left without one. Nothing breaks; the field simply reads null until a platform
              admin names somebody.
            </span>
          </p>
        </div>
        <div>
          <span :class="[MONO_LABEL, 'text-ink-faint']">Hand their posts to (optional)</span>
          <div class="mt-1.5">
            <Select v-model="replacement" label="Replacement" placeholder="Nobody" :options="replacementOptions" />
          </div>
          <p class="mt-1.5 text-[12px] leading-relaxed text-ink-faint">
            If they lead a team or hold the headship, somebody has to take it over — or the post is left empty
            on purpose.
          </p>
        </div>
        <p v-if="removeError" role="alert" class="rounded bg-bad-surface px-3 py-2 text-[12px] text-bad">
          {{ removeError }}
        </p>
      </div>
      <template #footer>
        <Btn size="sm" variant="secondary" @click="removing = null">Cancel</Btn>
        <Btn
          v-if="removeBlocked"
          size="sm"
          variant="secondary"
          :busy="removeMember.isPending.value"
          @click="submitRemove(true)"
        >
          Remove and leave the post empty
        </Btn>
        <Btn size="sm" variant="destructive" :busy="removeMember.isPending.value" @click="submitRemove(false)">
          Remove from department
        </Btn>
      </template>
    </Modal>

    <!-- ── place ── -->
    <Modal
      :open="placing"
      title="Place an existing account"
      description="For somebody who already has an account — a fresh sign-up, or a move from another department."
      @close="placing = false"
    >
      <div class="space-y-4">
        <label class="block">
          <span :class="[MONO_LABEL, 'text-ink-faint']">Search accounts</span>
          <input
            v-model="placeQuery"
            type="search"
            autocomplete="off"
            placeholder="Name or email"
            :class="[FOCUS, 'mt-1.5 w-full rounded-md bg-sunken px-2.5 py-2 text-[12.5px] text-ink ring-1 ring-inset ring-line placeholder:text-ink-faint']"
          />
        </label>
        <div>
          <span :class="[MONO_LABEL, 'text-ink-faint']">Role</span>
          <div class="mt-1.5">
            <Select
              :model-value="placeRole"
              label="Role"
              :options="roleOptions"
              @update:model-value="placeRole = $event as Role"
            />
          </div>
        </div>

        <p v-if="candidates.isPending.value" class="text-[12.5px] text-ink-muted" role="status">Searching…</p>
        <p v-else-if="candidates.isError.value" role="alert" class="text-[12.5px] text-ink-muted">
          {{ apiMessage(candidates.error.value, "The directory did not answer.") }}
        </p>
        <ul v-else-if="candidates.data.value?.items?.length" class="max-h-64 divide-y divide-line-subtle overflow-y-auto rounded-md ring-1 ring-inset ring-line-subtle">
          <li v-for="person in candidates.data.value.items" :key="person.id" class="flex items-center gap-3 px-3 py-2.5">
            <span class="min-w-0 flex-1">
              <span class="block truncate text-[12.5px] text-ink">
                {{ fullName(person.first_name, person.last_name, person.email) }}
              </span>
              <span class="mono block truncate text-[12px] text-ink-muted">{{ person.email }}</span>
            </span>
            <Btn
              size="sm"
              variant="secondary"
              :busy="addMember.isPending.value"
              @click="placeError = null; addMember.mutate({ userId: person.id, role: placeRole })"
            >
              Add
            </Btn>
          </li>
        </ul>
        <p v-else class="text-[12.5px] text-ink-muted">No matching account.</p>

        <p v-if="placeError" role="alert" class="rounded bg-bad-surface px-3 py-2 text-[12px] text-bad">
          {{ placeError }}
        </p>
      </div>
    </Modal>

    <InviteDialog
      :open="inviteOpen"
      :departments="[]"
      :roles="roleOptions"
      :locked-dept-id="deptId"
      :busy="sendInvite.isPending.value"
      :server-error="inviteError"
      @close="inviteOpen = false"
      @submit="inviteError = null; sendInvite.mutate($event)"
    />
  </IdentityShell>
</template>
