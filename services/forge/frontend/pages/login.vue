<script setup lang="ts">
import { z } from "zod";

definePageMeta({ layout: false });

const auth = useAuth();
const router = useRouter();

const loginSchema = z.object({
  email: z.string().email("Enter a valid email address"),
  password: z.string().min(1, "Password is required"),
});

const email = ref("");
const password = ref("");
const errorMessage = ref<string | null>(null);
const submitting = ref(false);

onMounted(() => {
  auth.hydrate();
  if (auth.isAuthenticated.value) {
    router.replace("/");
  }
});

async function onSubmit() {
  errorMessage.value = null;
  const parsed = loginSchema.safeParse({
    email: email.value,
    password: password.value,
  });
  if (!parsed.success) {
    errorMessage.value = parsed.error.issues[0]?.message ?? "Invalid input";
    return;
  }

  submitting.value = true;
  try {
    await auth.login(parsed.data.email, parsed.data.password);
    await router.push("/");
  } catch (err: unknown) {
    const status = (err as { statusCode?: number })?.statusCode;
    errorMessage.value =
      status === 401
        ? "Incorrect email or password."
        : "Could not sign in. Is the identity service running?";
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-gray-50 px-4">
    <div class="w-full max-w-sm rounded-lg border border-gray-200 bg-white p-8 shadow-sm">
      <h1 class="mb-1 text-xl font-semibold">Sign in to Forge</h1>
      <p class="mb-6 text-sm text-gray-500">Use your CypherCrescent account.</p>

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

        <div>
          <label for="password" class="mb-1 block text-sm font-medium">Password</label>
          <input
            id="password"
            v-model="password"
            type="password"
            autocomplete="current-password"
            class="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-gray-500 focus:outline-none"
            placeholder="••••••••"
          />
        </div>

        <p class="text-right">
          <NuxtLink to="/forgot-password" class="text-xs text-gray-500 hover:underline">
            Forgot your password?
          </NuxtLink>
        </p>

        <p v-if="errorMessage" class="text-sm text-red-600">{{ errorMessage }}</p>

        <button
          type="submit"
          :disabled="submitting"
          class="w-full rounded-md bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-60"
        >
          {{ submitting ? "Signing in…" : "Sign in" }}
        </button>
      </form>

      <p class="mt-6 text-sm text-gray-500">
        New here?
        <NuxtLink to="/signup" class="font-medium text-gray-900 hover:underline">
          Create an account
        </NuxtLink>
      </p>
    </div>
  </div>
</template>
