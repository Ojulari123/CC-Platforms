<script setup lang="ts">
import { MONO_LABEL } from "@crescent/ui/utils/ui";
import { LEARNING_PATHS } from "~/constants/learningPaths";

definePageMeta({ middleware: "auth" });

/* The cards are live links to a written description, so they take a solid hairline. The
   dashed border marks the one thing here that is not built: the guided walkthrough. The
   tasks themselves all run on the canvas, so the marker must not be read as covering them. */
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
        All four routes run on the canvas today: attach a CSV, assemble the steps, train, score
        and read the Python it generates. What these pages do not do yet is walk you through one.
        Each describes the steps its task takes, and links to the canvas that runs it.
      </p>
      <p :class="[MONO_LABEL, 'mt-5 border-y border-line-subtle py-3 text-ink-muted']">
        the tasks run on the canvas · the guided walkthrough is not built
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
              <h2 class="text-[18px] font-semibold leading-tight tracking-[-0.02em] text-ink">{{ path.title }}</h2>
              <span :class="WEEK6_TAG">No walkthrough yet</span>
            </div>
            <p class="mt-2.5 max-w-[52ch] text-[13px] leading-relaxed text-ink-muted">{{ path.summary }}</p>
            <p :class="[MONO_LABEL, 'mt-4 text-ink-muted']">{{ path.steps.length }} steps · runs on the canvas</p>
          </NuxtLink>
        </li>
      </ul>
    </section>
  </div>
</template>
