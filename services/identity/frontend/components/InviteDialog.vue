<script lang="ts">
export interface InvitePayload {
  email: string;
  deptId: number;
  role: string;
}

// Deliberately looser than the server's EmailStr: this only has to catch a typo before
// a round trip, and a client-side address rule that is stricter than the server's
// rejects addresses the server would have accepted.
export const EMAIL_SHAPE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
</script>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import Btn from "@crescent/ui/components/Btn.vue";
import Modal from "@crescent/ui/components/Modal.vue";
import Select from "@crescent/ui/components/Select.vue";
import type { SelectOption } from "@crescent/ui/types/ui";
import { FOCUS, MONO_LABEL } from "@crescent/ui/utils/ui";
import { roleBlurb } from "~/utils/format";

/* Invite someone into a department.

   There is no "place them later": every invite endpoint is nested under a department
   (POST /departments/{dept_id}/invites), so an invite with no department has nowhere to
   go. It is also the right rule — somebody in no department cannot be given work or
   approvals, so the invite would create an account nobody can use. */
const props = withDefaults(
  defineProps<{
    open: boolean;
    departments: SelectOption[];
    roles: SelectOption[];
    lockedDeptId?: number | null;
    busy?: boolean;
    /** Whatever the API said. Rendered under the fields, not swallowed. */
    serverError?: string | null;
  }>(),
  { lockedDeptId: null, busy: false, serverError: null },
);

const emit = defineEmits<{ close: []; submit: [payload: InvitePayload] }>();

const email = ref("");
const deptId = ref(props.lockedDeptId === null ? "" : String(props.lockedDeptId));
const role = ref("engineer");
const error = ref<string | null>(null);
const emailField = ref<HTMLInputElement | null>(null);

const message = computed(() => error.value ?? props.serverError ?? null);

watch(
  () => props.open,
  (isOpen) => {
    if (!isOpen) return;
    email.value = "";
    error.value = null;
    role.value = "engineer";
    deptId.value = props.lockedDeptId === null ? "" : String(props.lockedDeptId);
  },
);

function submit() {
  error.value = null;
  const address = email.value.trim();
  if (address === "") {
    error.value = "An email address is required — it is how the invite gets there.";
    return;
  }
  if (!EMAIL_SHAPE.test(address)) {
    error.value = "That does not look like an email address.";
    return;
  }
  if (deptId.value === "") {
    error.value = "Choose a department. An invite is issued by a department, so there is no invite without one.";
    return;
  }
  emit("submit", { email: address, deptId: Number(deptId.value), role: role.value });
}
</script>

<template>
  <Modal
    :open="open"
    title="Invite someone"
    description="They get an emailed link. Nothing exists on their side until they open it and set a password."
    :initial-focus="emailField"
    @close="emit('close')"
  >
    <div class="space-y-4">
      <label class="block">
        <span :class="[MONO_LABEL, 'text-ink-faint']">Email address</span>
        <input
          ref="emailField"
          v-model="email"
          type="email"
          autocomplete="email"
          inputmode="email"
          spellcheck="false"
          placeholder="name@cyphercrescent.com"
          :aria-invalid="message !== null"
          :aria-describedby="message ? 'invite-error' : undefined"
          :class="[FOCUS, 'mono mt-1.5 w-full rounded-md bg-sunken px-2.5 py-2 text-[12.5px] text-ink ring-1 ring-inset ring-line-subtle placeholder:text-ink-faint']"
          @keydown.enter.prevent="submit"
          @input="error = null"
        />
      </label>

      <div v-if="lockedDeptId === null">
        <span :class="[MONO_LABEL, 'text-ink-faint']">Department</span>
        <div class="mt-1.5">
          <Select v-model="deptId" label="Department" placeholder="Choose a department" :options="departments" />
        </div>
        <p class="mt-1.5 text-[11px] leading-relaxed text-ink-faint">
          Required. An invite is issued by a department and carries it — someone in no department
          cannot be given work or approvals.
        </p>
      </div>

      <div>
        <span :class="[MONO_LABEL, 'text-ink-faint']">Role</span>
        <div class="mt-1.5">
          <Select v-model="role" label="Role" :options="roles" />
        </div>
        <p class="mt-1.5 text-[11px] leading-relaxed text-ink-faint">{{ roleBlurb(role) }}</p>
      </div>

      <p v-if="message" id="invite-error" role="alert" class="rounded bg-bad-surface px-3 py-2 text-[12px] text-bad">
        {{ message }}
      </p>
    </div>

    <template #footer>
      <Btn size="sm" variant="secondary" @click="emit('close')">Cancel</Btn>
      <Btn size="sm" :busy="busy" @click="submit">Send invite</Btn>
    </template>
  </Modal>
</template>
