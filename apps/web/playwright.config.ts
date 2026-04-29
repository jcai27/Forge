import { defineConfig, devices } from "@playwright/test";
import path from "path";

const apiRoot = path.resolve(__dirname, "../api");
const apiBaseUrl = "http://127.0.0.1:8100";
const webBaseUrl = "http://127.0.0.1:3100";

export default defineConfig({
  testDir: "./e2e",
  testIgnore: ["**/real-preview-docker.spec.ts"],
  timeout: 120_000,
  workers: 1,
  expect: {
    timeout: 30_000,
  },
  fullyParallel: false,
  retries: process.env.CI ? 2 : 0,
  use: {
    baseURL: webBaseUrl,
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "uvicorn app.e2e_main:app --host 127.0.0.1 --port 8100",
      cwd: apiRoot,
      url: `${apiBaseUrl}/health`,
      reuseExistingServer: false,
      env: {
        ...process.env,
        PYTHONPATH: ".",
        ENVIRONMENT: "development",
        FRONTEND_URL: webBaseUrl,
        DATABASE_URL: "sqlite:///./verified-work-sample.e2e.db",
        RUNTIME_ROOT: "./.e2e/runtime",
        OBJECT_STORE_ROOT: "./.e2e/object-store",
        RUNTIME_BACKEND: "filesystem",
        RUNTIME_ALLOW_FILESYSTEM_FALLBACK: "true",
        RUNTIME_CLEANUP_ON_STARTUP: "false",
        RUNTIME_WORKER_EMBED_IN_API: "true",
        RUNTIME_WORKER_POLL_INTERVAL_SECONDS: "0.1",
      },
    },
    {
      command: "npm run build && npm run start -- --hostname 127.0.0.1 --port 3100",
      cwd: __dirname,
      url: webBaseUrl,
      reuseExistingServer: false,
      env: {
        ...process.env,
        NEXT_PUBLIC_API_BASE_URL: `${apiBaseUrl}/api`,
        API_PROXY_TARGET: apiBaseUrl,
      },
    },
  ],
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
      },
    },
  ],
});
