"""Stage 7: check the reports. Pure code, no LLM call.

Two things run here: the fixed per-``req_type`` report checks derived from each rule,
and the admin-defined expression checks over named values. A value that cannot be
resolved produces a "could not evaluate" finding; the run never skips a check silently
(``docs/design.md`` "Configurable checks").
"""

from __future__ import annotations

import logging
from typing import Any, Final, cast

from greenlight_ai.checks.definitions import AdminConfig
from greenlight_ai.checks.expressions import ExpressionError, UnresolvedValue, evaluate
from greenlight_ai.checks.named_values import NamedValue, resolve_all
from greenlight_ai.checks.field_constraints import FieldConstraintSpec
from greenlight_ai.checks.field_constraints import evaluate as evaluate_constraints
from greenlight_ai.checks.reports import REPORT_CHECKED_KINDS, CheckOutcome, run_derived_check
from greenlight_ai.pipeline.context import RunContext
from greenlight_ai.rules.derive import derive_checks
from greenlight_ai.rules.schema import Evidence, Finding, Severity

__all__ = ["run"]

_LOG: Final = logging.getLogger(__name__)

#: A report that contradicts a requirement is as serious as a config that does: the
#: delivery is already wrong.
_VIOLATION_SEVERITY: Final[Severity] = "high"


def run(context: RunContext) -> None:
    """Run the derived report checks and the admin checks.

    Args:
        context: The run context, whose ``findings`` this appends to. Its ``admin``
            field supplies the checks and named values, and ``customer`` scopes them.
    """
    settings = context.admin
    customer = context.customer
    before = len(context.findings)

    for rule in context.rules:
        for check in derive_checks(rule):
            if check.kind not in REPORT_CHECKED_KINDS:
                # Settled elsewhere: waterfall order is an OSL-against-config question
                # and stage 5 answers it.
                continue
            # A campaign can deliver the same report type several times, so a check
            # runs once per uploaded file and a finding names the one it came from
            # (ADR-021). "The field distribution is wrong" is useless when five were
            # uploaded.
            for documents, part_name in _views(context):
                outcome = run_derived_check(check, documents, context.aliases)
                if outcome.passed is True:
                    continue
                suffix = f" ({part_name})" if part_name else ""
                if outcome.passed is None:
                    context.add_finding(
                        Finding(
                            finding_id=context.next_finding_id(),
                            type="could_not_evaluate",
                            severity="review",
                            title=f"Could not check {check.description}{suffix}",
                            detail=outcome.detail,
                            leg="osl_reports",
                            rule_id=rule.rule_id,
                            evidence=_evidence(rule, outcome),
                        )
                    )
                    continue
                context.add_finding(
                    Finding(
                        finding_id=context.next_finding_id(),
                        type=(
                            "count_does_not_reconcile"
                            if check.kind == "counts_reconcile"
                            else "report_violates_rule"
                        ),
                        severity=_VIOLATION_SEVERITY,
                        title=(f"The delivery does not satisfy: {check.description}{suffix}"),
                        detail=outcome.detail,
                        leg="osl_reports",
                        rule_id=rule.rule_id,
                        evidence=_evidence(rule, outcome),
                    )
                )

    _check_deliverable_count(context)
    _run_field_constraints(context)
    _run_admin_checks(context, settings, customer)

    _LOG.info(
        "run %s stage 7: %d findings from report checks",
        context.run_id,
        len(context.findings) - before,
    )


def _run_field_constraints(context: RunContext) -> None:
    """Check the per-attribute rules a reviewer wrote in plain words (ADR-021).

    The sentence was the input to synthesis; what runs here is structured data
    compared by code, which is ADR-001 applied to a rule that came from a person.

    Args:
        context: The run context, whose ``findings`` this appends to.
    """
    specs = [
        spec for spec in context.admin.field_constraints if isinstance(spec, FieldConstraintSpec)
    ]
    if not specs:
        return

    for outcome in evaluate_constraints(specs, context.reports, context.aliases):
        if outcome.passed is True:
            continue
        ref = f"field_constraint:{outcome.spec.id}"
        shadow = ref in context.admin.shadow_rule_refs
        where = f" in {outcome.report_kind}" if outcome.report_kind else ""
        if outcome.passed is None:
            context.add_finding(
                Finding(
                    finding_id=context.next_finding_id(),
                    type="could_not_evaluate",
                    severity="review",
                    title=f"Could not check the rule for {outcome.spec.field}",
                    detail=outcome.detail,
                    leg="osl_reports",
                    rule_ref=ref,
                    shadow=shadow,
                    evidence=Evidence(report_name=outcome.report_kind, report_sheet=outcome.sheet),
                )
            )
            continue
        context.add_finding(
            Finding(
                finding_id=context.next_finding_id(),
                type="report_violates_rule",
                # Narrowed here rather than in the store: the column is a plain
                # string so a new severity needs no migration, and an unrecognised
                # one is a bug in whatever wrote the row.
                severity=cast(Severity, outcome.spec.severity),
                title=f"{outcome.spec.field}{where}: {outcome.detail}",
                detail=outcome.spec.reasoning or outcome.detail,
                leg="osl_reports",
                rule_ref=ref,
                shadow=shadow,
                evidence=Evidence(
                    report_name=outcome.report_kind,
                    report_sheet=outcome.sheet,
                    # Offending values only, capped, never a row (ADR-003).
                    report_value=", ".join(outcome.offending),
                ),
            )
        )


def _check_deliverable_count(context: RunContext) -> None:
    """Compare the declared deliverable count with the files that arrived.

    This is the point of asking for the number. A count the model is merely told is a
    count nobody verifies, so code compares it and a shortfall becomes a finding
    rather than a sentence in a prompt (ADR-021).

    Args:
        context: The run context, whose ``findings`` this may append to.
    """
    declared = context.guidance.deliverable_count
    if not declared:
        return

    uploaded = sum(len(parts) for parts in context.report_parts.values()) or len(context.reports)
    covered = context.guidance.outputs_validated or declared
    if uploaded >= covered:
        return

    context.add_finding(
        Finding(
            finding_id=context.next_finding_id(),
            type="deliverables_missing",
            severity="high",
            title=(
                f"The run declares {covered} output(s) to validate but {uploaded} "
                "report file(s) were uploaded"
            ),
            detail=(
                f"The campaign was described as having {declared} deliverable(s). "
                f"Validating {uploaded} of them leaves the rest unchecked, so this "
                "run cannot show that the delivery as a whole is correct."
            ),
            leg="osl_reports",
            # Counts only: this check reads no file content at all.
            evidence=Evidence(report_name="uploaded files"),
        )
    )


def _views(context: RunContext) -> list[tuple[dict[str, Any], str]]:
    """The sets of documents a check should be evaluated against.

    Args:
        context: The run context.

    Returns:
        One entry per combination of parts, each with the name to put in a finding.
        The ordinary case is a single file per kind, which gives exactly one entry
        with no name and therefore findings that read exactly as they did before.
        When one kind arrives several times, each of its parts is evaluated against
        the other kinds' first files, because a check spanning two reports has to
        pair them somehow and pairing every part of one with the single file of the
        other is the only reading that is never wrong.
    """
    parts = context.report_parts or {kind: [] for kind in context.reports}
    multiple = [kind for kind, items in parts.items() if len(items) > 1]
    if not multiple:
        return [(dict(context.reports), "")]

    views: list[tuple[dict[str, Any], str]] = []
    for kind in multiple:
        for part in parts[kind]:
            if part.document is None:
                continue
            documents = dict(context.reports)
            documents[kind] = part.document
            views.append((documents, part.name))
    return views


def _evidence(rule: object, outcome: CheckOutcome) -> Evidence:
    """Build evidence pointing at the report cell the check read.

    Args:
        rule: The originating rule.
        outcome: The check outcome.

    Returns:
        Evidence carrying the OSL reference and the report location. Aggregates only,
        never a row (ADR-003).
    """
    return Evidence(
        osl_ref=getattr(rule, "source_ref", ""),
        osl_text=getattr(rule, "source_text", ""),
        report_name=outcome.report_kind or "",
        report_sheet=outcome.sheet,
        report_cell=outcome.cell,
        report_value=outcome.observed,
    )


def _run_admin_checks(context: RunContext, admin: AdminConfig, customer: str) -> None:
    """Evaluate every in-scope admin expression check.

    Args:
        context: The run context.
        admin: The admin configuration.
        customer: The run's customer.
    """
    named = tuple(v for v in admin.named_values if isinstance(v, NamedValue))
    if not admin.checks:
        return
    values = resolve_all(named, context.reports)

    for check in admin.checks:
        if not check.applies_to(customer):
            continue
        if check.kind == "judgment":
            # Judgment checks are answered by the model in stage 8's style, and are out
            # of scope for Phase 2 (``docs/design.md``: "use sparingly").
            _LOG.info("skipping judgment check %r: not implemented in Phase 2", check.name)
            continue

        try:
            result = evaluate(check.expression, values)
        except UnresolvedValue as exc:
            context.add_finding(
                Finding(
                    finding_id=context.next_finding_id(),
                    type="could_not_evaluate",
                    severity="review",
                    title=f"Check {check.name!r} could not be evaluated",
                    detail=(
                        f"The named value {exc.name!r} could not be resolved in the "
                        f"reports supplied. {check.reasoning}"
                    ),
                    leg="config_reports",
                    evidence=Evidence(report_value=exc.name),
                )
            )
            continue
        except ExpressionError as exc:
            context.add_finding(
                Finding(
                    finding_id=context.next_finding_id(),
                    type="could_not_evaluate",
                    severity="review",
                    title=f"Check {check.name!r} is not a valid expression",
                    detail=f"{exc} Expression: {check.expression}",
                    leg="config_reports",
                )
            )
            continue

        if result.passed:
            continue
        inputs = ", ".join(f"{name} = {value}" for name, value in sorted(result.resolved.items()))
        context.add_finding(
            Finding(
                finding_id=context.next_finding_id(),
                type="cross_report_disagreement",
                severity=check.severity,
                title=f"Check {check.name!r} failed",
                detail=f"{check.reasoning} Expression {check.expression} was false with {inputs}.",
                leg="config_reports",
                evidence=Evidence(report_value=inputs),
            )
        )
