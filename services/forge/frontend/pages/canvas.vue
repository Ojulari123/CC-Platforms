<script setup lang="ts">
definePageMeta({ middleware: "auth" });

// Static sketch. Nothing here is wired to the API; it exists to pin down the
// layout and vocabulary of the workflow builder before it gets built.
const modules = [
  { group: "Data in", items: ["Dataset", "Join", "Filter rows"] },
  { group: "Prepare", items: ["Drop columns", "Fill blanks", "Encode text"] },
  { group: "Model", items: ["Classify", "Regress", "Forecast"] },
  { group: "Results out", items: ["Score card", "Chart", "Export CSV"] },
];

const nodes = [
  { title: "Dataset", subtitle: "Monthly Sales (sample)", kind: "Data in" },
  { title: "Fill blanks", subtitle: "median for numeric columns", kind: "Prepare" },
  { title: "Forecast", subtitle: "6 periods ahead", kind: "Model" },
  { title: "Chart", subtitle: "history + forecast band", kind: "Results out" },
];
</script>

<template>
  <div class="mx-auto max-w-6xl px-4 py-8">
    <header class="mb-6">
      <h1 class="text-xl font-semibold">Workflow canvas</h1>
      <p class="mt-1 text-sm text-gray-500">
        Drag modules onto the canvas, connect them, and run the chain. This is the layout
        sketch, not the working builder.
      </p>
    </header>

    <div class="mb-8 rounded-lg border border-amber-200 bg-amber-50 p-4">
      <p class="text-sm font-medium text-amber-900">Preview of Week 6</p>
      <p class="mt-1 text-sm text-amber-800">
        Nothing on this page is clickable and no workflow runs. It's here so the module
        vocabulary and the shape of the builder are settled before the real one is wired
        up. Working features today: dataset upload and preview.
      </p>
    </div>

    <div class="grid gap-4 lg:grid-cols-[200px_1fr_240px]">
      <aside class="rounded-lg border border-gray-200 bg-white p-4">
        <p class="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-400">
          Modules
        </p>
        <div v-for="group in modules" :key="group.group" class="mb-4 last:mb-0">
          <p class="mb-1.5 text-xs font-medium text-gray-500">{{ group.group }}</p>
          <ul class="space-y-1">
            <li
              v-for="item in group.items"
              :key="item"
              class="cursor-not-allowed rounded-md border border-gray-200 bg-gray-50 px-2 py-1.5 text-sm text-gray-500"
            >
              {{ item }}
            </li>
          </ul>
        </div>
      </aside>

      <section
        class="rounded-lg border border-dashed border-gray-300 bg-[radial-gradient(circle,#d1d5db_1px,transparent_1px)] bg-[length:16px_16px] p-6"
      >
        <div class="flex flex-col items-center gap-1">
          <template v-for="(node, index) in nodes" :key="node.title">
            <div class="w-full max-w-xs rounded-lg border border-gray-300 bg-white p-3 shadow-sm">
              <p class="text-xs font-medium uppercase tracking-wide text-gray-400">
                {{ node.kind }}
              </p>
              <p class="mt-0.5 text-sm font-medium">{{ node.title }}</p>
              <p class="text-sm text-gray-500">{{ node.subtitle }}</p>
            </div>
            <div
              v-if="index < nodes.length - 1"
              class="text-gray-400"
              aria-hidden="true"
            >
              &darr;
            </div>
          </template>

          <div
            class="mt-4 w-full max-w-xs rounded-lg border border-dashed border-gray-300 px-3 py-6 text-center text-sm text-gray-400"
          >
            Drop a module here
          </div>
        </div>
      </section>

      <aside class="rounded-lg border border-gray-200 bg-white p-4">
        <p class="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-400">
          Selected step
        </p>
        <p class="text-sm font-medium">Forecast</p>
        <dl class="mt-3 space-y-2 text-sm">
          <div>
            <dt class="text-gray-500">Date column</dt>
            <dd class="text-gray-700">month</dd>
          </div>
          <div>
            <dt class="text-gray-500">Value column</dt>
            <dd class="text-gray-700">revenue</dd>
          </div>
          <div>
            <dt class="text-gray-500">Horizon</dt>
            <dd class="text-gray-700">6 periods</dd>
          </div>
        </dl>
        <button
          type="button"
          disabled
          class="mt-4 w-full cursor-not-allowed rounded-md bg-gray-900 px-3 py-2 text-sm font-medium text-white opacity-40"
        >
          Run workflow
        </button>
        <p class="mt-2 text-xs text-gray-400">Disabled until Week 6.</p>
      </aside>
    </div>

    <p class="mt-6 text-sm text-gray-500">
      Each
      <NuxtLink to="/learning" class="font-medium text-gray-900 hover:underline">
        learning path
      </NuxtLink>
      becomes one of these chains, pre-filled so you only pick the dataset and columns.
    </p>
  </div>
</template>
