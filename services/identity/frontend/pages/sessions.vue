<script lang="ts">
/* Identity — Sessions.

   Your own sessions, and nobody else's. GET /me/sessions returns the caller's
   refresh-token families and there is no endpoint that lists another account's, none
   that revokes one family by id, and none that signs anybody else out. What the
   prototype drew on top of that — a person column, a per-row Revoke, a security-event
   feed — is named at the foot of the screen rather than mocked up, because a control
   that cannot work is worse than a missing one.

   One row per family, not per request: the refresh token rotates on every use and the
   old one is blacklisted, so a family is a chain of tokens under a single id. */

/** Mirrors SessionResponse in services/identity/app/schemas/auth.py. Declared here rather
    than in types/api.ts because that file is being edited alongside this one; move it
    across once both landings are in. session_id is a digest of the refresh-family id, so
    it names the row without handing back a value the database stores. */
export interface SessionResponse {
  session_id: string;
  started_at: string;
  last_used_at: string;
  rotations: number;
  expires_at: string;
  is_revoked: boolean;
  is_current: boolean;
}

export type SessionFilter = "active" | "stale" | "all";

/** Idle for three days or more, measured against last_used_at. */
export const IDLE_MS = 3 * 24 * 60 * 60 * 1000;

export function isExpired(session: SessionResponse, now = Date.now()): boolean {
  return new Date(session.expires_at).getTime() <= now;
}

export function isLive(session: SessionResponse, now = Date.now()): boolean {
  return !session.is_revoked && !isExpired(session, now);
}

export function isIdle(session: SessionResponse, now = Date.now()): boolean {
  return now - new Date(session.last_used_at).getTime() >= IDLE_MS;
}

export function sessionState(session: SessionResponse, now = Date.now()): "revoked" | "expired" | "idle" | "refreshing" {
  if (session.is_revoked) return "revoked";
  if (isExpired(session, now)) return "expired";
  if (isIdle(session, now)) return "idle";
  return "refreshing";
}

export function filterSessions(rows: SessionResponse[], filter: SessionFilter, now = Date.now()): SessionResponse[] {
  if (filter === "all") return rows;
  const fresh = (s: SessionResponse) => isLive(s, now) && !isIdle(s, now);
  return rows.filter((s) => (filter === "active" ? fresh(s) : !fresh(s)));
}
</script>

<script setup lang="ts">
import { useMutation, useQuery } from "@tanstack/vue-query";

definePageMeta({ middleware: "auth", layout: false });

const api = useApi();
const auth = useAuth();
const router = useRouter();
const say = useAnnounce();
const config = useRuntimeConfig();

const filter = ref<SessionFilter>("active");
const confirmAll = ref(false);
const now = ref(Date.now());

const sessions = useQuery({
  queryKey: ["me-sessions"],
  queryFn: () => api.request<SessionResponse[]>("/me/sessions"),
});

// The kid is real and published; the rotation history the prototype printed beside it
// was fixture, so it is not here.
const jwks = useQuery({
  queryKey: ["jwks"],
  retry: false,
  queryFn: () =>
    $fetch<{ keys: { kid: string; alg: string }[] }>(`${config.public.identityUrl}/.well-known/jwks.json`),
});

const mine = computed(() => sessions.data.value ?? []);
const live = computed(() => mine.value.filter((s) => isLive(s, now.value)));
const idle = computed(() => live.value.filter((s) => isIdle(s, now.value)));
const rotations = computed(() => mine.value.reduce((sum, s) => sum + s.rotations, 0));
const rows = computed(() => filterSessions(mine.value, filter.value, now.value));

const counts = computed(() => {
  const fresh = mine.value.filter((s) => isLive(s, now.value) && !isIdle(s, now.value)).length;
  return { active: fresh, stale: mine.value.length - fresh, all: mine.value.length };
});

const tabItems = computed(() => [
  { id: "active", label: "Active", hint: String(counts.value.active) },
  { id: "stale", label: "Stale", hint: String(counts.value.stale) },
  { id: "all", label: "All", hint: String(counts.value.all) },
]);

const stats = computed(() => [
  { label: "Live sessions", value: live.value.length, note: "families that can still be refreshed" },
  { label: "Idle over 3 days", value: idle.value.length, note: "still valid, not refreshed recently" },
  { label: "Rotations recorded", value: rotations.value, note: "refreshes across every family you own" },
]);

const signOutError = ref<string | null>(null);

const logoutAll = useMutation({
  mutationFn: () => api.request<void>("/auth/logout-all", { method: "POST" }),
  onSuccess: () => {
    confirmAll.value = false;
    say("Every session revoked. Signing out.");
    auth.logout();
    router.push("/login");
  },
  onError: (err) => {
    signOutError.value = apiMessage(err, "Identity did not accept that. Nothing was revoked.");
  },
});

function expiryLabel(session: SessionResponse): string {
  if (session.is_revoked) return "revoked";
  const ms = new Date(session.expires_at).getTime() - now.value;
  const days = Math.round(Math.abs(ms) / 86_400_000);
  return ms > 0 ? `in ${days}d` : `expired ${days}d ago`;
}

const STATE_TONE = { revoked: "muted", expired: "bad", idle: "warn", refreshing: "ok" } as const;

const ROTATION_NOTES: [string, string][] = [
  [
    "A high count on a live family",
    "You work there every day. Sixty rotations on a family started a week ago is roughly one refresh an hour, all week.",
  ],
  [
    "A low count on an old family",
    "Signed in once and barely came back. Five rotations over three weeks is a session left open, not one being used.",
  ],
  [
    "A count that stops moving",
    "The device was closed, or you stopped working there. The family stays valid until it expires, which is why the idle tile exists.",
  ],
  [
    "A rotation on a token already used",
    "That is theft, not a count. Presenting a blacklisted token kills the whole family and bumps token_version, which signs the account out everywhere.",
  ],
];

const NOT_BUILT: [string, string][] = [
  [
    "Ending one session",
    "There is no revoke-by-id endpoint. POST /auth/logout takes a raw refresh token, which this browser only holds for the session it is in — so the only revocation available from here is all of them.",
  ],
  [
    "Seeing somebody else's sessions",
    "Sessions are read from the caller's own token. An admin view would need GET /platform/users/{id}/sessions, and it does not exist.",
  ],
  [
    "A security event feed",
    "Sign-ins, key rotations and reuse detections are not written to any table, so there is nothing to list. Reuse detection itself is real — the record of it is not.",
  ],
];
</script>

<template>
  <IdentityShell :readout="`${live.length} live`">
    <header class="sec flex flex-wrap items-end justify-between gap-4">
      <div class="min-w-0">
        <Eyebrow>Identity · sessions</Eyebrow>
        <h1 class="mt-3 text-[clamp(1.5rem,2.2vw,1.9rem)] font-semibold leading-[1.05] tracking-[-0.035em]">
          Your sessions
        </h1>
        <p class="mt-1.5 max-w-[72ch] text-[12.5px] leading-relaxed text-ink-muted">
          One row per refresh-token family. The refresh token rotates on every use and the old one is
          blacklisted, so a family is a chain of tokens with a single id — ending the id ends the chain. These
          are the families on your own account; identity publishes no way to read anybody else's.
        </p>
      </div>
      <Btn size="sm" variant="destructive" :disabled="mine.length === 0" @click="signOutError = null; confirmAll = true">
        Sign out everywhere
      </Btn>
    </header>

    <!-- ── tiles ── -->
    <div class="sec mt-5 grid grid-cols-1 gap-3 border-t border-line-subtle pt-4 sm:grid-cols-3" style="animation-delay: 40ms">
      <div v-for="s in stats" :key="s.label" class="rounded-md bg-surface/40 px-4 py-3.5 ring-1 ring-inset ring-line-subtle">
        <p class="mono text-[11px] uppercase tracking-[0.08em] text-ink-faint">{{ s.label }}</p>
        <p class="mono mt-2 text-[28px] font-medium leading-none tracking-[-0.02em] text-ink">
          <template v-if="sessions.isPending.value">—</template>
          <template v-else>{{ s.value }}</template>
        </p>
        <p class="mt-2.5 text-[11px] text-ink-faint">{{ s.note }}</p>
      </div>
    </div>

    <!-- ── the gap, said out loud ── -->
    <div
      class="sec mt-3 flex flex-wrap items-start gap-3 rounded-md bg-sunken px-4 py-3 ring-1 ring-inset ring-line-subtle"
      style="animation-delay: 80ms"
    >
      <span class="mt-0.5 shrink-0 text-ink-faint"><Icon name="alert" /></span>
      <p class="min-w-0 flex-1 text-[12px] leading-relaxed text-ink-muted">
        <span class="font-medium text-ink">No device and no location, because neither is recorded.</span>
        The <span class="mono text-[11px]">refresh_tokens</span> table has no user-agent column and no IP column,
        so “Chrome on Windows, Port Harcourt” could only be guessed. What is real is the family id, when it
        started, when it last refreshed and how many times it has rotated — which is enough to tell a working
        session from an abandoned one. Adding device and location is a migration plus a change to token
        issuance, not a frontend change.
      </p>
    </div>

    <div class="mt-6 grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,320px)]">
      <!-- ── sessions ── -->
      <div class="sec min-w-0" style="animation-delay: 80ms">
        <Tabs
          id="sessions"
          :model-value="filter"
          label="Filter sessions"
          :items="tabItems"
          @update:model-value="filter = $event as SessionFilter"
        >
          <span class="mono text-[11px] uppercase tracking-[0.08em] text-ink-faint">refresh families</span>
        </Tabs>

        <div v-if="sessions.isPending.value" class="mt-4 space-y-2" role="status">
          <span class="sr-only">Loading your sessions</span>
          <span v-for="i in 3" :key="i" class="block h-12 rounded-md bg-surface/40 ring-1 ring-inset ring-line-subtle" aria-hidden="true" />
        </div>

        <div v-else-if="sessions.isError.value" role="alert" class="mt-4 rounded-md bg-bad-surface px-4 py-3.5">
          <p class="text-[13px] font-medium text-ink">Your sessions did not load.</p>
          <p class="mt-1 max-w-[60ch] text-[12.5px] leading-relaxed text-ink-muted">
            {{ apiMessage(sessions.error.value, "Identity did not answer.") }}
          </p>
          <div class="mt-3">
            <Btn size="sm" variant="secondary" @click="sessions.refetch()">Try again</Btn>
          </div>
        </div>

        <!-- `relative` is load-bearing: the sr-only caption is position:absolute, and with
             no positioned ancestor it resolves against the page and stretches the document
             to the width of the table. -->
        <div v-else class="relative mt-4 overflow-x-auto rounded-md bg-surface/40 ring-1 ring-inset ring-line-subtle">
          <table class="w-full min-w-[520px] border-collapse">
            <caption class="sr-only">Your refresh-token families</caption>
            <thead>
              <tr class="border-b border-line-subtle">
                <th scope="col" class="px-3 py-2.5 text-left text-[11px] font-medium uppercase tracking-[0.08em] text-ink-faint">Family</th>
                <th scope="col" class="px-3 py-2.5 text-left text-[11px] font-medium uppercase tracking-[0.08em] text-ink-faint">Started</th>
                <th scope="col" class="px-3 py-2.5 text-left text-[11px] font-medium uppercase tracking-[0.08em] text-ink-faint">Last refreshed</th>
                <th scope="col" class="px-3 py-2.5 text-right text-[11px] font-medium uppercase tracking-[0.08em] text-ink-faint">Rotations</th>
                <th scope="col" class="px-3 py-2.5 text-left text-[11px] font-medium uppercase tracking-[0.08em] text-ink-faint">Expiry</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(s, i) in rows"
                :key="s.session_id"
                :class="[
                  'sec border-b border-line-subtle/70 transition-colors last:border-0 hover:bg-surface-hover/50',
                  s.is_revoked && 'opacity-60',
                ]"
                :style="{ animationDelay: `${Math.min(i, 3) * 40}ms` }"
              >
                <td class="px-3 py-2.5">
                  <p class="flex flex-wrap items-center gap-2">
                    <span class="mono text-[12.5px] text-ink-muted">{{ s.session_id }}</span>
                    <span
                      v-if="s.is_current"
                      class="mono shrink-0 rounded bg-sunken px-1 py-px text-[11px] uppercase tracking-[0.08em] text-ink-muted"
                    >this device</span>
                  </p>
                </td>
                <td class="mono px-3 py-2.5 text-[11px] text-ink-muted">{{ formatDateTime(s.started_at) }}</td>
                <td class="px-3 py-2.5">
                  <span class="mono block text-[12.5px] text-ink">{{ formatDateTime(s.last_used_at) }}</span>
                  <StatusDot :tone="STATE_TONE[sessionState(s, now)]" quiet>{{ sessionState(s, now) }}</StatusDot>
                </td>
                <td class="mono px-3 py-2.5 text-right text-[12.5px] text-ink-muted">{{ s.rotations }}</td>
                <td class="mono px-3 py-2.5 text-[11px] text-ink-muted">{{ expiryLabel(s) }}</td>
              </tr>
            </tbody>
          </table>

          <div v-if="rows.length === 0" class="px-6 py-14 text-center">
            <p class="text-[13.5px] font-medium text-ink">
              {{ filter === "active" ? "No session is live" : filter === "stale" ? "Nothing stale" : "No session recorded" }}
            </p>
            <p class="mx-auto mt-1.5 max-w-[52ch] text-[12.5px] leading-relaxed text-ink-muted">
              <template v-if="filter === 'active'">
                Every family has been revoked or has expired. The next sign-in starts a new one.
              </template>
              <template v-else-if="filter === 'stale'">Every family here is being refreshed normally.</template>
              <template v-else>
                Nothing is stored for this account yet. A family is created by a sign-in, so this fills the next
                time you sign in.
              </template>
            </p>
            <div v-if="filter !== 'all'" class="mt-4 flex justify-center">
              <Btn size="sm" variant="secondary" @click="filter = 'all'">Show all families</Btn>
            </div>
          </div>
        </div>

        <p class="mt-3 text-[11px] leading-relaxed text-ink-faint">
          Access tokens are not listed. They live about fifteen minutes and are never stored, so there is nothing
          to revoke — cutting the family is what stops the next one being issued.
        </p>
      </div>

      <!-- ── rail ── -->
      <div class="sec min-w-0 space-y-5" style="animation-delay: 120ms">
        <section aria-label="What a rotation count tells you">
          <div class="flex items-center gap-2">
            <Cross />
            <Eyebrow>What a rotation count tells you</Eyebrow>
          </div>
          <dl class="mt-2.5 divide-y divide-line-subtle">
            <div v-for="[term, body] in ROTATION_NOTES" :key="term" class="py-2 first:pt-0 last:pb-0">
              <dt class="text-[12.5px] font-medium text-ink-muted">{{ term }}</dt>
              <dd class="mt-0.5 text-[12.5px] leading-relaxed text-ink-muted">{{ body }}</dd>
            </div>
          </dl>
          <p v-if="jwks.data.value?.keys?.length" class="mono mt-2.5 text-[11px] leading-relaxed text-ink-muted">
            signing key {{ jwks.data.value.keys[0]!.kid }} · {{ jwks.data.value.keys[0]!.alg }} · public keys
            published at /.well-known/jwks.json
          </p>
          <p v-else class="mono mt-2.5 text-[11px] leading-relaxed text-ink-muted">
            public keys published at /.well-known/jwks.json
          </p>
        </section>

        <!-- Marked as unbuilt on purpose. A security review should be able to see what
             this console can and cannot do without reading the API. -->
        <section aria-label="Not built yet" class="border-t border-line-strong pt-3">
          <h2 class="mono text-[11px] uppercase tracking-[0.08em] text-ink-faint">Not built yet</h2>
          <p class="mt-2 text-[12.5px] leading-relaxed text-ink-muted">
            Three things a security review usually asks for do not exist behind this screen. They are named here
            rather than mocked up, because a control that cannot work is worse than a missing one.
          </p>
          <ul class="mt-2.5 divide-y divide-line-subtle">
            <li v-for="[term, body] in NOT_BUILT" :key="term" class="py-2 first:pt-0 last:pb-0">
              <p class="text-[12.5px] font-medium text-ink-muted">{{ term }}</p>
              <p class="mt-0.5 text-[12.5px] leading-relaxed text-ink-muted">{{ body }}</p>
            </li>
          </ul>
        </section>
      </div>
    </div>

    <!-- ── sign out everywhere ── -->
    <Modal
      :open="confirmAll"
      title="Sign out everywhere?"
      description="Every family on your account, including the one you are reading this on."
      :close-on-backdrop="false"
      @close="confirmAll = false"
    >
      <div class="space-y-3">
        <div class="flex items-start gap-2.5 rounded-md bg-bad-surface px-3 py-2.5">
          <span class="mt-0.5 shrink-0 text-bad"><Icon name="alert" class="h-3.5 w-3.5" /></span>
          <p class="text-[12px] leading-relaxed text-ink">
            <span class="font-medium">This signs you out here too.</span>
            <span class="text-ink-muted">
              It bumps <span class="mono text-[11px]">token_version</span>, which invalidates every refresh token
              issued to you before now. Nothing is deleted and your password does not change.
            </span>
          </p>
        </div>
        <p class="text-[12px] leading-relaxed text-ink-muted">
          Worth doing if a device is lost or a token turns up where it should not be. It is not worth doing to
          tidy up idle sessions — those expire on their own. Access tokens already issued keep working until they
          expire, which is under fifteen minutes.
        </p>
        <p v-if="signOutError" role="alert" class="rounded bg-bad-surface px-3 py-2 text-[12px] text-bad">
          {{ signOutError }}
        </p>
      </div>
      <template #footer>
        <Btn size="sm" variant="secondary" @click="confirmAll = false">Cancel</Btn>
        <Btn size="sm" variant="destructive" :busy="logoutAll.isPending.value" @click="logoutAll.mutate()">
          Sign out of {{ live.length }} {{ live.length === 1 ? "session" : "sessions" }}
        </Btn>
      </template>
    </Modal>
  </IdentityShell>
</template>
