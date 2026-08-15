import { defineConfig, mergeConfig } from "vitest/config";
import { uiTestConfig } from "../../../packages/ui/vitest.shared";

// The layer's setup, plus the two aliases Nuxt resolves for us at runtime and Vitest
// does not: `@crescent/ui` for the shared components, `~` for this app's own files.
const root = decodeURIComponent(new URL(".", import.meta.url).pathname).replace(/\/$/, "");

export default mergeConfig(
  uiTestConfig(import.meta.url),
  defineConfig({
    resolve: {
      alias: {
        "@crescent/ui": `${root}/../../../packages/ui`,
        "~": root,
      },
    },
  }),
);
