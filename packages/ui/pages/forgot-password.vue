<script setup lang="ts">
definePageMeta({ layout: false });

const config = useRuntimeConfig();

const email = ref("");
const errorMessage = ref<string | null>(null);
const sent = ref(false);
const submitting = ref(false);

function serverDetail(err: unknown): string | null {
  const detail = (err as { data?: { detail?: unknown } })?.data?.detail;
  return typeof detail === "string" ? detail : null;
}

async function onSubmit() {
  errorMessage.value = null;
  const address = email.value.trim();
  if (!address.includes("@")) {
    errorMessage.value = "Enter a valid email address.";
    return;
  }

  submitting.value = true;
  try {
    await $fetch(`${config.public.identityUrl}/auth/forgot-password`, {
      method: "POST",
      body: { email: address },
    });
    sent.value = true;
  } catch (err: unknown) {
    const status = (err as { statusCode?: number; status?: number })?.statusCode
      ?? (err as { status?: number })?.status;
    if (status === 503) {
      // Server-wide email misconfiguration — same answer for every address, so
      // showing it still says nothing about whether this one has an account.
      errorMessage.value = serverDetail(err) ?? "Password reset email isn't configured on the server yet.";
    } else if (status === 429) {
      errorMessage.value = "Too many requests. Wait a minute and try again.";
    } else if (status === 422) {
      errorMessage.value = "Enter a valid email address.";
    } else {
      errorMessage.value = "Could not send the reset link. Is the identity service running?";
    }
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-gray-50 px-4 py-10">
    <div class="w-full max-w-sm rounded-lg border border-gray-200 bg-white p-8 shadow-sm">
      <template v-if="sent">
        <h1 class="mb-1 text-xl font-semibold">Check your email</h1>
        <!-- Deliberately does not say whether that address has an account. -->
        <p class="mb-6 text-sm text-gray-500">
          If an account exists for that address, a reset link is on its way. It expires
          shortly, so use it soon. Check spam if you don't see it.
        </p>
        <NuxtLink
          to="/login"
          class="block w-full rounded-md bg-gray-900 px-3 py-2 text-center text-sm font-medium text-white hover:bg-gray-800"
        >
          Back to sign in
        </NuxtLink>
      </template>

      <template v-else>
        <h1 class="mb-1 text-xl font-semibold">Reset your password</h1>
        <p class="mb-6 text-sm text-gray-500">
          Enter your work email and we'll send you a link to choose a new password.
        </p>

        <form class="space-y-4" @submit.prevent="onSubmit">
          <div>
            <label for="email" class="mb-1 block text-sm font-medium">Email</label>
            <input
              id="email"
              v-model="email"
              type="email"
              autocomplete="email"
              class="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-gray-500 focus:outline-none"
              placeholder="you@cyphercrescent.com"
            />
          </div>

          <p v-if="errorMessage" class="text-sm text-red-600">{{ errorMessage }}</p>

          <button
            type="submit"
            :disabled="submitting"
            class="w-full rounded-md bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-60"
          >
            {{ submitting ? "Sending…" : "Send reset link" }}
          </button>
        </form>

        <p class="mt-6 text-sm text-gray-500">
          Remembered it?
          <NuxtLink to="/login" class="font-medium text-gray-900 hover:underline">Sign in</NuxtLink>
        </p>
      </template>
    </div>
  </div>
</template>
