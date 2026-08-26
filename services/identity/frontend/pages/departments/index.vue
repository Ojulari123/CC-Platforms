<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { z } from "zod";
import type { Roster } from "~/components/DeptRail.vue";
import type {
  DepartmentResponse,
  MemberListResponse,
  PlatformUserListResponse,
  UserMeResponse,
} from "~/types/api";

/* Organisation — the master half.

   The prototype draws this as one master/detail screen; the app keeps two URLs, because
   a department is already deep-linkable and people send those links to each other. The
   rail is the same component on both, so selecting one is a navigation, not local state. */
definePageMeta({ middleware: "auth", layout: false });

const api = useApi();
const auth = useAuth();
const queryClient = useQueryClient();
const { show } = useToast();

const me = computed(() => auth.user.value as UserMeResponse | null);
const isPlatformAdmin = computed(() => me.value?.is_platform_admin === true);

const departments = useQuery({
  queryKey: ["departments"],
  queryFn: () => api.request<DepartmentResponse[]>("/departments"),
});

// Only the departments the caller may read. A platform admin passes require_dept_role
// everywhere; anybody else would collect a 403 per department they are not in, so those
// are never asked for and the rail says "not visible to you" instead of a wrong zero.
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

const rosterMap = computed(() => rosters.data.value ?? {});
const truncated = computed(() => Object.values(rosterMap.value).some((r) => r && r.total > ROSTER_PAGE));

// ── accounts outside every department ──────────────────────────────────────
// Needs the whole directory, which is platform-admin only. Rather than guess, the panel
// says who can see it.
const accounts = useQuery({
  queryKey: ["platform-users", "", 0],
  enabled: isPlatformAdmin,
  queryFn: () => api.request<PlatformUserListResponse>("/platform/users", { query: { limit: 200, offset: 0 } }),
});

const placed = computed(() => {
  const ids = new Set<number>();
  for (const roster of Object.values(rosterMap.value)) {
    for (const m of roster?.members ?? []) ids.add(m.user_id);
  }
  return ids;
});

const unplaced = computed(() => (accounts.data.value?.items ?? []).filter((u) => !placed.value.has(u.id)));

const headless = computed(() => (departments.data.value ?? []).filter((d) => d.head_user_id === null));

// ── create ────────────────────────────────────────────────────────────────
const creating = ref(false);
const newName = ref("");
const formError = ref<string | null>(null);
const nameField = ref<HTMLInputElement | null>(null);

const create = useMutation({
  mutationFn: (name: string) =>
    api.request<DepartmentResponse>("/departments", { method: "POST", body: { name } }),
  onSuccess: (dept) => {
    creating.value = false;
    newName.value = "";
    queryClient.invalidateQueries({ queryKey: ["departments"] });
    show(`${dept.name} created. Nobody is in it yet — that is a real state, not a loading one.`, "ok");
  },
  onError: (err) => {
    formError.value = apiMessage(err, "Could not create that department.");
  },
});

function submitCreate() {
  formError.value = null;
  const parsed = z.string().trim().min(1, "Give the department a name.").max(200).safeParse(newName.value);
  if (!parsed.success) {
    formError.value = parsed.error.issues[0]?.message ?? "Check the name.";
    return;
  }
  create.mutate(parsed.data);
}

const count = computed(() => departments.data.value?.length ?? 0);
const readout = computed(() => `${count.value} ${count.value === 1 ? "department" : "departments"}`);
</script>

<template>
  <IdentityShell :readout="readout">
    <header class="sec min-w-0">
      <Eyebrow>Identity · organisation</Eyebrow>
      <h1 class="mt-3 text-[clamp(1.5rem,2.2vw,1.9rem)] font-semibold leading-[1.05] tracking-[-0.035em]">
        Departments
      </h1>
      <p class="mt-1.5 max-w-[72ch] text-[12.5px] leading-relaxed text-ink-muted">
        One organisation, so the department is the grouping people actually choose. Pulse and Forge never copy
        this — they store a <span class="mono text-[12.5px]">dept_id</span> and ask identity what it means.
      </p>
    </header>

    <div v-if="departments.isPending.value" class="sec mt-6 space-y-2" role="status">
      <span class="sr-only">Loading departments</span>
      <span v-for="i in 3" :key="i" class="block h-16 rounded-md bg-surface/40 ring-1 ring-inset ring-line-subtle" aria-hidden="true" />
    </div>

    <div v-else-if="departments.isError.value" role="alert" class="sec mt-6 rounded-md bg-bad-surface px-4 py-3.5">
      <p class="text-[13px] font-medium text-ink">Departments did not load.</p>
      <p class="mt-1 max-w-[60ch] text-[12.5px] leading-relaxed text-ink-muted">
        {{ apiMessage(departments.error.value, "Identity did not answer.") }}
      </p>
      <div class="mt-3">
        <Btn size="sm" variant="secondary" @click="departments.refetch()">Try again</Btn>
      </div>
    </div>

    <div v-else class="mt-6 grid gap-5 lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
      <!-- ── the tree ── -->
      <div class="sec min-w-0" style="animation-delay: 40ms">
        <div class="flex items-center gap-2">
          <Cross />
          <Eyebrow>Structure</Eyebrow>
        </div>

        <div class="mt-3">
          <DeptRail v-if="count" :departments="departments.data.value ?? []" :rosters="rosterMap" />
          <p v-else class="text-[12.5px] leading-relaxed text-ink-muted">
            No department exists yet. Departments are the unit people are placed into; Engineering and Data are
            the usual first two.
          </p>
        </div>

        <p v-if="truncated" class="mono mt-2 text-[12px] leading-relaxed text-ink-muted">
          rosters read {{ ROSTER_PAGE }} members per department, which is the API's page cap
        </p>

        <!-- ── outside every department ── -->
        <div class="mt-5 border-t border-line-strong pt-3">
          <p class="mono flex items-center gap-2 text-[12px] uppercase tracking-[0.08em] text-warn">
            <Icon name="alert" class="h-3.5 w-3.5 shrink-0" />
            Outside every department
          </p>

          <p v-if="!isPlatformAdmin" class="mt-2 text-[12.5px] leading-relaxed text-ink-muted">
            An account with no department is not listed in any department, so only a platform admin can see one.
            You see the departments you belong to.
          </p>
          <p v-else-if="accounts.isPending.value || rosters.isPending.value" class="mt-2 text-[12.5px] text-ink-muted" role="status">
            Reading the directory…
          </p>
          <p v-else-if="accounts.isError.value" role="alert" class="mt-2 text-[12.5px] leading-relaxed text-ink-muted">
            The directory did not load, so this list is unknown rather than empty.
            {{ apiMessage(accounts.error.value, "") }}
          </p>
          <p v-else-if="unplaced.length === 0" class="mt-2 text-[12.5px] leading-relaxed text-ink-muted">
            Everybody is placed.
          </p>
          <template v-else>
            <ul class="mt-1 divide-y divide-line-subtle">
              <li v-for="person in unplaced" :key="person.id" class="flex items-center gap-2.5 py-2">
                <Avatar :name="fullName(person.first_name, person.last_name, person.email)" size="sm" />
                <span class="min-w-0 flex-1">
                  <span class="block truncate text-[12px] text-ink">
                    {{ fullName(person.first_name, person.last_name, person.email) }}
                  </span>
                  <span class="mono block truncate text-[12px] text-ink-muted">{{ person.email }}</span>
                </span>
                <StatusDot v-if="person.is_active" tone="warn" quiet>unplaced</StatusDot>
                <StatusDot v-else tone="muted" quiet>inactive</StatusDot>
              </li>
            </ul>
            <p class="mt-3 text-[12.5px] leading-relaxed text-ink-muted">
              {{ unplaced.length }} {{ unplaced.length === 1 ? "account" : "accounts" }} with
              <span class="mono text-[12px]">dept_id</span> null. They can sign in and write their own report;
              no manager sees it, because a report is read through the department it was filed in.
            </p>
          </template>
        </div>
      </div>

      <!-- ── the right pane ── -->
      <div class="sec min-w-0" style="animation-delay: 80ms">
        <div class="rounded-md bg-surface/40 px-4 py-4 ring-1 ring-inset ring-line-subtle">
          <h2 class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">Pick a department to open its roster</h2>
          <p class="mt-1.5 max-w-[70ch] text-[12.5px] leading-relaxed text-ink-muted">
            Each one has its own URL, so a link to
            <span class="mono text-[12px]">/departments/6</span> reaches the same place tomorrow. Teams sit
            inside a department; roles are set on the membership row, which is what every permission check
            reads.
          </p>
          <div v-if="isPlatformAdmin" class="mt-4">
            <Btn size="sm" @click="formError = null; creating = true">
              <Icon name="plus" class="h-3.5 w-3.5" />
              New department
            </Btn>
          </div>
        </div>

        <section class="mt-6 border-t border-line-subtle pt-5" aria-label="Two facts this screen exists to show">
          <div class="grid gap-3 sm:grid-cols-2">
            <div class="flex gap-2.5">
              <Cross class="mt-1 shrink-0" />
              <p class="min-w-0 text-[12.5px] leading-relaxed text-ink-muted">
                <span class="font-medium text-ink">A department can have no head.</span>
                <span class="mono text-[12px]">head_user_id</span> is nullable and the department works anyway.
                Being head grants nothing on its own — every check reads the role on the membership row.
              </p>
            </div>
            <div class="flex gap-2.5">
              <Cross class="mt-1 shrink-0" />
              <p class="min-w-0 text-[12.5px] leading-relaxed text-ink-muted">
                <span class="font-medium text-ink">An account can belong to no department at all,</span>
                which is not the same as belonging to an empty one. Both are shown here because both need
                somebody to act.
              </p>
            </div>
          </div>
        </section>

        <p v-if="headless.length" class="mt-5 flex items-start gap-2 text-[12.5px] leading-relaxed text-ink-muted">
          <Cross class="mt-1 shrink-0" />
          <span>
            {{ headless.map((d) => d.name).join(", ") }} {{ headless.length === 1 ? "has" : "have" }} no head.
            Nothing is blocked by that: heads are named by a platform admin, and the person named has to already
            hold <span class="mono text-[12px]">admin</span> in the department.
          </span>
        </p>
      </div>
    </div>

    <Modal
      :open="creating"
      title="New department"
      description="A department is created before anybody is placed in it. Creating and deleting one is platform-admin only."
      :initial-focus="nameField"
      @close="creating = false"
    >
      <div class="space-y-4">
        <label class="block">
          <span :class="[MONO_LABEL, 'text-ink-faint']">Name</span>
          <input
            ref="nameField"
            v-model="newName"
            type="text"
            autocomplete="off"
            placeholder="Engineering"
            :aria-invalid="formError !== null"
            :aria-describedby="formError ? 'dept-error' : undefined"
            :class="[FOCUS, 'mt-1.5 w-full rounded-md bg-sunken px-2.5 py-2 text-[12.5px] text-ink ring-1 ring-inset ring-line placeholder:text-ink-faint']"
            @keydown.enter.prevent="submitCreate"
          />
        </label>
        <p v-if="formError" id="dept-error" role="alert" class="rounded bg-bad-surface px-3 py-2 text-[12px] text-bad">
          {{ formError }}
        </p>
      </div>
      <template #footer>
        <Btn size="sm" variant="secondary" @click="creating = false">Cancel</Btn>
        <Btn size="sm" :busy="create.isPending.value" @click="submitCreate">Create department</Btn>
      </template>
    </Modal>
  </IdentityShell>
</template>
