import vue from "@vitejs/plugin-vue";
import type { UserConfig } from "vitest/config";

// The layer's test setup, exported so a service app can extend it instead of
// re-deriving one:
//
//   import { defineConfig, mergeConfig } from "vitest/config";
//   import { uiTestConfig } from "../../../packages/ui/vitest.shared";
//   export default mergeConfig(uiTestConfig(import.meta.url), defineConfig({ ... }));
//
// `root` is passed in so each app resolves its own test files and its own vue copy.
export function uiTestConfig(rootUrl: string): UserConfig {
  const root = decodeURIComponent(new URL(".", rootUrl).pathname).replace(/\/$/, "");
  return {
    plugins: [vue()],
    test: {
      root,
      environment: "happy-dom",
      globals: true,
      include: ["test/**/*.spec.ts"],
      setupFiles: [`${root}/test/setup.ts`],
      restoreMocks: true,
    },
  };
}
