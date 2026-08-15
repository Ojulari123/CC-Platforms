import { defineConfig, mergeConfig } from "vitest/config";
import { uiTestConfig } from "../../../packages/ui/vitest.shared";

// No node builtins here: `nuxt typecheck` compiles this file with the app's tsconfig,
// which loads no ambient @types, so `node:url` does not resolve. decodeURIComponent
// covers paths with spaces — the same shape packages/ui uses.
const here = decodeURIComponent(new URL(".", import.meta.url).pathname).replace(/\/$/, "");

// Vitest runs outside Nuxt, so the two aliases Nuxt resolves at build time have to be
// declared here. Components and utils under test import from them explicitly for the
// same reason: an auto-import is not there when the component is mounted on its own.
export default mergeConfig(
  uiTestConfig(import.meta.url),
  defineConfig({
    resolve: {
      alias: {
        "@crescent/ui": `${here}/../../../packages/ui`,
        "~": here,
      },
    },
  }),
);
