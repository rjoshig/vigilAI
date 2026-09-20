/**
 * Seed a throwaway stack, then start the worker.
 *
 * The seeder produces runs in every lifecycle state, so the tests read a stack that
 * already looks like a working day. The worker has no URL for Playwright to poll, so it
 * is spawned here and stopped in `global-teardown.ts`; without it a newly submitted run
 * would sit at "queued" forever.
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

/**
 * Run a command to completion, failing loudly.
 *
 * @param command - The executable.
 * @param args - Its arguments.
 * @param label - What to call it in an error.
 */
function run(command: string, args: string[], label: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd: ROOT, env: SERVICE_ENV, stdio: "inherit" });
    child.on("error", reject);
    child.on("exit", (code) =>
      code === 0 ? resolve() : reject(new Error(`${label} exited with ${code}`))
    );
  });
}

export default async function globalSetup(): Promise<void> {
  if (!fs.existsSync(PYTHON)) {
    throw new Error(
      `No Python at ${PYTHON}. Create the virtualenv (see CLAUDE.md "Local environment") ` +
        "or set E2E_PYTHON to one that has the package installed."
    );
  }

  // A fresh database every run. These tests finalize runs and approve rules, which are
  // one-way, so reusing a database would make the second run fail for reasons that
  // have nothing to do with the code.
  fs.rmSync(DATA_DIR, { recursive: true, force: true });
  fs.mkdirSync(DATA_DIR, { recursive: true });

  await run(PYTHON, [path.join(ROOT, "scripts", "seed_demo.py"), "--log-level", "ERROR"], "seeder");

  const worker = spawn(PYTHON, ["-m", "greenlight_ai.worker.app"], {
    cwd: ROOT,
    env: SERVICE_ENV,
    stdio: "ignore",
    detached: true,
  });
  worker.unref();
  if (worker.pid) fs.writeFileSync(WORKER_PID_FILE, String(worker.pid), "utf-8");
}
