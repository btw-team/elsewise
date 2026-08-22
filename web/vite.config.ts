import { readFileSync } from "node:fs";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const packageMetadata = JSON.parse(
  readFileSync(new URL("../package.json", import.meta.url), "utf8"),
) as { version: string };

export default defineConfig({
  define: { __APP_VERSION__: JSON.stringify(packageMetadata.version) },
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: "./tests/setup.ts",
    testTimeout: 15_000,
  },
});
