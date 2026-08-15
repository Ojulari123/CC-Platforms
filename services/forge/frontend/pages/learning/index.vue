<script setup lang="ts">
import { MONO_LABEL } from "@crescent/ui/utils/ui";
import { LEARNING_PATHS } from "~/constants/learningPaths";

definePageMeta({ middleware: "auth" });

// The cards are live links to a written description, so they take a solid hairline.
// The dashed border is reserved for the marker on the thing that does not run.
const WEEK6_TAG = `${MONO_LABEL} inline-flex shrink-0 items-center rounded border border-dashed border-line px-2 py-[3px] text-ink-muted`;
</script>

<template>
  <div>
    <section>
      <Eyebrow>Forge · learning paths</Eyebrow>
      <h1 class="mt-3 max-w-[24ch] text-[clamp(1.5rem,2.2vw,1.9rem)] font-semibold tracking-[-0.035em]">
        Four routes from a dataset to an answer
      </h1>
      <p class="mt-3 max-w-[64ch] text-[13px] leading-relaxed text-ink-muted">
        Each page below describes what a path will do and the steps it takes. None of them run.
        Nothing here trains a model, and no ML libraries are installed. Uploading a CSV and
        reading it back is what works today.
      </p>
      <p :class="[MONO_LABEL, 'mt-5 border-y border-line-subtle py-3 text-ink-muted']">
        specification only · week 6 · no run affordance anywhere on these pages
      </p>
    </section>

    <section class="mt-10 border-t border-line-subtle pt-8">
      <ul class="grid gap-3 sm:grid-cols-2">
        <li v-for="path in LEARNING_PATHS" :key="path.slug">
          <NuxtLink
            :to="`/learning/${path.slug}`"
            :class="[FOCUS, TAP, 'block h-full rounded-md bg-surface/25 p-5 ring-1 ring-inset ring-line-subtle transition-colors hover:bg-surface-hover/50 hover:ring-line']"
          >
            <div class="flex flex-wrap items-center justify-between gap-3">
              <h2 class="text-[15px] font-semibold tracking-[-0.015em]">{{ path.title }}</h2>
              <span :class="WEEK6_TAG">Week 6 · not built</span>
            </div>
            <p class="mt-2.5 max-w-[52ch] text-[13px] leading-relaxed text-ink-muted">{{ path.summary }}</p>
            <p :class="[MONO_LABEL, 'mt-4 text-ink-muted']">{{ path.steps.length }} steps · read only</p>
          </NuxtLink>
        </li>
      </ul>
    </section>
  </div>
</template>
