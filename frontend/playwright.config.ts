import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  timeout: 60000,
  use: { baseURL: "http://127.0.0.1:3001", trace: "retain-on-failure", channel: process.env.PLAYWRIGHT_CHANNEL },
  projects: [{ name: "desktop", use: { ...devices["Desktop Chrome"] } }, { name: "mobile", use: { ...devices["iPhone 13"], browserName: "chromium", viewport: { width: 375, height: 812 } } }],
  webServer: [
    { command: "../backend/.venv/bin/python -m uvicorn app.main:app --app-dir ../backend --host 127.0.0.1 --port 8001", url: "http://127.0.0.1:8001/health", reuseExistingServer: false, env: { APP_ENV: "test", STORAGE_MODE: "demo", DEMO_DB_PATH: "work/e2e.sqlite3", LEADFLOW_ENV_FILE: "work/e2e-admin.env", ALLOWED_ORIGINS: "http://127.0.0.1:3001", RATE_LIMIT_PER_MINUTE: "1000", AUTH_RATE_LIMIT_PER_MINUTE: "100" } },
    { command: "npm run dev -- --port 3001", url: "http://127.0.0.1:3001", reuseExistingServer: false, env: { NEXT_PUBLIC_API_URL: "http://127.0.0.1:8001", LEADFLOW_API_URL: "http://127.0.0.1:8001", LEADFLOW_E2E: "1", NEXT_TELEMETRY_DISABLED: "1" }, timeout: 120000 },
  ],
});
