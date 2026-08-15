<script setup lang="ts">
import { computed, ref } from "vue";
import Btn from "@crescent/ui/components/Btn.vue";
import Modal from "@crescent/ui/components/Modal.vue";
import { FOCUS, MONO_LABEL } from "@crescent/ui/utils/ui";
import type { DatasetResponse } from "~/types/api";
import { formatStamp } from "~/utils/upload";

/* The rows plus the confirmation in front of the destructive one. Delete is offered
   only where the API would allow it — samples belong to nobody and the service refuses
   a delete from anyone but the owner, so a button that can only earn a 403 is not
   drawn at all. */
const props = withDefaults(
  defineProps<{
    datasets: DatasetResponse[];
    currentUserId: number | null;
    /** A delete is in flight; the row controls stand down until it settles. */
    busy?: boolean;
  }>(),
  { busy: false },
);

const emit = defineEmits<{ confirm: [dataset: DatasetResponse] }>();

const pending = ref<DatasetResponse | null>(null);

function owner(ds: DatasetResponse): string {
  if (ds.is_sample) return "sample";
  if (props.currentUserId !== null && ds.owner_user_id === props.currentUserId) return "yours";
  return ds.owner_user_id === null ? "unowned" : `user_id ${ds.owner_user_id}`;
}

function deletable(ds: DatasetResponse): boolean {
  return !ds.is_sample && props.currentUserId !== null && ds.owner_user_id === props.currentUserId;
}

const description = computed(() => {
  const ds = pending.value;
  if (!ds) return undefined;
  return `${ds.name} — ${ds.row_count.toLocaleString()} rows, ${ds.columns.length} columns. The file and its parsed rows go; nothing else references it.`;
});

function go() {
  const ds = pending.value;
  if (!ds) return;
  pending.value = null;
  emit("confirm", ds);
}
</script>

<template>
  <div>
    <p v-if="datasets.length === 0" :class="[MONO_LABEL, 'mt-6 border-t border-line-subtle pt-6 text-ink-muted']">
      nothing to list · upload a csv to start
    </p>

    <!-- A table, not a flex row: the counts have to line up between rows, and a row that
         carries a Delete cannot be allowed to shift the columns of the rows that do not. -->
    <table v-else class="mt-4 w-full border-collapse text-left">
      <caption class="sr-only">
        Datasets you can open — their size, when they were uploaded and who owns them.
      </caption>
      <thead>
        <tr class="border-y border-line-subtle">
          <th scope="col" :class="[MONO_LABEL, 'py-2 pr-3 font-normal text-ink-faint']">Dataset</th>
          <th scope="col" :class="[MONO_LABEL, 'whitespace-nowrap px-2 py-2 text-right font-normal text-ink-faint sm:px-3']">Rows</th>
          <th scope="col" :class="[MONO_LABEL, 'whitespace-nowrap px-2 py-2 text-right font-normal text-ink-faint sm:px-3']">Cols</th>
          <th scope="col" :class="[MONO_LABEL, 'hidden whitespace-nowrap px-3 py-2 font-normal text-ink-faint sm:table-cell']">Uploaded</th>
          <th scope="col" :class="[MONO_LABEL, 'whitespace-nowrap px-2 py-2 font-normal text-ink-faint sm:px-3']">Owner</th>
          <th scope="col" class="py-2 pl-2 sm:pl-3"><span class="sr-only">Actions</span></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="ds in datasets" :key="ds.id" class="border-b border-line-subtle">
          <!-- w-full + max-w-0 lets the name column take the leftover width and still
               truncate, instead of widening the table until the numbers fall off. -->
          <td class="w-full max-w-0 py-3.5 pr-3">
            <NuxtLink
              :to="`/datasets/${ds.id}`"
              :class="[FOCUS, 'mono block truncate rounded text-[12.5px] text-ink hover:underline']"
            >
              {{ ds.name }}
            </NuxtLink>
          </td>
          <td class="mono whitespace-nowrap px-2 py-3.5 text-right text-[12px] tabular-nums text-ink-muted sm:px-3">
            {{ ds.row_count.toLocaleString() }}
          </td>
          <td class="mono whitespace-nowrap px-2 py-3.5 text-right text-[12px] tabular-nums text-ink-muted sm:px-3">
            {{ ds.columns.length }}
          </td>
          <td class="mono hidden whitespace-nowrap px-3 py-3.5 text-[12px] text-ink-muted sm:table-cell">
            {{ formatStamp(ds.created_at) }}
          </td>
          <td class="mono whitespace-nowrap px-2 py-3.5 text-[12px] text-ink-muted sm:px-3">{{ owner(ds) }}</td>
          <td class="whitespace-nowrap py-3.5 pl-2 text-right sm:pl-3">
            <Btn
              v-if="deletable(ds)"
              variant="ghost"
              size="sm"
              :disabled="busy"
              :aria-label="`Delete ${ds.name}`"
              @click="pending = ds"
            >
              Delete
            </Btn>
          </td>
        </tr>
      </tbody>
    </table>

    <Modal
      :open="pending !== null"
      title="Delete this dataset?"
      :description="description"
      :close-on-backdrop="false"
      @close="pending = null"
    >
      <p v-if="pending" :class="[MONO_LABEL, 'text-ink-muted']">
        dataset_id {{ pending.id }} · uploaded {{ formatStamp(pending.created_at) }} ·
        {{ pending.columns.length }} cols
      </p>
      <template #footer>
        <Btn variant="secondary" size="sm" @click="pending = null">Keep it</Btn>
        <Btn variant="destructive" size="sm" @click="go">Delete dataset</Btn>
      </template>
    </Modal>
  </div>
</template>
