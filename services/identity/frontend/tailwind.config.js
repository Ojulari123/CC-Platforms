/* The shared components live in packages/ui, outside this app's directory, so Tailwind
   has to be told to scan them: a class that only ever appears inside TopBar or TickRuler
   is otherwise never generated. The failure is quiet and looks like a component bug —
   default blue focus rings instead of the token colour, and a ruler that draws no ticks.

   Per-directory globs on purpose. A blanket `packages/ui/**` also matches node_modules,
   which Tailwind warns about and which makes every rebuild slow.

   The theme itself is in packages/ui/tailwind.config.js and is merged in from the layer. */

// Absolute, because Tailwind resolves relative globs against the working directory rather
// than against this file. decodeURIComponent covers the space in the checkout path.
const appDir = decodeURIComponent(new URL(".", import.meta.url).pathname).replace(/\/$/, "");
const uiDir = `${appDir}/../../../packages/ui`;

/** @type {import('tailwindcss').Config} */
export default {
  content: [
    `${appDir}/components/**/*.{vue,js,ts}`,
    `${appDir}/composables/**/*.{js,ts}`,
    `${appDir}/layouts/**/*.vue`,
    `${appDir}/pages/**/*.vue`,
    `${appDir}/utils/**/*.{js,ts}`,
    `${appDir}/app.vue`,
    `${appDir}/error.vue`,
    `${uiDir}/components/**/*.{vue,js,ts}`,
    `${uiDir}/composables/**/*.{js,ts}`,
    `${uiDir}/pages/**/*.vue`,
    `${uiDir}/utils/**/*.{js,ts}`,
  ],
};
