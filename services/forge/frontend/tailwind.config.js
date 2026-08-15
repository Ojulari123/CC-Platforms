/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./components/**/*.{vue,js,ts}",
    "./constants/**/*.{js,ts}",
    "./layouts/**/*.{vue,js,ts}",
    "./pages/**/*.{vue,js,ts}",
    "./utils/**/*.{js,ts}",
    "./app.vue",
    // The shared layer's components, its `FOCUS`/`MONO_LABEL` class strings, and the
    // pages it ships (password reset, invite accept). Listed per directory rather than
    // as `packages/ui/**`, which swept that package's node_modules into every scan.
    "../../../packages/ui/components/**/*.{vue,js,ts}",
    "../../../packages/ui/composables/**/*.{js,ts}",
    "../../../packages/ui/layouts/**/*.{vue,js,ts}",
    "../../../packages/ui/pages/**/*.{vue,js,ts}",
    "../../../packages/ui/utils/**/*.{js,ts}",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
};
