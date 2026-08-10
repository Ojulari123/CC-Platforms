<script setup lang="ts">
import { z } from "zod";

definePageMeta({ layout: false });

const auth = useAuth();
const router = useRouter();

// bcrypt reads at most 72 bytes, so identity rejects anything longer. Bytes, not
// characters: an accented letter or emoji costs 2–4 of them.
const MAX_PASSWORD_BYTES = 72;
const encoder = new TextEncoder();
const passwordBytes = (v: string) => encoder.encode(v).length;

// Mirrors identity's validate_password so people see the rules before they submit
// rather than guessing at a 400. The server is still the authority.
const passwordRules = [
  { label: "At least 8 characters", test: (v: string) => v.length >= 8 },
  {
    label: "No more than 72 bytes (accents and emoji count extra)",
    test: (v: string) => passwordBytes(v) <= MAX_PASSWORD_BYTES,
  },
  { label: "One uppercase letter", test: (v: string) => /[A-Z]/.test(v) },
  { label: "One lowercase letter", test: (v: string) => /[a-z]/.test(v) },
  { label: "One number", test: (v: string) => /[0-9]/.test(v) },
  { label: "One special character", test: (v: string) => /[^A-Za-z0-9]/.test(v) },
];

const signupSchema = z.object({
  first_name: z.string().min(1, "First name is required").max(100),
  last_name: z.string().min(1, "Last name is required").max(100),
  email: z.string().email("Enter a valid email address"),
  password: z
    .string()
    .min(8, "Password must be at least 8 characters")
    .regex(/[A-Z]/, "Password needs one uppercase letter")
    .regex(/[a-z]/, "Password needs one lowercase letter")
    .regex(/[0-9]/, "Password needs one number")
    .regex(/[^A-Za-z0-9]/, "Password needs one special character")
    .refine(
      (v) => passwordBytes(v) <= MAX_PASSWORD_BYTES,
      (v) => ({
        message: `Password is too long (${passwordBytes(v)} bytes; the limit is ${MAX_PASSWORD_BYTES}).`,
      }),
    ),
});

const firstName = ref("");
const lastName = ref("");
const email = ref("");
const password = ref("");
const errorMessage = ref<string | null>(null);
const emailTaken = ref(false);
const submitting = ref(false);

onMounted(() => {
  auth.hydrate();
  if (auth.isAuthenticated.value) {
    router.replace("/");
  }
});

const ruleState = computed(() =>
  passwordRules.map((rule) => ({ label: rule.label, met: rule.test(password.value) })),
);

// FastAPI puts the human-readable reason in `detail`; on a 422 it's a list of
// field errors instead, which isn't worth showing raw.
function serverDetail(err: unknown): string | null {
  const detail = (err as { data?: { detail?: unknown } })?.data?.detail;
  return typeof detail === "string" ? detail : null;
}

async function onSubmit() {
  errorMessage.value = null;
  emailTaken.value = false;
  const parsed = signupSchema.safeParse({
    first_name: firstName.value.trim(),
    last_name: lastName.value.trim(),
    email: email.value.trim(),
    password: password.value,
  });
  if (!parsed.success) {
    errorMessage.value = parsed.error.issues[0]?.message ?? "Invalid input";
    return;
  }

  submitting.value = true;
  try {
    await auth.signup(parsed.data);
    await router.push("/");
  } catch (err: unknown) {
    const status = (err as { statusCode?: number; status?: number })?.statusCode
      ?? (err as { status?: number })?.status;
    const detail = serverDetail(err);
    if (status === 403) {
      // Identity can restrict signup to specific email domains.
      errorMessage.value = detail ?? "Sign-ups aren't open to that email domain.";
    } else if (status === 409) {
      emailTaken.value = true;
      errorMessage.value = detail ?? "An account with that email already exists.";
    } else if (status === 400) {
      errorMessage.value = detail ?? "That password doesn't meet the requirements.";
    } else if (status === 422) {
      errorMessage.value = "Check the details above and try again.";
    } else if (status === 429) {
      errorMessage.value = "Too many attempts. Wait a minute and try again.";
    } else {
      errorMessage.value = "Could not create your account. Is the identity service running?";
    }
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-gray-50 px-4 py-10">
    <div class="w-full max-w-sm rounded-lg border border-gray-200 bg-white p-8 shadow-sm">
      <h1 class="mb-1 text-xl font-semibold">Create your Forge account</h1>
      <p class="mb-6 text-sm text-gray-500">
        You'll be signed in straight away. An admin adds you to a department later.
      </p>

      <form class="space-y-4" @submit.prevent="onSubmit">
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
            autocomplete="new-password"
            class="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-gray-500 focus:outline-none"
            placeholder="••••••••"
          />
          <ul class="mt-2 space-y-0.5">
            <li
              v-for="rule in ruleState"
              :key="rule.label"
              class="flex items-center gap-1.5 text-xs"
              :class="rule.met ? 'text-green-600' : 'text-gray-500'"
            >
              <span aria-hidden="true">{{ rule.met ? "✓" : "•" }}</span>
              {{ rule.label }}
            </li>
          </ul>
        </div>

        <div v-if="errorMessage" class="text-sm text-red-600">
          <p>{{ errorMessage }}</p>
          <NuxtLink v-if="emailTaken" to="/login" class="underline">Sign in instead</NuxtLink>
        </div>

        <button
          type="submit"
          :disabled="submitting"
          class="w-full rounded-md bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-60"
        >
          {{ submitting ? "Creating account…" : "Create account" }}
        </button>
      </form>

      <p class="mt-6 text-sm text-gray-500">
        Already have an account?
        <NuxtLink to="/login" class="font-medium text-gray-900 hover:underline">Sign in</NuxtLink>
      </p>
    </div>
  </div>
</template>
