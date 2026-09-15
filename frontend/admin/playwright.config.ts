import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results",
  fullyParallel: false,
  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI
    ? [["html", { outputFolder: "playwright-report", open: "never" }], ["json", { outputFile: "test-results/report.json" }], ["line"]]
    : [["list"], ["html", { outputFolder: "playwright-report", open: "never" }], ["json", { outputFile: "test-results/report.json" }]],
  use: {
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  webServer: {
    command: "NEXT_TELEMETRY_DISABLED=1 npm run dev",
    url: "http://localhost:3000",
    timeout: 180_000,
    reuseExistingServer: !process.env.CI,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
