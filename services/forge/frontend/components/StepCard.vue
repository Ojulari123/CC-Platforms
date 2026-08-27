<script setup lang="ts">
import { computed } from "vue";
import { FOCUS, MONO_LABEL } from "@crescent/ui/utils/ui";
import type { WorkflowKind } from "~/types/api";
import { ALGORITHMS_FOR_KIND, ALLOWED_HYPERPARAMETERS, STEP_FIELDS, describeStep, humanise, strategyNote } from "~/utils/workflows";

/* One step of the workflow, drawn as its own thing with its parameters on show. Nothing
   here is hidden behind a details toggle: the point of the canvas is that a learner can
   read down it and know what will happen to the data before pressing Run. */
const props = withDefaults(
  defineProps<{
    kind: string;
    params: Record<string, unknown>;
    /** 1-based place in the run order. */
    position: number;
    total: number;
    label: string;
    summary: string;
    workflowKind: WorkflowKind;
    /** Dataset column names, when a dataset is attached. */
    columns?: string[];
    removable?: boolean;
    active?: boolean;
  }>(),
  { columns: () => [], removable: true, active: false },
);

const emit = defineEmits<{
  "update:params": [params: Record<string, unknown>];
  remove: [];
  focus: [];
}>();

const FIELD_CLASS = `${FOCUS} w-full rounded-md bg-sunken px-3 py-2 text-[12.5px] text-ink ring-1 ring-inset ring-line transition-colors placeholder:text-ink-faint hover:ring-line-strong`;

const fields = computed(() => STEP_FIELDS[props.kind] ?? []);
const visible = computed(() => fields.value.filter((f) => !f.when || f.when(props.params)));
const detail = computed(() => describeStep(props.kind, props.params));

function optionsFor(key: string, given: string[] | undefined) {
  const values = key === "algorithm" ? ALGORITHMS_FOR_KIND[props.workflowKind] : given ?? [];
  return values.map((value) => ({ value, label: humanise(value) }));
}

function set(key: string, value: unknown) {
  emit("update:params", { ...props.params, [key]: value });
}

function asColumns(key: string): string[] {
  const value = props.params[key];
  return Array.isArray(value) ? (value as string[]) : [];
}

function toggleColumn(key: string, column: string) {
  const current = asColumns(key);
  set(key, current.includes(column) ? current.filter((c) => c !== column) : [...current, column]);
}

const hyperparameters = computed(() => {
  const value = props.params.hyperparameters;
  return value && typeof value === "object" ? (value as Record<string, number>) : {};
});

const unusedHyperparameters = computed(() => ALLOWED_HYPERPARAMETERS.filter((name) => !(name in hyperparameters.value)));

function setHyperparameter(name: string, raw: string) {
  const next = { ...hyperparameters.value };
  const parsed = Number(raw);
  if (raw.trim() === "" || Number.isNaN(parsed)) delete next[name];
  else next[name] = parsed;
  set("hyperparameters", next);
}

function addHyperparameter(name: string) {
  if (!name) return;
  set("hyperparameters", { ...hyperparameters.value, [name]: 0 });
}

function dropHyperparameter(name: string) {
  const next = { ...hyperparameters.value };
  delete next[name];
  set("hyperparameters", next);
}
</script>

<template>
  <article
    :class="[
      'rounded-md bg-surface/40 ring-1 ring-inset transition-colors',
      active ? 'ring-accent-ink' : 'ring-line-subtle',
    ]"
    @focusin="emit('focus')"
    @mouseenter="emit('focus')"
  >
    <header class="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-line-subtle px-4 py-3">
      <span :class="[MONO_LABEL, 'text-ink-faint']">step {{ position }} of {{ total }}</span>
      <h3 class="text-[14px] font-semibold leading-tight tracking-[-0.01em] text-ink">{{ label }}</h3>
      <span class="mono text-[12px] text-ink-faint">{{ kind }}</span>
      <button
        v-if="removable"
        type="button"
        :class="[FOCUS, 'mono ml-auto rounded px-2 py-1 text-[12px] text-ink-muted transition-colors hover:bg-surface-hover hover:text-ink']"
        @click="emit('remove')"
      >
        Remove
      </button>
    </header>

    <div class="px-4 py-3">
      <p class="text-[12.5px] leading-relaxed text-ink-muted">{{ summary }}</p>
      <p v-if="detail" class="mono mt-1.5 text-[12px] text-ink">{{ detail }}</p>

      <div v-if="visible.length" class="mt-4 space-y-4">
        <div v-for="field in visible" :key="field.key">
          <label
            v-if="field.type !== 'toggle' && field.type !== 'columns'"
            :class="[MONO_LABEL, 'block text-ink-muted']"
            :for="`step-${position}-${field.key}`"
          >
            {{ field.label }}
          </label>
          <p v-else :class="[MONO_LABEL, 'text-ink-muted']">{{ field.label }}</p>

          <div class="mt-1.5">
            <Select
              v-if="field.type === 'select'"
              :model-value="String(params[field.key] ?? '')"
              :options="optionsFor(field.key, field.options)"
              :label="field.label"
              @update:model-value="set(field.key, $event)"
            />

            <Select
              v-else-if="field.type === 'column' && columns.length"
              :model-value="String(params[field.key] ?? '')"
              :options="columns.map((c) => ({ value: c, label: c }))"
              :label="field.label"
              placeholder="Choose a column"
              @update:model-value="set(field.key, $event)"
            />

            <input
              v-else-if="field.type === 'column' || field.type === 'text'"
              :id="`step-${position}-${field.key}`"
              :class="FIELD_CLASS"
              type="text"
              :value="String(params[field.key] ?? '')"
              :placeholder="field.placeholder"
              @input="set(field.key, ($event.target as HTMLInputElement).value)"
            >

            <input
              v-else-if="field.type === 'number'"
              :id="`step-${position}-${field.key}`"
              :class="FIELD_CLASS"
              type="number"
              :min="field.min"
              :max="field.max"
              :step="field.step"
              :value="params[field.key] as number"
              @input="set(field.key, Number(($event.target as HTMLInputElement).value))"
            >

            <textarea
              v-else-if="field.type === 'textarea'"
              :id="`step-${position}-${field.key}`"
              :class="[FIELD_CLASS, 'resize-y leading-relaxed']"
              :rows="field.rows ?? 3"
              :placeholder="field.placeholder"
              :value="String(params[field.key] ?? '')"
              @input="set(field.key, ($event.target as HTMLTextAreaElement).value)"
            />

            <label v-else-if="field.type === 'toggle'" class="flex items-center gap-2.5 text-[12.5px] text-ink">
              <input
                :class="[FOCUS, 'h-4 w-4 rounded-sm accent-[color:var(--ink)]']"
                type="checkbox"
                :checked="Boolean(params[field.key])"
                @change="set(field.key, ($event.target as HTMLInputElement).checked)"
              >
              {{ field.label }}
            </label>

            <div v-else-if="field.type === 'columns'">
              <div v-if="columns.length" class="flex flex-wrap gap-1.5">
                <button
                  v-for="column in columns"
                  :key="column"
                  type="button"
                  :aria-pressed="asColumns(field.key).includes(column)"
                  :class="[
                    FOCUS,
                    'mono rounded px-2 py-1 text-[12px] ring-1 ring-inset transition-colors',
                    asColumns(field.key).includes(column)
                      ? 'bg-surface-active text-ink ring-line-strong'
                      : 'text-ink-muted ring-line hover:bg-surface-hover hover:text-ink',
                  ]"
                  @click="toggleColumn(field.key, column)"
                >
                  {{ column }}
                </button>
              </div>
              <p v-else class="mono text-[12px] text-ink-faint">Attach a dataset to pick columns.</p>
            </div>

            <div v-else-if="field.type === 'hyperparameters'" class="space-y-2">
              <div v-for="(value, name) in hyperparameters" :key="name" class="flex items-center gap-2">
                <span class="mono w-36 shrink-0 text-[12px] text-ink-muted">{{ name }}</span>
                <input
                  :class="[FIELD_CLASS, 'max-w-[10rem]']"
                  type="number"
                  :aria-label="name"
                  :value="String(value)"
                  @input="setHyperparameter(name, ($event.target as HTMLInputElement).value)"
                >
                <button
                  type="button"
                  :class="[FOCUS, 'mono rounded px-2 py-1 text-[12px] text-ink-muted transition-colors hover:bg-surface-hover hover:text-ink']"
                  @click="dropHyperparameter(name)"
                >
                  Remove
                </button>
              </div>
              <Select
                v-if="unusedHyperparameters.length"
                model-value=""
                :options="unusedHyperparameters.map((n) => ({ value: n, label: n }))"
                label="Add a hyperparameter"
                placeholder="Add a setting"
                @update:model-value="addHyperparameter($event)"
              />
            </div>
          </div>

          <p v-if="strategyNote(params[field.key])" class="mt-1.5 max-w-[62ch] text-[12px] leading-relaxed text-ink-muted">
            {{ strategyNote(params[field.key]) }}
          </p>
          <p v-else-if="field.note" class="mt-1.5 max-w-[62ch] text-[12px] leading-relaxed text-ink-muted">
            {{ field.note }}
          </p>
        </div>
      </div>
    </div>
  </article>
</template>
