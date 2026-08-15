import { defineConfig, mergeConfig } from "vitest/config";
import { uiTestConfig } from "../../../packages/ui/vitest.shared";

// decodeURIComponent covers the space in the checkout path.
const root = decodeURIComponent(new URL(".", import.meta.url).pathname).replace(/\/$/, "");

// The layer supplies the plugin, the environment and the setup file; this adds the two
// aliases Nuxt would otherwise resolve for us.
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
