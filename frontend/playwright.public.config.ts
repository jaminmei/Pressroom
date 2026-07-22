import { defineConfig } from "@playwright/test";

const baseURL = process.env.PW_BASE_URL?.trim() || "http://127.0.0.1:5173";
const runId = process.env.PW_RUN_ID?.trim();

export default defineConfig({
  testDir: "./e2e/public",
  fullyParallel: false,
  timeout: 240_000,
  outputDir: runId ? `test-results/${runId}/public` : "test-results/public",
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  expect: {
    timeout: 20_000,
  },
  use: {
    baseURL,
    headless: true,
    viewport: { width: 1440, height: 900 },
    actionTimeout: 20_000,
    navigationTimeout: 60_000,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "retain-on-failure",
  },
  workers: 1,
  projects: [
    {
      name: "chromium",
      use: {
        browserName: "chromium",
        launchOptions: {
          args: ["--no-sandbox"],
        },
        chromiumSandbox: false,
      },
    },
  ],
});
