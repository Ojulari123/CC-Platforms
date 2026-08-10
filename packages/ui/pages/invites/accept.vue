<script setup lang="ts">
import type { InvitePreview, TokenPair } from "../../types/api";

definePageMeta({ layout: false });

const config = useRuntimeConfig();
const route = useRoute();
const router = useRouter();
const auth = useAuth();

const token = ref(typeof route.query.token === "string" ? route.query.token : "");

const preview = ref<InvitePreview | null>(null);
const loading = ref(true);
// Terminal state: invalid, expired, already accepted — retrying can't fix it.
const deadReason = ref<string | null>(null);

const firstName = ref("");
const lastName = ref("");
const password = ref("");
const { rules, valid } = usePasswordRules(password);

const errorMessage = ref<string | null>(null);
const submitting = ref(false);

const placement = computed(() => {
  const p = preview.value;
  if (!p) return "";
  return p.team_name ? `${p.dept_name} — ${p.team_name}` : p.dept_name;
});

function serverDetail(err: unknown): string | null {
  const detail = (err as { data?: { detail?: unknown } })?.data?.detail;
  return typeof detail === "string" ? detail : null;
}

function statusOf(err: unknown): number | undefined {
  return (err as { statusCode?: number; status?: number })?.statusCode
    ?? (err as { status?: number })?.status;
}

onMounted(async () => {
  if (!token.value) {
    deadReason.value = "This invite link is missing its token — open the link from the email itself.";
    loading.value = false;
    return;
  }
  try {
    preview.value = await $fetch<InvitePreview>(`${config.public.identityUrl}/invites/preview`, {
      query: { token: token.value },
    });
  } catch (err: unknown) {
    deadReason.value = statusOf(err) === 400
      ? serverDetail(err) ?? "This invitation is no longer valid."
      : "Could not check this invitation. Is the identity service running?";
  } finally {
    loading.value = false;
  }
});

async function onAccept() {
  errorMessage.value = null;
  if (preview.value?.needs_account) {
    if (!firstName.value.trim() || !lastName.value.trim()) {
      errorMessage.value = "Enter your first and last name.";
      return;
    }
    if (!valid.value) {
      errorMessage.value = "That password doesn't meet the requirements yet.";
      return;
    }
  }

  submitting.value = true;
  try {
    const pair = await $fetch<TokenPair>(`${config.public.identityUrl}/invites/accept`, {
      method: "POST",
      body: preview.value?.needs_account
        ? {
            token: token.value,
            first_name: firstName.value.trim(),
            last_name: lastName.value.trim(),
            password: password.value,
          }
        : { token: token.value },
    });
    token.value = "";
    password.value = "";
    await auth.adoptSession(pair);
    // replace, not push: the entry holding the token leaves the history too.
    await router.replace("/");
  } catch (err: unknown) {
    const status = statusOf(err);
    const detail = serverDetail(err);
    if (status === 400 && detail && /password/i.test(detail)) {
      errorMessage.value = detail;
    } else if (status === 400) {
      deadReason.value = detail ?? "This invitation is no longer valid.";
    } else if (status === 409 || status === 403) {
      deadReason.value = detail ?? "This invitation can't be accepted.";
    } else if (status === 422) {
      errorMessage.value = "Check the details above and try again.";
    } else if (status === 429) {
      errorMessage.value = "Too many attempts. Wait a minute and try again.";
    } else {
      errorMessage.value = "Could not accept the invitation. Is the identity service running?";
    }
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-gray-50 px-4 py-10">
    <div class="w-full max-w-sm rounded-lg border border-gray-200 bg-white p-8 shadow-sm">
      <p v-if="loading" class="text-sm text-gray-500">Checking your invitation…</p>

      <template v-else-if="deadReason">
        <h1 class="mb-1 text-xl font-semibold">This invitation won't work</h1>
        <p class="mb-6 text-sm text-gray-500">{{ deadReason }}</p>
        <NuxtLink
          to="/login"
          class="block w-full rounded-md bg-gray-900 px-3 py-2 text-center text-sm font-medium text-white hover:bg-gray-800"
        >
          Go to sign in
        </NuxtLink>
      </template>

      <template v-else-if="preview">
        <h1 class="mb-1 text-xl font-semibold">Join {{ placement }}</h1>
        <p class="mb-6 text-sm text-gray-500">
          <strong>{{ preview.email }}</strong> has been invited as
          <strong>{{ preview.role }}</strong>.
          <span v-if="!preview.needs_account">
            This joins the department with the account you already have.
          </span>
        </p>

        <form class="space-y-4" @submit.prevent="onAccept">
          <template v-if="preview.needs_account">
            <div class="flex gap-3">
              <div class="flex-1">
                <label for="first-name" class="mb-1 block text-sm font-medium">First name</label>
                <input
                  id="first-name"
                  v-model="firstName"
                  type="text"
                  autocomplete="given-name"
                  class="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-gray-500 focus:outline-none"
                />
              </div>
              <div class="flex-1">
                <label for="last-name" class="mb-1 block text-sm font-medium">Last name</label>
                <input
                  id="last-name"
                  v-model="lastName"
                  type="text"
                  autocomplete="family-name"
                  class="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-gray-500 focus:outline-none"
                />
              </div>
            </div>

            <div>
              <label for="password" class="mb-1 block text-sm font-medium">Password</label>
              <input
                id="password"
                v-model="password"
                type="password"
                autocomplete="new-password"
                class="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-gray-500 focus:outline-none"
                placeholder="••••••••"
              />
              <ul class="mt-2 space-y-0.5">
                <li
                  v-for="rule in rules"
                  :key="rule.label"
                  class="flex items-center gap-1.5 text-xs"
                  :class="rule.met ? 'text-green-600' : 'text-gray-500'"
                >
                  <span aria-hidden="true">{{ rule.met ? "✓" : "•" }}</span>
                  {{ rule.label }}
                </li>
              </ul>
            </div>
          </template>

          <p v-if="errorMessage" class="text-sm text-red-600">{{ errorMessage }}</p>

          <button
            type="submit"
            :disabled="submitting"
            class="w-full rounded-md bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-60"
          >
            {{ submitting ? "Joining…" : preview.needs_account ? "Create account and join" : "Accept invitation" }}
          </button>
        </form>
      </template>
    </div>
  </div>
</template>
