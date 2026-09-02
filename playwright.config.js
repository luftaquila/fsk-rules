const { defineConfig, devices } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./tests/browser",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://127.0.0.1:8765",
    trace: "on-first-retry"
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile-320", use: { ...devices["Pixel 7"], viewport: { width: 320, height: 720 } } },
    { name: "mobile-375", use: { ...devices["Pixel 7"], viewport: { width: 375, height: 812 } } },
    { name: "mobile-414", use: { ...devices["Pixel 7"], viewport: { width: 414, height: 896 } } },
    { name: "tablet-768", use: { ...devices["Desktop Chrome"], viewport: { width: 768, height: 1024 } } }
  ],
  webServer: {
    command: "python3 -m http.server 8765 --directory _site",
    url: "http://127.0.0.1:8765/rules-manifest.json",
    reuseExistingServer: !process.env.CI
  }
});
