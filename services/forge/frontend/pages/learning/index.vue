<script setup lang="ts">
import { LEARNING_PATHS } from "~/constants/learningPaths";

definePageMeta({ middleware: "auth" });
</script>

<template>
  <div class="mx-auto max-w-4xl px-4 py-8">
    <header class="mb-6">
      <h1 class="text-xl font-semibold">Learning paths</h1>
      <p class="mt-1 text-sm text-gray-500">
        Four guided routes from a dataset to an answer. Pick the one that matches the
        question you're asking.
      </p>
    </header>

    <div class="mb-8 rounded-lg border border-amber-200 bg-amber-50 p-4">
      <p class="text-sm font-medium text-amber-900">These don't run yet</p>
      <p class="mt-1 text-sm text-amber-800">
        The pages below describe what each path will do and the steps involved. Nothing
        trains a model at the moment — that lands in Week 6. Uploading and previewing
        datasets works today.
      </p>
    </div>

    <div class="grid gap-4 sm:grid-cols-2">
      <NuxtLink
        v-for="path in LEARNING_PATHS"
        :key="path.slug"
        :to="`/learning/${path.slug}`"
        class="rounded-lg border border-gray-200 bg-white p-5 hover:border-gray-400"
      >
        <div class="flex items-center justify-between gap-2">
          <h2 class="text-sm font-semibold">{{ path.title }}</h2>
          <span class="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
            preview
          </span>
        </div>
        <p class="mt-1 text-sm text-gray-500">{{ path.summary }}</p>
        <p class="mt-3 text-xs text-gray-400">{{ path.steps.length }} steps</p>
      </NuxtLink>
    </div>
  </div>
</template>
