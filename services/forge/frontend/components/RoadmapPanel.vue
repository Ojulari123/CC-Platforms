<script setup lang="ts">
import { computed, ref } from "vue";
import Eyebrow from "@crescent/ui/components/Eyebrow.vue";
import Icon from "@crescent/ui/components/Icon.vue";
import StatusDot from "@crescent/ui/components/StatusDot.vue";
import { FOCUS, MONO_LABEL, TAP } from "@crescent/ui/utils/ui";
import { LEARNING_PATHS } from "~/constants/learningPaths";
import { MODULE_GROUPS } from "~/constants/canvasModules";

/* Nothing here was cut from the workspace — it is the same build ledger, the same
   week 6 specification and the same not-yet list, moved below the tool and closed by
   default. A signed-in workspace opens on the thing that works, not on two thirds of a
   page explaining what it is not.

   Every control inside stays disabled while collapsed: clipped content is still in the
   tab order otherwise, and an aria-hidden region you can tab into is worse than one you
   cannot see. Dashed hairlines mean "not built yet" and are used nowhere else, and they
   mark the guided walkthrough rather than the task: every task below runs on the canvas
   today, so each one links to the screen that does it. */

const LEDGER: { label: string; live: boolean }[] = [
  { label: "CSV upload, 5 MB cap", live: true },
  { label: "Column + row preview", live: true },
  { label: "Dataset list and delete", live: true },
  { label: "Shared sample datasets", live: true },
  { label: "Workflow canvas", live: true },
  { label: "Train, score, forecast", live: true },
  { label: "LLM playground", live: true },
  { label: "Generated Python and notebook", live: true },
  { label: "Guided learning paths", live: false },
];

const NOT_YET = [
  "The four guided walkthroughs are still a written specification. All four tasks they cover run on the canvas; what is missing is being walked through one.",
  "No feature importance, joins, filters or CSV export.",
  "A fitted model is scored and then thrown away. Nothing is saved for reuse.",
  "No two-way editing: changing the generated Python does not change the canvas.",
];

const WEEK6_TAG = `${MONO_LABEL} inline-flex shrink-0 items-center gap-1.5 rounded border border-dashed border-line px-2 py-[3px] text-ink-muted`;

const open = ref(false);
const pathSlug = ref(LEARNING_PATHS[0]?.slug ?? "");

const path = computed(() => LEARNING_PATHS.find((p) => p.slug === pathSlug.value) ?? LEARNING_PATHS[0]);
</script>

<template>
  <section class="mt-14 border-t border-line-subtle pt-8">
    <button
      type="button"
      :aria-expanded="open"
      aria-controls="forge-not-built"
      :class="[FOCUS, TAP, 'flex w-full flex-wrap items-baseline gap-x-3 gap-y-1.5 rounded px-1 py-2 text-left transition-colors hover:bg-surface-hover/40']"
      @click="open = !open"
    >
      <Eyebrow>Build status</Eyebrow>
      <span class="text-[13.5px] font-medium text-ink">
        What runs today, and what is still only written down
      </span>
      <span :class="[MONO_LABEL, 'ml-auto inline-flex shrink-0 items-center gap-1.5 text-ink-muted']">
        {{ open ? "hide" : "show" }}
        <Icon name="chevronDown" :class="['h-3.5 w-3.5 transition-transform', open && '-rotate-180']" />
      </span>
    </button>
    <!-- The manifest stays outside the collapse so what is inside is readable while
         it is shut. Discoverability was the whole objection to closing it. -->
    <p :class="[MONO_LABEL, 'mt-1 px-1 text-ink-faint']">
      build ledger · four tasks · canvas vocabulary · not-yet list
    </p>

    <div id="forge-not-built" class="sec-collapse" :data-open="open ? 'true' : 'false'" :aria-hidden="!open">
      <div>
        <div class="pt-8">
          <div class="rounded-md bg-surface/40 ring-1 ring-line-subtle">
            <div class="flex items-baseline justify-between gap-3 border-b border-line-subtle px-4 py-3">
              <h3 class="text-[12.5px] font-medium">What runs right now</h3>
              <span :class="[MONO_LABEL, 'text-ink-faint']">build status</span>
            </div>
            <ul>
              <li
                v-for="row in LEDGER"
                :key="row.label"
                class="flex items-center gap-3 border-b border-line-subtle/60 px-4 py-[9px] last:border-0"
              >
                <StatusDot :tone="row.live ? 'ok' : 'warn'" quiet class="shrink-0" />
                <span :class="['text-[12.5px]', row.live ? 'text-ink' : 'text-ink-muted']">{{ row.label }}</span>
                <span :class="[MONO_LABEL, 'ml-auto text-ink-muted']">{{ row.live ? "live" : "planned" }}</span>
              </li>
            </ul>
            <p class="border-t border-line-subtle px-4 py-3 text-[12.5px] leading-relaxed text-ink-muted">
              Anything marked <span class="mono text-ink">planned</span> is written down and not
              built. Everything marked live has a screen you can use now.
            </p>
          </div>
        </div>

        <div class="mt-12 border-t border-line-subtle pt-10">
          <div class="flex flex-wrap items-center gap-3">
            <Eyebrow>Next</Eyebrow>
            <span :class="WEEK6_TAG">Guided walkthroughs · not built</span>
          </div>
          <h3 class="mt-2.5 max-w-[48ch] text-[clamp(1.35rem,2.4vw,1.75rem)] font-semibold leading-[1.15] tracking-[-0.025em]">
            The four tasks run. Being walked through them does not.
          </h3>
          <p class="mt-3 max-w-[64ch] text-[13px] leading-relaxed text-ink-muted">
            Every task below is on the canvas today: pick it, attach a CSV, run it and read the
            Python it generates. What is still only written down is the guided version, which
            would carry you through one end to end. Until it exists you assemble the steps
            yourself, and each task links to the canvas that does it.
          </p>
        </div>

        <div class="mt-8 grid gap-6 lg:grid-cols-12 lg:gap-10">
          <div class="lg:col-span-5">
            <h4 :class="[MONO_LABEL, 'text-ink-muted']">Four tasks, all runnable today</h4>
            <ul class="mt-3 space-y-1.5">
              <li v-for="p in LEARNING_PATHS" :key="p.slug">
                <button
                  type="button"
                  :aria-pressed="p.slug === pathSlug"
                  :disabled="!open"
                  :class="[
                    FOCUS,
                    'flex w-full items-center gap-3 rounded-md border border-dashed px-3.5 py-3 text-left transition-colors',
                    p.slug === pathSlug ? 'border-line-strong bg-surface/60' : 'border-line-subtle enabled:hover:bg-surface/40',
                  ]"
                  @click="pathSlug = p.slug"
                >
                  <span class="min-w-0 flex-1">
                    <span :class="['block text-[13.5px] font-medium', p.slug === pathSlug ? 'text-ink' : 'text-ink-muted']">
                      {{ p.title }}
                    </span>
                    <span class="mt-0.5 block truncate text-[12px] text-ink-muted">{{ p.summary }}</span>
                  </span>
                  <span :class="[MONO_LABEL, 'shrink-0 text-ink-muted']">{{ p.steps.length }} steps</span>
                </button>
              </li>
            </ul>
          </div>

          <div v-if="path" class="lg:col-span-7">
            <div class="rounded-md border border-dashed border-line bg-app/40 p-5">
              <div class="flex flex-wrap items-center justify-between gap-3">
                <h4 class="text-[15px] font-semibold tracking-[-0.015em]">{{ path.title }}</h4>
                <span :class="WEEK6_TAG">Walkthrough not built</span>
              </div>
              <p class="mt-2.5 max-w-[56ch] text-[13px] leading-relaxed text-ink-muted">{{ path.summary }}</p>

              <ol class="mt-5">
                <li
                  v-for="(step, i) in path.steps"
                  :key="step.title"
                  class="flex items-center gap-3 border-t border-line-subtle py-2.5 first:border-0 first:pt-0"
                >
                  <span class="mono grid h-5 w-5 shrink-0 place-items-center rounded border border-dashed border-line text-[12px] text-ink-faint">
                    {{ i + 1 }}
                  </span>
                  <span class="text-[12.5px] text-ink-muted">{{ step.title }}</span>
                  <span :class="[MONO_LABEL, 'ml-auto text-ink-faint']">no walkthrough</span>
                </li>
              </ol>

              <!-- Rendered only while open. An anchor cannot be disabled the way the path
                   buttons are, and FOCUSABLE matches `a[href]` whatever its tabindex, so the
                   only way it stays out of the tab order while collapsed is to not exist. -->
              <p v-if="open" class="mt-5 max-w-[56ch] text-[12.5px] leading-relaxed text-ink-muted">
                These steps are not guided yet. The task itself runs:
                <NuxtLink
                  :to="`/canvas?task=${path.workflowKind}`"
                  :class="[FOCUS, 'rounded font-medium text-ink underline underline-offset-4']"
                >
                  open {{ path.title }} on the canvas
                </NuxtLink>
                and assemble it yourself.
              </p>

              <div class="mt-5 border-t border-line-subtle pt-4">
                <p :class="[MONO_LABEL, 'text-ink-faint']">For example</p>
                <p class="mt-1.5 max-w-[60ch] text-[12.5px] leading-relaxed text-ink-muted">{{ path.example }}</p>
              </div>
            </div>
          </div>
        </div>

        <div class="mt-12 border-t border-line-subtle pt-8">
          <div class="flex flex-wrap items-end justify-between gap-4">
            <div>
              <h4 :class="[MONO_LABEL, 'text-ink-muted']">Canvas vocabulary</h4>
              <p class="mt-2 max-w-[52ch] text-[13px] leading-relaxed text-ink-muted">
                The groups the steps fall into. Nine have a step on the canvas today; the three
                marked planned do not exist yet.
              </p>
            </div>
            <span :class="[MONO_LABEL, 'shrink-0 text-ink-muted']">nine of twelve built</span>
          </div>

          <div class="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div
              v-for="(g, gi) in MODULE_GROUPS"
              :key="g.group"
              class="rounded-md border border-dashed border-line-subtle p-3.5"
            >
              <div class="flex items-baseline justify-between">
                <p class="text-[12.5px] font-medium text-ink-muted">{{ g.group }}</p>
                <span class="mono text-[12px] text-ink-faint">{{ `0${gi + 1}` }}</span>
              </div>
              <ul class="mt-3 space-y-1.5">
                <!-- A built module takes the solid hairline the rest of the product uses for
                     things that work; the dashed one stays on the three that do not exist. -->
                <li
                  v-for="m in g.modules"
                  :key="m.name"
                  :class="[
                    'mono flex items-center gap-2 rounded-md px-2.5 py-[7px] text-[12px]',
                    m.live
                      ? 'border border-line-subtle bg-surface/40 text-ink-muted'
                      : 'border border-dashed border-line-subtle bg-surface/25 text-ink-faint',
                  ]"
                >
                  <StatusDot :tone="m.live ? 'ok' : 'warn'" quiet class="shrink-0" />
                  {{ m.name }}
                  <span v-if="!m.live" :class="[MONO_LABEL, 'ml-auto text-ink-faint']">planned</span>
                </li>
              </ul>
            </div>
          </div>
        </div>

        <div class="mt-10 grid gap-6 rounded-md bg-sunken/50 p-5 ring-1 ring-line-subtle sm:grid-cols-12 sm:gap-8">
          <div class="sm:col-span-4">
            <p class="flex items-center gap-2 text-[13px] font-medium">
              <span class="text-ink-faint"><Icon name="clock" class="h-4 w-4" /></span>
              Not in the product yet
            </p>
            <p class="mt-2 text-[12px] leading-relaxed text-ink-muted">
              Listed plainly so nobody has to guess which parts are real.
            </p>
          </div>
          <ul class="sm:col-span-8 sm:grid sm:grid-cols-2 sm:gap-x-6">
            <li
              v-for="n in NOT_YET"
              :key="n"
              class="flex items-start gap-2.5 border-t border-line-subtle py-2 text-[12.5px] leading-relaxed text-ink-muted first:border-0 first:pt-0 sm:border-t-0 sm:py-1.5 sm:first:pt-1.5"
            >
              <span class="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-line-strong" aria-hidden="true" />
              {{ n }}
            </li>
          </ul>
        </div>

        <p :class="[MONO_LABEL, 'mt-8 border-t border-line-subtle pt-4 text-ink-muted']">
          upload · canvas · runs · code export · four tasks live · guided walkthroughs not built
        </p>
      </div>
    </div>
  </section>
</template>
