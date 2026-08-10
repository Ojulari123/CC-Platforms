<script setup lang="ts">
import { findLearningPath } from "~/constants/learningPaths";

definePageMeta({ middleware: "auth" });

const route = useRoute();
const path = computed(() => findLearningPath(route.params.slug as string));
</script>

<template>
  <div class="mx-auto max-w-3xl px-4 py-8">
    <header class="mb-6">
      <NuxtLink to="/learning" class="text-sm text-gray-500 hover:underline">
        &larr; All learning paths
      </NuxtLink>
    </header>

    <p v-if="!path" class="text-sm text-gray-600">
      There's no learning path by that name.
    </p>

    <div v-else>
      <h1 class="text-xl font-semibold">{{ path.title }}</h1>
      <p class="mt-1 text-sm text-gray-500">{{ path.summary }}</p>

      <div class="mt-6 rounded-lg border border-amber-200 bg-amber-50 p-4">
        <p class="text-sm font-medium text-amber-900">Not built yet</p>
        <p class="mt-1 text-sm text-amber-800">
          This page describes the path so you know what's coming. The steps below aren't
          clickable and nothing runs — that's Week 6 work. In the meantime you can upload
          a CSV and preview it from
          <NuxtLink to="/datasets" class="underline">Datasets</NuxtLink>.
        </p>
      </div>

      <section class="mt-8">
        <h2 class="text-sm font-semibold text-gray-800">The question it answers</h2>
        <p class="mt-1 text-sm text-gray-600">{{ path.question }}</p>
        <p class="mt-3 text-sm text-gray-500">{{ path.example }}</p>
      </section>

      <section class="mt-8">
        <h2 class="mb-3 text-sm font-semibold text-gray-800">How it will work</h2>
        <ol class="space-y-4">
          <li
            v-for="(step, index) in path.steps"
            :key="step.title"
            class="flex gap-3 rounded-lg border border-gray-200 bg-white p-4"
          >
            <span
              class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-gray-100 text-xs font-medium text-gray-600"
            >
              {{ index + 1 }}
            </span>
            <div>
              <p class="text-sm font-medium">{{ step.title }}</p>
              <p class="mt-0.5 text-sm text-gray-500">{{ step.detail }}</p>
            </div>
          </li>
        </ol>
      </section>

      <section class="mt-8 rounded-lg border border-gray-200 bg-white p-5">
        <p class="text-sm font-medium">These steps become canvas modules</p>
        <p class="mt-1 text-sm text-gray-500">
          Each step above is one block on the workflow canvas.
          <NuxtLink to="/canvas" class="font-medium text-gray-900 hover:underline">
            See the canvas sketch
          </NuxtLink>
        </p>
      </section>
    </div>
  </div>
</template>
