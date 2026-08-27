<script setup lang="ts">
import { MONO_LABEL } from "@crescent/ui/utils/ui";
import { findLearningPath } from "~/constants/learningPaths";

definePageMeta({ middleware: "auth" });

const route = useRoute();
const path = computed(() => findLearningPath(route.params.slug as string));

const WEEK6_TAG = `${MONO_LABEL} inline-flex shrink-0 items-center rounded border border-dashed border-line px-2 py-[3px] text-ink-muted`;
</script>

<template>
  <div>
    <NuxtLink
      to="/learning"
      class="mono inline-flex items-center gap-1.5 rounded text-[12px] uppercase tracking-[0.08em] text-ink-muted transition-colors hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--accent-ink)]"
    >
      <Icon name="arrowLeft" class="h-3.5 w-3.5" />
      All learning paths
    </NuxtLink>

    <section v-if="!path" class="mt-8">
      <h1 class="text-[clamp(1.5rem,2.2vw,1.9rem)] font-semibold tracking-[-0.035em]">
        No path by that name
      </h1>
      <p class="mt-3 max-w-[54ch] text-[13px] leading-relaxed text-ink-muted">
        There are four: classification, regression, time series and the LLM playground.
      </p>
    </section>

    <template v-else>
      <section class="mt-6">
        <Eyebrow>Forge · learning path</Eyebrow>
        <div class="mt-3 flex flex-wrap items-center gap-3">
          <h1 class="text-[clamp(1.5rem,2.2vw,1.9rem)] font-semibold tracking-[-0.035em]">{{ path.title }}</h1>
          <span :class="WEEK6_TAG">Not built yet</span>
        </div>
        <p class="mt-3 max-w-[64ch] text-[13px] leading-relaxed text-ink-muted">{{ path.summary }}</p>
        <p :class="[MONO_LABEL, 'mt-5 border-y border-line-subtle py-3 text-ink-muted']">
          specification only · nothing on this page runs · no run button exists
        </p>
      </section>

      <section class="mt-10 grid gap-8 border-t border-line-subtle pt-8 lg:grid-cols-12 lg:gap-12">
        <div class="lg:col-span-4">
          <h2 class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">The question it answers</h2>
        </div>
        <div class="lg:col-span-8">
          <p class="max-w-[60ch] text-[13.5px] leading-relaxed text-ink">{{ path.question }}</p>
          <div class="mt-5 border-t border-line-subtle pt-4">
            <p :class="[MONO_LABEL, 'text-ink-faint']">For example</p>
            <p class="mt-1.5 max-w-[60ch] text-[12.5px] leading-relaxed text-ink-muted">{{ path.example }}</p>
          </div>
        </div>
      </section>

      <section class="mt-12 border-t border-line-subtle pt-8">
        <div class="flex flex-wrap items-baseline justify-between gap-3">
          <h2 class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">How it will work</h2>
          <span :class="[MONO_LABEL, 'text-ink-muted']">{{ path.steps.length }} steps</span>
        </div>
        <ol class="mt-5">
          <li
            v-for="(step, i) in path.steps"
            :key="step.title"
            class="flex items-start gap-3.5 rounded-md border border-dashed border-line-subtle px-4 py-3.5 [&+li]:mt-2"
          >
            <span class="mono mt-[1px] grid h-5 w-5 shrink-0 place-items-center rounded border border-dashed border-line text-[12px] text-ink-faint">
              {{ i + 1 }}
            </span>
            <span class="min-w-0 flex-1">
              <span class="block text-[13px] font-medium text-ink">{{ step.title }}</span>
              <span class="mt-1 block max-w-[64ch] text-[12.5px] leading-relaxed text-ink-muted">
                {{ step.detail }}
              </span>
            </span>
            <span :class="[MONO_LABEL, 'hidden shrink-0 text-ink-faint sm:inline']">not runnable</span>
          </li>
        </ol>
      </section>

      <section class="mt-12 border-t border-line-subtle pt-8">
        <h2 class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">These steps become canvas modules</h2>
        <p class="mt-2.5 max-w-[64ch] text-[13px] leading-relaxed text-ink-muted">
          Each step above is one block on the workflow canvas, pre-filled so only the dataset and
          the columns are left to pick. The canvas is a sketch too — see it under Canvas.
        </p>
      </section>
    </template>
  </div>
</template>
