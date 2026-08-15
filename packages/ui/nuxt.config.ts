
// Node builtins are off-limits here: Nuxt typechecks a layer's config with the app's
// tsconfig, which loads no ambient @types. decodeURIComponent covers paths with spaces.
const layerDir = decodeURIComponent(new URL(".", import.meta.url).pathname).replace(/\/$/, "");

const PREFIX_MISSING = [
  "[@crescent/ui] runtimeConfig.public.authStoragePrefix is empty.",
  "Every product on this layer must set it (Forge uses \"forge\", Pulse uses \"pulse\").",
  "It namespaces the localStorage token keys: changing or dropping it silently signs",
  "out every browser that already holds a session for this product.",
].join("\n");

export default defineNuxtConfig({
  // Tokens live in localStorage, which the server can't read, so SSR shipped protected
  // markup to logged-out visitors and bounced them client-side (layout flash + hydration
  // mismatch). Revisit if tokens ever move to httpOnly cookies (see docs/backlog.md).
  ssr: false,
  alias: {
    "@crescent/ui": layerDir,
  },
  // The design tokens and the motion rules, inherited by every product on this layer.
  // `@nuxtjs/tailwindcss` only auto-loads the *app's* assets/css/tailwind.css, so a
  // layer has to register its own stylesheets here. The tailwind.config.js next to this
  // file is picked up from the layer automatically and maps the tokens onto utilities.
  css: [`${layerDir}/assets/css/tokens.css`, `${layerDir}/assets/css/motion.css`],
  // This layer has no node_modules of its own, so `vue` doesn't resolve from a .vue
  // file living here and vue-tsc types every page in it as `{}`. Point at the
  // consuming app's copy; every product on this layer sits at services/*/frontend.
  typescript: {
    tsConfig: {
      compilerOptions: {
        paths: { vue: ["../node_modules/vue"] },
      },
    },
  },
  runtimeConfig: {
    public: {
      identityUrl: "http://localhost:8001",
      // Namespaces the stored tokens, so a product that already has sessions in
      // browsers can keep its existing keys when it moves onto this layer.
      // Intentionally has no usable default. See the `ready` hook below.
      authStoragePrefix: "",
    },
  },
  hooks: {
    // Fails `nuxt dev`/`build`/`typecheck` at startup rather than letting a product
    // that forgot the prefix boot on someone else's keys.
    ready(nuxt) {
      if (!nuxt.options.runtimeConfig.public.authStoragePrefix) {
        throw new Error(PREFIX_MISSING);
      }
    },
  },
});
