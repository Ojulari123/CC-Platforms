import { defineConfig, mergeConfig } from "vitest/config";
import { uiTestConfig } from "./vitest.shared";

/* `css: true` only so test/tokens.spec.ts can read tokens.css as text. Vitest stubs every
   `.css` import by default and the stub is chosen by extension, so it swallows `?raw` too
   and the file arrives as an empty string. Set here rather than in vitest.shared.ts: the
   three apps have no reason to start processing stylesheets in their tests. */
export default mergeConfig(defineConfig(uiTestConfig(import.meta.url)), defineConfig({ test: { css: true } }));
