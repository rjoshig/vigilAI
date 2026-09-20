/**
 * Start the worker, once the database exists.
 *
 * The database is wiped and seeded by the API's own web-server command, not here:
 * Playwright starts the web servers **before** it runs global setup, so seeding here
 * handed the API the previous run's database file and then deleted it underneath.
 * SQLite keeps a deleted file open, so the whole suite then read and wrote a database
 * nothing else could see. Global setup runs after the servers are up, which makes it
 * the right place for the worker and the wrong place for the seed.
 *
 * The worker has no URL for Playwright to poll, so it is spawned here and stopped in
 * `global-teardown.ts`; without it a newly submitted run would sit at "queued" forever.
 *
 * Nothing here reaches a model: `LLM_PROVIDER=mock` and the scripted stand-in answer
 * every stage (ADR-003, ADR-014).
 */

import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

import { DATA_DIR, PYTHON, ROOT, SERVICE_ENV } from "./playwright.config";

/** Where the worker's process id is left for teardown. */
export const WORKER_PID_FILE = path.join(DATA_DIR, "worker.pid");

export default async function globalSetup(): Promise<void> {
  if (!fs.existsSync(PYTHON)) {
    throw new Error(
      `No Python at ${PYTHON}. Create the virtualenv (see CLAUDE.md "Local environment") ` +
        "or set E2E_PYTHON to one that has the package installed."
    );
  }

  const worker = spawn(PYTHON, ["-m", "greenlight_ai.worker.app"], {
    cwd: ROOT,
    env: SERVICE_ENV,
    stdio: "ignore",
    detached: true,
  });
  worker.unref();
  if (worker.pid) fs.writeFileSync(WORKER_PID_FILE, String(worker.pid), "utf-8");
}
