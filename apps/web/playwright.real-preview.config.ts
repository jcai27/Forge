import { defineConfig, devices } from "@playwright/test";
import path from "path";

const apiRoot = path.resolve(__dirname, "../api");
const apiBaseUrl = "http://127.0.0.1:8200";
const webBaseUrl = "http://127.0.0.1:3200";

export default defineConfig({
  testDir: "./e2e",
  timeout: 240_000,
  workers: 1,
  expect: {
    timeout: 60_000,
  },
  fullyParallel: false,
  retries: 0,
  use: {
    baseURL: webBaseUrl,
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "uvicorn app.main:app --host 127.0.0.1 --port 8200",
      cwd: apiRoot,
      url: `${apiBaseUrl}/health`,
      reuseExistingServer: false,
      env: {
        ...process.env,
        PYTHONPATH: ".",
        ENVIRONMENT: "development",
        FRONTEND_URL: webBaseUrl,
        DATABASE_URL: "sqlite:///./verified-work-sample.real-preview.db",
        RUNTIME_ROOT: "./.e2e-real/runtime",
        OBJECT_STORE_ROOT: "./.e2e-real/object-store",
        RUNTIME_BACKEND: "docker",
        RUNTIME_ALLOW_FILESYSTEM_FALLBACK: "false",
        RUNTIME_CLEANUP_ON_STARTUP: "false",
        RUNTIME_WORKER_POLL_INTERVAL_SECONDS: "0.1",
        PREVIEW_PORT_START: "41200",
        PREVIEW_PORT_END: "41220",
      },
    },
    {
      command: "npm run build && npm run start -- --hostname 127.0.0.1 --port 3200",
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
