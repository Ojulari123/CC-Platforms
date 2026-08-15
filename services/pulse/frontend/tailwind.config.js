/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./components/**/*.{vue,js,ts}",
    "./pages/**/*.{vue,js,ts}",
    "./layouts/**/*.{vue,js,ts}",
    // statusClass() and the status tones return utility strings, so the files that
    // build them have to be scanned too.
    "./utils/**/*.{js,ts}",
    "./composables/**/*.{js,ts}",
    "./app.vue",
    // The shared layer, per directory rather than a blanket `packages/ui/**`: the
    // blanket form also walks node_modules, which Tailwind warns about. Missing these
    // fails quietly — the shared components lose their token colours and fall back to
    // Tailwind's default blue ring, and TickRuler draws nothing.
    "../../../packages/ui/components/**/*.{vue,ts}",
    "../../../packages/ui/pages/**/*.vue",
    "../../../packages/ui/composables/**/*.ts",
    "../../../packages/ui/utils/**/*.ts",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
};
