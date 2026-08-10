/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./components/**/*.{vue,js,ts}",
    "./pages/**/*.{vue,js,ts}",
    "./layouts/**/*.{vue,js,ts}",
    "./app.vue",
    // Pages that come from the shared layer (password reset, invite accept).
    "../../../packages/ui/**/*.{vue,js,ts}",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
};
