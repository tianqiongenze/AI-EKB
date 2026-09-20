import { defineConfig } from "@playwright/test";

// E2E smoke against the full stack: control plane (8000) + admin console preview (4173).
// Browsers are installed on demand: `npx playwright install chromium`.
export default defineConfig({
  testDir: ".",
  timeout: 30_000,
  use: { baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:4173" },
  // LAN mode: E2E_BASE_URL points at the cluster NodePort and no local server
  // is started; local mode defaults to the admin preview on 4173.
  ...(process.env.E2E_BASE_URL
    ? []
    : [
        {
          command: "npm run build && npm run preview -- --port 4173 --strictPort",
          cwd: "../web/admin",
          url: "http://127.0.0.1:4173",
          reuseExistingServer: true,
          timeout: 120_000,
        },
      ]),
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
