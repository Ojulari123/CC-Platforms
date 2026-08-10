<script setup lang="ts">
definePageMeta({ layout: false });

const config = useRuntimeConfig();
const route = useRoute();
const router = useRouter();

const token = ref(typeof route.query.token === "string" ? route.query.token : "");

const password = ref("");
const confirmPassword = ref("");
const { rules, valid } = usePasswordRules(password);

const errorMessage = ref<string | null>(null);
// Terminal states: the link itself is unusable, so no amount of retrying helps.
const linkDead = ref(!token.value);
const done = ref(false);
const submitting = ref(false);

function serverDetail(err: unknown): string | null {
  const detail = (err as { data?: { detail?: unknown } })?.data?.detail;
  return typeof detail === "string" ? detail : null;
}

async function onSubmit() {
  errorMessage.value = null;
  if (!valid.value) {
    errorMessage.value = "That password doesn't meet the requirements yet.";
    return;
  }
  if (password.value !== confirmPassword.value) {
    errorMessage.value = "The two passwords don't match.";
    return;
  }

  submitting.value = true;
  try {
    await $fetch(`${config.public.identityUrl}/auth/reset-password`, {
      method: "POST",
      body: { token: token.value, new_password: password.value },
    });
    token.value = "";
    password.value = "";
    confirmPassword.value = "";
    done.value = true;
    // Drop the token from the address bar and this history entry once it's spent.
    router.replace({ query: {} });
  } catch (err: unknown) {
    const status = (err as { statusCode?: number; status?: number })?.statusCode
      ?? (err as { status?: number })?.status;
    const detail = serverDetail(err);
    if (status === 400 && detail && /password/i.test(detail)) {
      errorMessage.value = detail;
    } else if (status === 400) {
      // Invalid, already-used or expired link — identity words each one itself.
      linkDead.value = true;
      errorMessage.value = detail ?? "This reset link is no longer valid.";
    } else if (status === 422) {
      errorMessage.value = "Password must be between 8 and 72 characters.";
    } else if (status === 429) {
      errorMessage.value = "Too many attempts. Wait a minute and try again.";
    } else {
      errorMessage.value = "Could not reset your password. Is the identity service running?";
    }
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-gray-50 px-4 py-10">
    <div class="w-full max-w-sm rounded-lg border border-gray-200 bg-white p-8 shadow-sm">
      <template v-if="done">
        <h1 class="mb-1 text-xl font-semibold">Password changed</h1>
        <p class="mb-6 text-sm text-gray-500">
          You've been signed out everywhere else. Sign in with your new password.
        </p>
        <NuxtLink
          to="/login"
          class="block w-full rounded-md bg-gray-900 px-3 py-2 text-center text-sm font-medium text-white hover:bg-gray-800"
        >
          Sign in
        </NuxtLink>
      </template>

      <template v-else-if="linkDead">
        <h1 class="mb-1 text-xl font-semibold">This link won't work</h1>
        <p class="mb-6 text-sm text-gray-500">
          {{ errorMessage ?? "This reset link is missing its token — open the link from the email itself." }}
        </p>
        <NuxtLink
          to="/forgot-password"
          class="block w-full rounded-md bg-gray-900 px-3 py-2 text-center text-sm font-medium text-white hover:bg-gray-800"
        >
          Request a new link
        </NuxtLink>
      </template>

      <template v-else>
        <h1 class="mb-1 text-xl font-semibold">Choose a new password</h1>
        <p class="mb-6 text-sm text-gray-500">
          This link works once. Setting a new password signs you out on every device.
        </p>

        <form class="space-y-4" @submit.prevent="onSubmit">
          <div>
            <label for="password" class="mb-1 block text-sm font-medium">New password</label>
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

          <div>
            <label for="confirm-password" class="mb-1 block text-sm font-medium">
              Confirm new password
            </label>
            <input
              id="confirm-password"
              v-model="confirmPassword"
              type="password"
              autocomplete="new-password"
              class="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-gray-500 focus:outline-none"
              placeholder="••••••••"
            />
          </div>

          <p v-if="errorMessage" class="text-sm text-red-600">{{ errorMessage }}</p>

          <button
            type="submit"
            :disabled="submitting"
            class="w-full rounded-md bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-60"
          >
            {{ submitting ? "Saving…" : "Set new password" }}
          </button>
        </form>
      </template>
    </div>
  </div>
</template>
