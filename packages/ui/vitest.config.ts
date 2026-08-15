import { defineConfig } from "vitest/config";
import { uiTestConfig } from "./vitest.shared";

export default defineConfig(uiTestConfig(import.meta.url));
