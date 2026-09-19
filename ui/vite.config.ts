import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// vite.config runs under Node; tsconfig only carries browser types.
declare const process: { env: Record<string, string | undefined> };

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      // the workbench server runs on 8010 (README, .claude/launch.json);
      // the old 8000 default made every dev-mode API call 404 in silence
      "/api": process.env.WB_API ?? "http://localhost:8010",
    },
  },
  build: {
    outDir: "dist",
    chunkSizeWarningLimit: 1600, // 3Dmol is intentionally a single lazy chunk
  },
  test: {
    // unit tests only; Playwright specs live in e2e/*.pw.ts and drive the
    // real server (npm run e2e)
    include: ["src/**/*.test.{ts,tsx}"],
    exclude: ["e2e/**", "node_modules/**", "dist/**"],
    // vitest empties every CSS request (including `index.css?raw`) unless
    // it is listed here; the theme contrast guard reads the raw stylesheet
    css: { include: [/\.css\?raw$/] },
  },
});
