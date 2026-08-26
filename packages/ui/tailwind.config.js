/* The apps run Tailwind 3.4 (`@nuxtjs/tailwindcss` 6.x), not the prototype's v4, so the
   `@theme inline` block in the prototype's index.css becomes this config. The custom
   properties themselves live in assets/css/tokens.css.

   `@nuxtjs/tailwindcss` loads a `tailwind.config` from every Nuxt layer and merges it,
   so all three apps inherit this without touching their own configs. */

/* Tailwind 3 opacity modifiers (`bg-app/85`, `ring-bad/30`) need to be able to insert
   an alpha into the colour. The tokens are `oklch()` strings behind a custom property,
   which the `rgb(var(--x) / <alpha-value>)` trick cannot take apart, so `color-mix`
   does it instead. Every browser that understands `oklch()` understands `color-mix`. */
const token = (name) => ({ opacityValue } = {}) =>
  opacityValue === undefined
    ? `var(--${name})`
    : `color-mix(in oklch, var(--${name}) calc(${opacityValue} * 100%), transparent)`;

// Content globs must be absolute: Tailwind resolves relative ones against the app's
// working directory, not this file. decodeURIComponent covers paths with spaces.
const layerDir = decodeURIComponent(new URL(".", import.meta.url).pathname).replace(/\/$/, "");

/** @type {import('tailwindcss').Config} */
export default {
  content: [
    `${layerDir}/components/**/*.{vue,js,ts}`,
    `${layerDir}/composables/**/*.{js,ts}`,
    `${layerDir}/layouts/**/*.{vue,js,ts}`,
    `${layerDir}/pages/**/*.{vue,js,ts}`,
    `${layerDir}/utils/**/*.{js,ts}`,
  ],
  theme: {
    extend: {
      colors: {
        app: token("app"),
        sunken: token("sunken"),
        surface: {
          DEFAULT: token("surface"),
          hover: token("surface-hover"),
          active: token("surface-active"),
        },
        line: {
          DEFAULT: token("line"),
          subtle: token("line-subtle"),
          strong: token("line-strong"),
        },
        ink: {
          DEFAULT: token("ink"),
          muted: token("ink-muted"),
          faint: token("ink-faint"),
          disabled: token("ink-disabled"),
        },
        accent: {
          DEFAULT: token("accent"),
          hover: token("accent-hover"),
          ink: token("accent-ink"),
          surface: token("accent-surface"),
        },
        ok: { DEFAULT: token("ok"), surface: token("ok-surface") },
        warn: { DEFAULT: token("warn"), surface: token("warn-surface") },
        bad: { DEFAULT: token("bad"), surface: token("bad-surface") },
        info: { DEFAULT: token("info"), surface: token("info-surface") },
      },
      fontFamily: {
        sans: ["var(--font-body)"],
        body: ["var(--font-body)"],
        heading: ["var(--font-heading)"],
        mono: ["var(--font-mono)"],
      },
      /* One elevation, theme-aware, for anything that floats over the page. Tailwind's
         own shadow scale is a black ramp and stays available, but nothing on this
         platform should reach for it — see the note in tokens.css. */
      boxShadow: {
        overlay: "var(--shadow-overlay)",
      },
      // 6px controls and containers, 4px chips, full on 6px dots and avatars. No others.
      borderRadius: {
        DEFAULT: "var(--radius-sm)",
        sm: "var(--radius-sm)",
        md: "var(--radius-md)",
        lg: "var(--radius-lg)",
        xl: "var(--radius-xl)",
      },
    },
  },
  plugins: [],
};
