<script setup lang="ts">
import { computed, ref, watch } from "vue";
import Btn from "@crescent/ui/components/Btn.vue";
import Eyebrow from "@crescent/ui/components/Eyebrow.vue";
import Icon from "@crescent/ui/components/Icon.vue";
import Select from "@crescent/ui/components/Select.vue";
import { MONO_LABEL } from "@crescent/ui/utils/ui";
import type { ApproverCandidate, RepositoryResponse } from "~/types/api";
import { candidateOptions } from "~/utils/pulse";

/* Naming who can decide a report about this repository.

   Not a directory search: /approver-candidates returns the people whose commits, pull
   requests or issues appear here, plus whoever holds a post today, and marks which is
   which. Someone who has never worked here is not offered at all. */
const props = withDefaults(
  defineProps<{
    repo: RepositoryResponse;
    candidates: ApproverCandidate[];
    pending?: boolean;
    busy?: boolean;
    /** Off while the panel is collapsed: clipped controls are still tabbable. */
    active?: boolean;
    serverError?: string | null;
  }>(),
  { pending: false, busy: false, active: true, serverError: null },
);

const emit = defineEmits<{ save: [lead: number | null, deputy: number | null] }>();

const lead = ref(props.repo.lead_user_id === null ? "none" : String(props.repo.lead_user_id));
const deputy = ref(props.repo.deputy_user_id === null ? "none" : String(props.repo.deputy_user_id));
const clashError = ref<string | null>(null);

watch(
  () => [props.repo.lead_user_id, props.repo.deputy_user_id],
  ([nextLead, nextDeputy]) => {
    lead.value = nextLead === null ? "none" : String(nextLead);
    deputy.value = nextDeputy === null ? "none" : String(nextDeputy);
    clashError.value = null;
  },
);

// The endpoint is documented to include whoever holds a post today. If one is ever
// missing, the trigger falls back to its placeholder and the post looks vacant — and
// saving from there would clear it. Carry the holder in rather than lose them silently.
const options = computed(() => {
  const known = new Set(props.candidates.map((c) => c.user_id));
  const held: ApproverCandidate[] = [];
  const posts = [
    [props.repo.lead_user_id, props.repo.lead, true, false] as const,
    [props.repo.deputy_user_id, props.repo.deputy, false, true] as const,
  ];
  for (const [id, ref, isLead, isDeputy] of posts) {
    if (id === null || known.has(id)) continue;
    known.add(id);
    held.push({ user_id: id, person: ref, has_activity: false, is_lead: isLead, is_deputy: isDeputy });
  }
  return candidateOptions([...props.candidates, ...held]);
});
const errorMessage = computed(() => clashError.value ?? props.serverError);

function idOf(value: string): number | null {
  return value === "none" ? null : Number(value);
}

// The API rejects one person holding both posts with a 400. Catching it here means the
// user is told before a request goes out, not after half a swap has landed.
function save() {
  clashError.value = null;
  if (lead.value !== "none" && lead.value === deputy.value) {
    clashError.value = "The lead and deputy have to be two different people.";
    return;
  }
  emit("save", idOf(lead.value), idOf(deputy.value));
}
</script>

<template>
  <div class="min-w-0">
    <Eyebrow>Who can decide a report here</Eyebrow>
    <p class="mt-2 max-w-[62ch] text-[12.5px] leading-relaxed text-ink-muted">
      The picker only offers people whose commits, pull requests or issues appear in this
      repository, plus whoever holds a post today. Somebody who has never worked here is not in
      the list at all — and a post-holder who has stopped is kept, and labelled, rather than
      dropped. Lead and deputy both decide; they must be two different people.
    </p>

    <p v-if="pending" class="mt-3 text-[12.5px] text-ink-muted">Loading people…</p>

    <template v-else>
      <div class="mt-3.5 flex flex-wrap items-end gap-2">
        <div>
          <p :class="[MONO_LABEL, 'mb-1.5 text-ink-faint']">Lead</p>
          <Select
            v-model="lead"
            :label="`Lead for ${repo.full_name}`"
            class="w-[248px]"
            :disabled="!active"
            :options="options"
          />
        </div>
        <div>
          <p :class="[MONO_LABEL, 'mb-1.5 text-ink-faint']">Deputy · optional</p>
          <Select
            v-model="deputy"
            :label="`Deputy for ${repo.full_name}`"
            class="w-[248px]"
            :disabled="!active"
            :options="options"
          />
        </div>
        <Btn size="sm" data-test="save-posts" :disabled="!active" :busy="busy" @click="save">
          {{ busy ? "Saving" : "Save posts" }}
        </Btn>
      </div>

      <p
        v-if="candidates.length === 0"
        data-test="no-candidates"
        class="mt-3 max-w-[62ch] text-[12px] leading-relaxed text-ink-muted"
      >
        Nobody has synced work in this repository yet, so there is nobody the endpoint can offer.
        It will fill in after a sync that finds commits here.
      </p>

      <p
        v-if="errorMessage"
        role="alert"
        class="mt-3 flex items-start gap-2 text-[12px] leading-relaxed text-bad"
      >
        <span class="mt-0.5 shrink-0"><Icon name="alert" class="h-3.5 w-3.5" /></span>
        {{ errorMessage }}
      </p>

      <p class="mono mt-3.5 text-[11px] leading-relaxed text-ink-faint">
        get /github/repositories/{{ repo.id }}/approver-candidates<br />
        put /github/repositories/{{ repo.id }}/lead/{user_id}<br />
        put /github/repositories/{{ repo.id }}/deputy/{user_id}<br />
        delete /github/repositories/{{ repo.id }}/lead · deputy
      </p>
    </template>
  </div>
</template>
