<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { FOCUS, MONO_LABEL } from "@crescent/ui/utils/ui";
import type { IconName, Tone } from "@crescent/ui/types/ui";
import type { DepartmentResponse, Page, PlatformUserListResponse, UserMeResponse } from "~/types/api";

/* The picker you land on after signing in. One token, three doors.

   The card itself is the control: Tab reaches it once, Enter opens it, and the "Open"
   line inside is a label rather than a second tab stop competing with its container. */

definePageMeta({ layout: false, middleware: "require-auth" });

const auth = useAuth();
const api = useApi();
const config = useRuntimeConfig();
const signOut = useSignOut();
const { label: signingKey } = useSigningKey();

const me = computed(() => auth.user.value as UserMeResponse | null);
const isPlatformAdmin = computed(() => me.value?.is_platform_admin === true);
const displayName = computed(() => (me.value ? fullName(me.value.first_name, me.value.last_name, me.value.email) : ""));
const membership = computed(() => me.value?.memberships?.[0] ?? null);

// The identity card is a console, not a product: offering it to someone whose every
// control inside is a 403 is offering a door into a locked room. Department admins get it
// because /departments is theirs to administer.
const canOpenIdentity = computed(() => isPlatformAdmin.value || (me.value?.memberships ?? []).some((m) => m.role === "admin"));

/* Every figure below is a live read. A figure that cannot be fetched is dropped rather
   than shown as zero — on this screen a zero and a failure look identical, and one of
   them is a lie. Pulse and Forge are separate origins, so those two calls fail quietly
   until their CORS lists include this app. */
const departments = useQuery({
  queryKey: ["departments"],
  queryFn: () => api.request<DepartmentResponse[]>("/departments"),
  retry: false,
});

const people = useQuery({
  queryKey: ["platform-users", "count"],
  enabled: isPlatformAdmin,
  queryFn: () => api.request<PlatformUserListResponse>("/platform/users", { query: { limit: 1 } }),
  retry: false,
});

const sessions = useQuery({
  queryKey: ["me", "sessions"],
  queryFn: () => api.request<{ is_revoked: boolean; expires_at: string }[]>("/me/sessions"),
  retry: false,
});

const liveSessions = computed(() => {
  const rows = sessions.data.value;
  if (!rows) return null;
  return rows.filter((s) => !s.is_revoked && new Date(s.expires_at).getTime() > Date.now()).length;
});

// The identity-issued token is the same token the products verify, so a summary read is
// just a normal authenticated call to another origin.
function productHeaders(): Record<string, string> {
  return auth.accessToken.value ? { Authorization: `Bearer ${auth.accessToken.value}` } : {};
}

const pulseReports = useQuery({
  queryKey: ["pulse", "reports", "count"],
  retry: false,
  queryFn: () =>
    $fetch<Page<unknown>>(`${config.public.pulseApiUrl}/reports`, { query: { limit: 1 }, headers: productHeaders() }),
});

const pulseQueue = useQuery({
  queryKey: ["pulse", "review-queue", "count"],
  retry: false,
  queryFn: () =>
    $fetch<Page<unknown>>(`${config.public.pulseApiUrl}/reports/review-queue`, { query: { limit: 1 }, headers: productHeaders() }),
});

const forgeDatasets = useQuery({
  queryKey: ["forge", "datasets", "summary"],
  retry: false,
  queryFn: () =>
    $fetch<{ owned_count: number; sample_count: number }>(`${config.public.forgeApiUrl}/datasets/summary`, {
      query: { recent: 0 },
      headers: productHeaders(),
    }),
});

function plural(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`;
}

const pulseStat = computed(() => {
  const parts: string[] = [];
  if (pulseReports.data.value) parts.push(plural(pulseReports.data.value.total, "report"));
  if (pulseQueue.data.value) parts.push(`${pulseQueue.data.value.total} awaiting your review`);
  return parts.length ? parts.join(" · ") : null;
});

const forgeStat = computed(() => {
  const summary = forgeDatasets.data.value;
  if (!summary) return null;
  return `${plural(summary.owned_count, "dataset")} · ${summary.sample_count} shared`;
});

const identityStat = computed(() => {
  const parts: string[] = [];
  if (people.data.value) parts.push(plural(people.data.value.total, "person", "people"));
  if (departments.data.value) parts.push(plural(departments.data.value.length, "department"));
  if (liveSessions.value !== null) parts.push(`${liveSessions.value} live sessions`);
  return parts.length ? parts.join(" · ") : null;
});

interface Door {
  key: string;
  name: string;
  tag: string;
  icon: IconName;
  to: string;
  external: boolean;
  line: string;
  points: string[];
  stat: string | null;
  status: string;
  tone: Tone;
}

// Cross-product links go through the product's own SSO relay rather than straight at its
// front page: the relay asks identity for a token for that origin, and falls back to a
// plain landing when the product has no SSO config yet. See packages/ui/composables/useSSO.
function relay(base: string): string {
  return `${base}/auth/callback?start=1&next=${encodeURIComponent("/")}`;
}

const doors = computed<Door[]>(() => {
  const all: Door[] = [
    {
      key: "pulse",
      name: "Pulse",
      tag: "Engineering performance & reporting",
      icon: "pulse",
      to: relay(config.public.pulseUrl as string),
      external: true,
      line: "Weekly reports drafted from what your repositories actually did, then routed to a lead for approval.",
      points: [
        "Commits, pull requests, reviews and issues in one window",
        "AI drafts you edit, own and submit",
        "Approval decisions kept on the record",
      ],
      stat: pulseStat.value,
      status: "Live",
      tone: "ok",
    },
    {
      key: "forge",
      name: "Forge",
      tag: "No-code AI/ML workspace",
      icon: "layers",
      to: relay(config.public.forgeUrl as string),
      external: true,
      line: "Upload a dataset, build a workflow step by step, and see every step instead of one Run button.",
      points: ["CSV upload with an instant schema preview", "Guided classification and forecasting", "Canvas that maps to real Python"],
      stat: forgeStat.value,
      status: "Live · limited",
      tone: "warn",
    },
  ];

  if (canOpenIdentity.value) {
    all.push({
      key: "identity",
      name: "Identity",
      tag: "Accounts, departments and access",
      icon: "shield",
      to: "/departments",
      external: false,
      line: "The system of record for who someone is and what they may do. Every other product reads it by id.",
      points: ["People, departments, teams and memberships", "Roles, and what each one actually unlocks", "Your own sessions and revocation"],
      stat: identityStat.value,
      status: isPlatformAdmin.value ? "Console · platform admin" : "Console · department admin",
      tone: "info",
    });
  }
  return all;
});

const readout = computed(() => `${doors.value.length} doors · one token`);

useHead({ title: "Products" });
</script>

<template>
  <div class="w-full overflow-x-hidden">
    <TopBar signed-in show-sign-out home-to="/products" :user-name="displayName" account-to="/account" @sign-out="signOut" />
    <RulerStrip :readout="readout" />

    <main id="main" class="relative mx-auto w-full max-w-[1200px] px-5 sm:px-8">
      <div class="relative border-line-subtle py-12 lg:pr-14">
        <div class="sec flex flex-wrap items-center gap-3">
          <Eyebrow>Signed in</Eyebrow>
          <span class="rule-draw h-px w-8 bg-line" style="animation-delay: 160ms" aria-hidden="true" />
          <StatusDot tone="ok">Session active</StatusDot>
        </div>

        <h1
          class="sec mt-6 max-w-[18ch] text-[clamp(2rem,4.6vw,3.2rem)] font-semibold leading-[0.98] tracking-[-0.04em]"
          style="animation-delay: 40ms"
        >
          Where do you want<br />
          <span class="text-ink-muted">to work today?</span>
        </h1>

        <div v-if="me" class="sec mt-7 flex flex-wrap items-baseline gap-x-3 gap-y-1.5" style="animation-delay: 80ms">
          <span class="mono text-[12px] text-ink-muted">{{ displayName }}</span>
          <span class="text-ink-faint" aria-hidden="true">·</span>
          <span class="mono text-[12px] text-ink-muted">{{ membership?.dept_name ?? "Unplaced" }}</span>
          <span class="text-ink-faint" aria-hidden="true">·</span>
          <span class="mono text-[12px] text-ink-muted">{{ isPlatformAdmin ? "platform admin" : membership?.role ?? "no role yet" }}</span>
          <span class="text-ink-faint" aria-hidden="true">·</span>
          <span class="mono text-[12px] text-ink-muted">user_id {{ me.id }}</span>
        </div>

        <p class="sec mt-5 max-w-[52ch] text-[13.5px] leading-relaxed text-ink-muted" style="animation-delay: 100ms">
          The same access token opens all of them. Nothing here keeps its own copy of you — the products ask identity by id,
          and stop asking the moment the session is revoked.
        </p>
      </div>

      <!-- the doors, on the same hairline grid as the landing -->
      <div class="grid border-t border-line-subtle md:grid-cols-2">
        <article
          v-for="(door, i) in doors"
          :key="door.key"
          :class="['sec group/door relative border-b border-line-subtle', i % 2 === 1 ? 'md:border-l' : '']"
          :style="{ animationDelay: `${140 + i * 60}ms` }"
        >
          <Cross class="absolute -bottom-[5px] -right-[5px] hidden md:block" />
          <NuxtLink
            :to="door.to"
            :external="door.external"
            :aria-label="`Open ${door.name} — ${door.tag}`"
            :class="[
              FOCUS,
              'flex h-full w-full flex-col items-start px-0 py-7 text-left transition-colors hover:bg-surface-hover/40',
              i % 2 === 1 ? 'md:pl-10' : 'md:pr-10',
            ]"
          >
            <div class="flex w-full items-start justify-between gap-4">
              <div class="flex items-center gap-3">
                <span class="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-sunken text-ink-muted ring-1 ring-inset ring-line-subtle transition-colors group-hover/door:text-ink">
                  <Icon :name="door.icon" class="h-4 w-4" />
                </span>
                <div>
                  <h2 class="text-[17px] font-semibold tracking-tight">{{ door.name }}</h2>
                  <p :class="[MONO_LABEL, 'text-ink-faint']">{{ door.tag }}</p>
                </div>
              </div>
              <StatusDot :tone="door.tone" class="shrink-0 whitespace-nowrap">{{ door.status }}</StatusDot>
            </div>

            <p class="mt-5 max-w-[46ch] text-[13.5px] leading-relaxed text-ink-muted">{{ door.line }}</p>

            <ul class="mt-5 w-full space-y-2">
              <li v-for="point in door.points" :key="point" class="flex items-start gap-2.5 text-[12.5px] text-ink-muted">
                <span class="mt-[7px] h-px w-2.5 shrink-0 bg-line-strong" aria-hidden="true" />
                {{ point }}
              </li>
            </ul>

            <!-- Dropped entirely when the figure cannot be read: a zero here is
                 indistinguishable from a failure. -->
            <p v-if="door.stat" :class="[MONO_LABEL, 'mt-6 w-full border-t border-line-subtle pt-3 text-ink-muted']">{{ door.stat }}</p>

            <span
              class="mt-5 inline-flex items-center gap-2 rounded-md bg-ink px-4 py-2.5 text-[13.5px] font-medium text-app transition-[filter] duration-100 ease-out group-hover/door:brightness-90"
            >
              Open {{ door.name }}
              <Icon name="arrow" class="h-4 w-4 transition-transform group-hover/door:translate-x-0.5" />
            </span>
          </NuxtLink>
        </article>

        <!-- the placeholder from the landing diagram, kept as a promise -->
        <div class="relative border-b border-line-subtle md:border-l">
          <div class="h-full py-7 md:pl-10">
            <div class="flex h-full w-full flex-col items-start gap-3 rounded-md border border-dashed border-line-subtle px-5 py-8">
              <span class="grid h-9 w-9 place-items-center rounded-md border border-dashed border-line-subtle text-ink-faint">
                <Icon name="plus" class="h-4 w-4" />
              </span>
              <p class="text-[14px] font-medium tracking-tight text-ink-muted">Next product</p>
              <p class="max-w-[38ch] text-[12.5px] leading-relaxed text-ink-muted">
                Adding one means trusting the same signing key. It does not mean migrating a single user.
              </p>
              <span :class="[MONO_LABEL, 'mt-1 text-ink-faint']">reserved</span>
            </div>
          </div>
        </div>
      </div>

      <div class="flex flex-wrap items-center justify-between gap-4 py-7">
        <!-- The key id is there to be compared against what JWKS publishes, so it reads as a
             value; `access 15 min` is a unit string and stays chrome. -->
        <p v-if="signingKey" :class="[MONO_LABEL, 'text-ink-faint']">
          <span class="text-ink-muted">{{ signingKey }}</span> · access 15 min
        </p>
        <NuxtLink to="/account" :class="[FOCUS, MONO_LABEL, 'rounded text-ink-muted transition-colors hover:text-ink']">
          Your account
        </NuxtLink>
      </div>
    </main>
  </div>
</template>
