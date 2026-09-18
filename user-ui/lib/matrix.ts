/**
 * Building the traceability matrix from the three things the API returns separately.
 *
 * Pulled out of the component so the join is testable on its own: it is the piece a
 * reviewer trusts most, and a wrong row would quietly mislead them.
 */

import { matrixStatus, type MatrixStatus } from "@/lib/display";
import type { ConfigElementOut, Finding, Requirements, Rule, Trace } from "@/lib/types";

export interface MatrixRow {
  rule: Rule;
  trace: Trace | null;
  element: ConfigElementOut | null;
  status: MatrixStatus;
  findings: Finding[];
}

/**
 * Join rules, traces, elements, and findings into one row per requirement.
 *
 * @param requirements What `GET /runs/{id}/requirements` returned.
 * @param findings What `GET /runs/{id}/findings` returned.
 * @returns One row per rule, in the order the rules arrived.
 */
export function buildMatrix(requirements: Requirements, findings: Finding[]): MatrixRow[] {
  const traceByRule = new Map(requirements.traces.map((trace) => [trace.rule_id, trace]));
  const elementById = new Map(
    requirements.elements.map((element) => [element.element_id, element])
  );

  const findingsByRule = new Map<string, Finding[]>();
  for (const finding of findings) {
    if (!finding.rule_ref) continue;
    const bucket = findingsByRule.get(finding.rule_ref) ?? [];
    bucket.push(finding);
    findingsByRule.set(finding.rule_ref, bucket);
  }

  return requirements.rules.map((rule) => {
    const trace = traceByRule.get(rule.rule_id) ?? null;
    const element = trace?.element_id ? (elementById.get(trace.element_id) ?? null) : null;
    const ruleFindings = findingsByRule.get(rule.rule_id) ?? [];
    return {
      rule,
      trace,
      element,
      status: matrixStatus(
        trace,
        ruleFindings.map((f) => f.type)
      ),
      findings: ruleFindings,
    };
  });
}

/** Count the rows in each matrix status, for the filter chips. */
export function countByStatus(rows: MatrixRow[]): Record<MatrixStatus, number> {
  const counts: Record<MatrixStatus, number> = {
    match: 0,
    mismatch: 0,
    partial: 0,
    missing: 0,
    extra: 0,
  };
  for (const row of rows) counts[row.status] += 1;
  return counts;
}

/** Render a rule's payload as the short text the matrix shows in the OSL column. */
export function ruleValues(rule: Rule): string {
  const payload = rule.rule as {
    values?: string[];
    steps?: string[];
    quantity?: number | null;
    conditions?: { field_name: string; operator: string; value: unknown }[];
  };
  if (payload.values?.length) return payload.values.join(", ");
  if (payload.steps?.length) return payload.steps.join(" → ");
  if (payload.quantity !== null && payload.quantity !== undefined) return String(payload.quantity);
  if (payload.conditions?.length) {
    return payload.conditions
      .map((c) => `${c.field_name} ${c.operator} ${String(c.value)}`)
      .join(" AND ");
  }
  return "—";
}
