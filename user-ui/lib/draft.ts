/**
 * Turning a draft run back into the form that made it (Phase 6.23c).
 *
 * Cloning a run has always produced a draft prefilled with the submitter's fields, and
 * until this phase nothing could show it: the run page suppresses its whole body for a
 * draft, and the New run form read no run id. So a person clicked Clone, landed on a
 * blank-looking page and had nothing to do.
 *
 * The mapping lives here rather than in the page so it can be tested. `user-ui` has no
 * page-level tests; the convention is that the logic sits in `lib/` beside a test file
 * (`lib/matrix.ts`, `lib/matrix.test.ts`).
 */

import type { RunDetail } from "@/lib/types";

/** The form fields a draft can fill in. */
export interface DraftForm {
  customer: string;
  order: string;
  configurationId: string;
  creditDate: string;
  notes: string;
  scope: string;
  hasSuppressions: boolean;
  deliveryNotes: string;
}

/**
 * Read a draft into the shape the New run form holds in state.
 *
 * Every value is coerced to the empty string rather than left undefined, because the
 * inputs are controlled: a `null` credit date would turn a controlled field into an
 * uncontrolled one the first time somebody typed in it.
 */
export function draftToForm(run: RunDetail): DraftForm {
  return {
    customer: run.customer_name ?? "",
    order: run.order_number ?? "",
    configurationId: run.configuration_id ?? "",
    creditDate: run.credit_date ?? "",
    notes: run.notes ?? "",
    scope: run.scope ?? "",
    hasSuppressions: run.has_suppressions ?? false,
    deliveryNotes: run.delivery_notes ?? "",
  };
}

/**
 * What a draft already carries, by artifact kind.
 *
 * The form renders a slot per kind, so it needs to know which are already filled and
 * with what — `files` alone is a `{kind: filename}` map that cannot describe a slot
 * holding three field distributions.
 */
export function attachedByKind(run: RunDetail): Record<string, string[]> {
  const byKind: Record<string, string[]> = {};
  for (const file of run.files_detail ?? []) {
    byKind[file.kind] = byKind[file.kind] ?? [];
    byKind[file.kind].push(file.part_label || file.filename);
  }
  return byKind;
}

/**
 * How long a draft has left, in words.
 *
 * Forward-looking, where `fmtRelative` in `lib/utils.ts` looks back. A draft is deleted
 * by the ordinary retention sweep, so the countdown is the only warning a person gets
 * — there is deliberately no extend button and no email.
 */
export function expiresIn(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";
  const ms = at.getTime() - now.getTime();
  if (ms <= 0) return "expired";
  const days = Math.floor(ms / 86_400_000);
  if (days >= 1) return `expires in ${days} day${days === 1 ? "" : "s"}`;
  const hours = Math.floor(ms / 3_600_000);
  if (hours >= 1) return `expires in ${hours} hour${hours === 1 ? "" : "s"}`;
  // Never "expires in 0 days": a draft with minutes left should read as urgent.
  return "expires today";
}
