/**
 * Browser tests over both apps against the seeded stack.
 *
 * Everything here runs against `LLM_PROVIDER=mock` and the scripted stand-in, so no
 * test reaches a real model (ADR-003, ADR-014). The database is a throwaway SQLite
 * file seeded by `scripts/seed_demo.py`, which produces runs in every lifecycle state,
 * so the tests read a stack that already looks like a working day rather than building
 * one screen at a time.
 *
 * The API and both apps are started by Playwright. The worker has no URL to poll, so
 * `global-setup.ts` spawns it and `global-teardown.ts` stops it.
 */

import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

/** The repository root, one level up from this directory. */
const ROOT = path.resolve(__dirname, "..");

/** Where the seeded database and the uploaded files live for this run. */
const DATA_DIR = process.env.GREENLIGHT_AI_DATA_DIR ?? path.join(ROOT, ".e2e-data");

/** The environment every service shares, so they see the same database. */
const SERVICE_ENV = {
  ...process.env,
  DATABASE_URL: process.env.DATABASE_URL ?? `sqlite+pysqlite:///${path.join(DATA_DIR, "e2e.db")}`,
  GREENLIGHT_AI_DATA_DIR: DATA_DIR,
  LLM_PROVIDER: "mock",
  PYTHONPATH: `${path.join(ROOT, "scripts")}${path.delimiter}${process.env.PYTHONPATH ?? ""}`,
};

/** The Python that has the package installed: the repo venv unless one is given. */
const PYTHON = process.env.E2E_PYTHON ?? path.join(ROOT, ".venv", "bin", "python");

export default defineConfig({
  testDir: "./tests",
  // One worker: every test shares one seeded database, and a test that finalizes a run
  // changes what another would see. Determinism is worth more than the wall clock here.
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : [["list"]],

  use: {
    baseURL: "http://127.0.0.1:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },

  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        // E2E_CHROMIUM lets an environment that already has a browser say where it is,
        // rather than every run downloading one. CI installs its own and leaves this
        // unset, in which case Playwright uses the browser it manages.
        ...(process.env.E2E_CHROMIUM
          ? { launchOptions: { executablePath: process.env.E2E_CHROMIUM } }
          : {}),
      },
    },
  ],

  globalSetup: "./global-setup.ts",
  globalTeardown: "./global-teardown.ts",

  webServer: [
    // The database is wiped and seeded **by this command**, not by global setup.
    // Playwright starts the web servers before it runs global setup, so seeding there
    // left the API holding the previous run's database file: SQLite keeps a deleted
    // file open, so every read and write went to the copy that had just been removed.
    // The symptom was a run that was already frozen before the test touched it, and
    // decisions that returned 200 and were nowhere afterwards. Seeding here happens
    // before the server binds, which is the only ordering that guarantees one database.
    //
    // `reuseExistingServer` is deliberately false everywhere for the same reason: a
    // server left over from an earlier run is attached to a database that no longer
    // exists and would carry its state into this one.
    {
      command:
        `rm -rf "${DATA_DIR}" && mkdir -p "${DATA_DIR}" && ` +
        `"${PYTHON}" "${path.join(ROOT, "scripts", "seed_demo.py")}" --log-level ERROR && ` +
        `"${PYTHON}" -m uvicorn greenlight_ai.api.app:get_app --factory --host 127.0.0.1 --port 8000`,
      url: "http://127.0.0.1:8000/health",
      cwd: ROOT,
      env: SERVICE_ENV,
      reuseExistingServer: false,
      timeout: 120_000,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: "npm run build && npm run start",
      url: "http://127.0.0.1:3000",
      cwd: path.join(ROOT, "user-ui"),
      env: { ...process.env, GREENLIGHT_AI_API_URL: "http://127.0.0.1:8000" },
      reuseExistingServer: false,
      timeout: 300_000,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: "npm run build && npm run start",
      url: "http://127.0.0.1:3001",
      cwd: path.join(ROOT, "admin-ui"),
      env: { ...process.env, GREENLIGHT_AI_API_URL: "http://127.0.0.1:8000" },
      reuseExistingServer: false,
      timeout: 300_000,
      stdout: "pipe",
      stderr: "pipe",
    },
  ],
});

export { DATA_DIR, PYTHON, ROOT, SERVICE_ENV };
