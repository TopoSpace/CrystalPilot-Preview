/** Playwright end-to-end harness for the workbench (round-2 plan R0).
 *
 * Drives the REAL server at http://127.0.0.1:8010 (never a mock), reusing the
 * installed Edge (channel "msedge": no browser download). Screenshots are the
 * evidence trail: they land in workdir/ui-evidence/<round>/ and are indexed by
 * docs/UI-EVIDENCE-2026-09.md. Run: `npm run e2e` (optionally
 * CP_EVIDENCE_ROUND=r1 CP_E2E_PROJECT=<path>). */
import { defineConfig } from "@playwright/test";

/** Interface language under test: CP_E2E_LANG=en drives the English
 * interface; the default is Chinese. The specs read their expected texts
 * from the same dictionaries the interface renders (e2e/lang.ts). */
const LANG = process.env.CP_E2E_LANG === "en" ? "en" : "zh";
const BASE_URL = process.env.CP_BASE_URL ?? "http://127.0.0.1:8010";

export default defineConfig({
  testDir: "./e2e",
  testMatch: /.*\.pw\.ts$/,
  timeout: 120_000,
  expect: { timeout: 20_000 },
  retries: 0,
  workers: 1, // resource frugality: one browser, one server
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "../workdir/ui-evidence/_playwright-report" }],
  ],
  outputDir: "../workdir/ui-evidence/_test-results",
  use: {
    baseURL: BASE_URL,
    // the language is read from localStorage before first paint (ui/index.html)
    storageState: {
      cookies: [],
      origins: [{ origin: BASE_URL, localStorage: [{ name: "crystalpilot-language", value: LANG }] }],
    },
    channel: process.env.CP_BROWSER_CHANNEL ?? (process.platform === "win32" ? "msedge" : "chrome"),
    headless: true,
    viewport: { width: 1600, height: 1000 },
    // headless WebGL for the 3Dmol viewer (same flags the manual Edge
    // screenshots needed during the 2026-09-04 inventory)
    launchOptions: { args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] },
    screenshot: "off",
    video: "off",
    trace: "retain-on-failure",
  },
});
