/**
 * Stop the worker that `global-setup.ts` started.
 *
 * Playwright stops the servers it started itself; the worker has no URL, so it is ours
 * to clean up. A worker left running would hold the database file open and quietly
 * process the next run's jobs.
 */

import fs from "node:fs";

import { WORKER_PID_FILE } from "./global-setup";

export default async function globalTeardown(): Promise<void> {
  if (!fs.existsSync(WORKER_PID_FILE)) return;
  const pid = Number(fs.readFileSync(WORKER_PID_FILE, "utf-8").trim());
  fs.rmSync(WORKER_PID_FILE, { force: true });
  if (!Number.isFinite(pid)) return;
  try {
    process.kill(pid, "SIGTERM");
  } catch {
    // Already gone, which is the outcome we wanted.
  }
}
