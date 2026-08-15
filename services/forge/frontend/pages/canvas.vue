<script setup lang="ts">
import { MONO_LABEL } from "@crescent/ui/utils/ui";
import { MODULE_GROUPS } from "~/constants/canvasModules";

definePageMeta({ middleware: "auth" });

/* A static sketch. Nothing here is wired to the API, nothing is draggable and no
   workflow runs — the page exists to settle the vocabulary and the shape of the builder
   before it is built. Every surface on it is dashed for that reason. */
const NODES = [
  { kind: "Data in", title: "Dataset", detail: "a CSV you uploaded" },
  { kind: "Prepare", title: "Fill blanks", detail: "median for numeric columns" },
  { kind: "Model", title: "Forecast", detail: "6 periods ahead" },
  { kind: "Results out", title: "Chart", detail: "history + forecast band" },
];

const WEEK6_TAG = `${MONO_LABEL} inline-flex shrink-0 items-center rounded border border-dashed border-line px-2 py-[3px] text-ink-muted`;
</script>

<template>
  <div>
    <section>
      <Eyebrow>Forge · workflow canvas</Eyebrow>
      <div class="mt-3 flex flex-wrap items-center gap-3">
        <h1 class="text-[clamp(1.5rem,2.2vw,1.9rem)] font-semibold tracking-[-0.035em]">
          The builder, drawn before it is built
        </h1>
        <span :class="WEEK6_TAG">Week 6 · not built</span>
      </div>
      <p class="mt-3 max-w-[64ch] text-[13px] leading-relaxed text-ink-muted">
        Twelve modules in four groups, chained into a workflow. Today this page is a drawing:
        nothing is draggable, nothing connects, and there is no Run button that does anything.
        Upload and preview are what work in Forge right now.
      </p>
      <p :class="[MONO_LABEL, 'mt-5 border-y border-line-subtle py-3 text-ink-muted']">
        static sketch · no drag · no connections · no runs · no saved workflows
      </p>
    </section>

    <section class="mt-10 grid gap-8 border-t border-line-subtle pt-8 lg:grid-cols-12 lg:gap-10">
      <div class="lg:col-span-4">
        <h2 :class="[MONO_LABEL, 'text-ink-muted']">Module vocabulary</h2>
        <div class="mt-4 space-y-5">
          <div v-for="group in MODULE_GROUPS" :key="group.group">
            <p class="text-[12.5px] font-medium text-ink-muted">{{ group.group }}</p>
            <ul class="mt-2 space-y-1.5">
              <li
                v-for="m in group.modules"
                :key="m"
                class="mono flex items-center gap-2 rounded-md border border-dashed border-line-subtle bg-surface/25 px-2.5 py-[7px] text-[11px] text-ink-faint"
              >
                <span class="h-1 w-1 rounded-full bg-line-strong" aria-hidden="true" />
                {{ m }}
              </li>
            </ul>
          </div>
        </div>
      </div>

      <div class="lg:col-span-8">
        <h2 :class="[MONO_LABEL, 'text-ink-muted']">A chain, as it would read</h2>
        <ol class="mt-4 rounded-md border border-dashed border-line bg-app/40 p-5">
          <li v-for="(node, i) in NODES" :key="node.title">
            <div class="rounded-md border border-dashed border-line-subtle bg-surface/25 px-4 py-3">
              <p :class="[MONO_LABEL, 'text-ink-faint']">{{ node.kind }}</p>
              <p class="mt-1 text-[13px] font-medium text-ink">{{ node.title }}</p>
              <p class="mono mt-0.5 text-[11.5px] text-ink-muted">{{ node.detail }}</p>
            </div>
            <p
              v-if="i < NODES.length - 1"
              class="mono py-1.5 text-center text-[11px] text-ink-faint"
              aria-hidden="true"
            >
              ↓
            </p>
          </li>
          <li class="mt-3 rounded-md border border-dashed border-line-subtle px-4 py-6">
            <p :class="[MONO_LABEL, 'text-ink-faint']">a module would land here</p>
          </li>
        </ol>
        <p class="mt-4 max-w-[64ch] text-[12.5px] leading-relaxed text-ink-muted">
          Each learning path becomes one of these chains, pre-filled so only the dataset and the
          columns are left to pick. Written up under Learning.
        </p>
      </div>
    </section>
  </div>
</template>
