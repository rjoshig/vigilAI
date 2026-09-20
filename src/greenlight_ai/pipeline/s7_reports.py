"""Stage 7: check the reports. Pure code, no LLM call.

Two things run here: the fixed per-``req_type`` report checks derived from each rule,
and the admin-defined expression checks over named values. A value that cannot be
resolved produces a "could not evaluate" finding; the run never skips a check silently
(``docs/design.md`` "Configurable checks").
"""

from __future__ import annotations

import logging
from typing import Any, Final, Mapping, cast

from greenlight_ai.checks.definitions import AdminConfig, CheckDefinition
from greenlight_ai.checks.expressions import ExpressionError, UnresolvedValue, evaluate
from greenlight_ai.checks.named_values import NamedValue, resolve_all
from greenlight_ai.checks.field_constraints import FieldConstraintSpec
from greenlight_ai.checks.field_constraints import evaluate as evaluate_constraints
from greenlight_ai.checks.reports import REPORT_CHECKED_KINDS, CheckOutcome, run_derived_check
from greenlight_ai.llm.client import LLMError
from greenlight_ai.llm.prompts import JUDGMENT_PROMPT
from greenlight_ai.llm.prompts.schemas import JudgmentResponse
from greenlight_ai.pipeline.guidance import preamble
from greenlight_ai.pipeline import coverage as coverage_module
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
    # A re-check runs this stage again; counting both passes would report twice the
    # coverage of a run that did the same work once (Phase 6.11c).
    context.coverage_record.clear()

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
                if outcome.passed is None:
                    context.coverage_record.unevaluated(rule.rule_id)
                else:
                    context.coverage_record.checked(rule.rule_id, outcome.report_kind or "")
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

    _check_programme(context)
    _check_credit_date(context)
    _check_deliverable_count(context)
    _run_field_constraints(context)
    _run_admin_checks(context, settings, customer)

    # Coverage is settled here, where every check that was going to run has run. It
    # is not a stage of its own: it computes nothing new, it reports what the stage
    # just did (Phase 6.11c).
    context.coverage = coverage_module.compute(context)

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
        if outcome.passed is not None:
            context.coverage_record.checked("", outcome.report_kind)
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


def _date_spellings(iso: str) -> tuple[str, ...]:
    """The ways a date is written in the documents we see.

    Args:
        iso: The date as ``YYYY-MM-DD``.

    Returns:
        Lowercase spellings to look for: ISO, slashed US and day-first forms with and
        without zero padding, and the month written out. A grep needs the spellings
        listed, because it will not infer them.
    """
    import datetime as dt

    try:
        day = dt.date.fromisoformat(iso)
    except ValueError:
        return (iso.lower(),)
    month_name = day.strftime("%B").lower()
    short = day.strftime("%b").lower()
    return tuple(
        dict.fromkeys(
            [
                iso,
                day.strftime("%m/%d/%Y"),
                day.strftime("%-m/%-d/%Y"),
                day.strftime("%d/%m/%Y"),
                day.strftime("%-d/%-m/%Y"),
                day.strftime("%Y%m%d"),
                day.strftime("%m-%d-%Y"),
                day.strftime("%d-%m-%Y"),
                f"{month_name} {day.day}, {day.year}",
                f"{day.day} {month_name} {day.year}",
                f"{short} {day.day}, {day.year}",
                f"{day.day} {short} {day.year}",
                f"{day.day}-{short}-{day.year}",
            ]
        )
    )


def _check_credit_date(context: RunContext) -> None:
    """Confirm the credit date the submitter gave appears in the artifacts (ADR-027).

    The reports are cut as of a credit date, and they usually say so in a cell. The
    submitter says which date this run is for; the two should agree. A date that
    appears nowhere is not proof of a wrong delivery, but it is exactly the thing a
    reviewer would want pointed out before signing.

    Args:
        context: The run context, whose ``findings`` this may append to.
    """
    iso = context.guidance.credit_date
    if not iso:
        return
    spellings = _date_spellings(iso)

    def contains(text: str) -> bool:
        lowered = text.lower()
        return any(spelling in lowered for spelling in spellings)

    in_reports = any(
        contains(sheet.name)
        or any(contains(header) for header in sheet.header)
        or any(
            contains(str(cell.value))
            for row in sheet.rows
            for cell in row
            if cell.value is not None
        )
        for document in context.reports.values()
        for sheet in document.sheets
    )
    if in_reports:
        return

    elsewhere = (
        context.osl is not None and any(contains(s.as_text()) for s in context.osl.sections)
    ) or (context.config is not None and any(contains(b.as_text()) for b in context.config.blocks))

    context.add_finding(
        Finding(
            finding_id=context.next_finding_id(),
            type="credit_date_missing",
            severity="low" if elsewhere else "medium",
            title=(
                f"Credit date {iso} appears in the OSL or configuration but in no report"
                if elsewhere
                else f"Credit date {iso} appears in none of the artifacts"
            ),
            detail=(
                "Looked for the date as "
                + ", ".join(spellings[:6])
                + " and more, in every report cell, sheet name and header"
                + (
                    ", and found it only outside the reports."
                    if elsewhere
                    else ", the OSL, and the configuration."
                )
                + " Confirm the reports were cut as of this credit date."
            ),
            leg="osl_reports",
            evidence=Evidence(report_name="every uploaded report"),
        )
    )


#: How many hits a programme needs before the check believes the inputs are that
#: programme's. One hit is a coincidence; two words from the list is a pattern.
_PROGRAMME_HIT_FLOOR: Final[int] = 2


def _programme_hits(context: RunContext, words: tuple[str, ...]) -> list[str]:
    """Which of a programme's words appear in the inputs.

    Args:
        context: The run context, after stage 1 has parsed everything.
        words: The programme's keywords.

    Returns:
        The words found, scanning the OSL text, the configuration's JSON paths and
        descriptions, and the report sheet names and headers. A grep, not a judgement:
        it is deliberately simple so it is deliberately explainable.
    """
    haystack_parts: list[str] = []
    if context.osl is not None:
        haystack_parts.extend(section.as_text() for section in context.osl.sections)
    if context.config is not None:
        haystack_parts.extend(block.as_text() for block in context.config.blocks)
    for document in context.reports.values():
        for sheet in document.sheets:
            haystack_parts.append(sheet.name)
            haystack_parts.extend(sheet.header)
    haystack = " ".join(haystack_parts).lower()
    return [word for word in words if word.lower() in haystack]


def _check_programme(context: RunContext) -> None:
    """Confirm the inputs read like the declared programme (ADR-026).

    A user says a run is Account Solicitation; the OSL, the configuration, and the
    reports usually say so somewhere in their own words. When none of the declared
    programme's words appear and another programme's do, that is worth a finding
    before anything else is checked.

    Args:
        context: The run context, whose ``findings`` this may append to.
    """
    guidance = context.guidance
    keywords = guidance.programme_keywords or {}
    declared = guidance.scope_code
    if not declared or declared not in keywords or not keywords[declared]:
        return

    declared_hits = _programme_hits(context, keywords[declared])
    if declared_hits:
        return

    others = {
        code: _programme_hits(context, words)
        for code, words in keywords.items()
        if code != declared and words
    }
    strongest = max(others.items(), key=lambda item: len(item[1]), default=("", []))
    looks_like = strongest[0] if len(strongest[1]) >= _PROGRAMME_HIT_FLOOR else ""

    context.add_finding(
        Finding(
            finding_id=context.next_finding_id(),
            type="programme_mismatch",
            severity="high" if looks_like else "review",
            title=(
                f"Declared as {guidance.scope_label or declared}, but the inputs read like "
                f"{looks_like}"
                if looks_like
                else (
                    f"Declared as {guidance.scope_label or declared}, but none of its "
                    "words appear in the inputs"
                )
            ),
            detail=(
                f"Looked for: {', '.join(keywords[declared])}. "
                + (
                    f"Found instead: {', '.join(strongest[1])}."
                    if looks_like
                    else "Found none of them, and no other programme's words either."
                )
                + " Confirm the programme on the run before trusting the programme rules."
            ),
            leg="osl_config",
            evidence=Evidence(osl_ref="whole OSL, configuration, and report headers"),
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


#: Below this the model's own confidence sends a judgment to a person rather than
#: recording a failure (ADR-039).
_JUDGMENT_CONFIDENCE_FLOOR: Final[float] = 0.5


def _run_judgment_check(
    context: RunContext,
    check: CheckDefinition,
    values: Mapping[str, object],
    homes: Mapping[str, str],
    ref: str,
    shadow: bool,
) -> None:
    """Ask the model whether the named values satisfy a rule no formula can express.

    This is the one place the design lets the model judge values, and it is held to
    ADR-001's discipline: the model sees the administrator's instruction and the named
    values the administrator listed — nothing else, never a report — and answers pass,
    fail or review. Code decides what a verdict becomes and sets the severity. It was
    definable and never ran until Phase 6.13c.

    Args:
        context: The run context.
        check: The judgment check.
        values: Every resolved named value on this run.
        homes: Which report each named value reads, for coverage.
        ref: The check's rule reference.
        shadow: Whether the check is in shadow.
    """
    if not check.value_names:
        context.add_finding(
            Finding(
                finding_id=context.next_finding_id(),
                type="could_not_evaluate",
                severity="review",
                title=f"Check {check.name!r} names no values for the model to judge",
                detail=(
                    "A judgment check lists the named values the model may see. This one "
                    f"lists none, so there is nothing to judge. {check.reasoning}"
                ),
                leg="config_reports",
                rule_ref=ref,
                shadow=shadow,
            )
        )
        return

    missing = [name for name in check.value_names if name not in values]
    if missing:
        context.add_finding(
            Finding(
                finding_id=context.next_finding_id(),
                type="could_not_evaluate",
                severity="review",
                title=f"Check {check.name!r} could not be evaluated",
                detail=(
                    f"The named value(s) {', '.join(repr(m) for m in missing)} could not be "
                    f"resolved in the reports supplied. {check.reasoning}"
                ),
                leg="config_reports",
                rule_ref=ref,
                shadow=shadow,
                evidence=Evidence(report_value=", ".join(missing)),
            )
        )
        return

    shown = {name: values[name] for name in check.value_names}
    rendered = ", ".join(f"{name} = {value}" for name, value in shown.items())
    try:
        result = context.client.complete(
            JUDGMENT_PROMPT.system,
            preamble(context.guidance)
            + JUDGMENT_PROMPT.render_with_examples(
                context.examples.get("admin_judgment", ()),
                instruction=check.instruction.strip(),
                values=rendered,
            ),
            JudgmentResponse,
            stage="admin_judgment",
            prompt_version=JUDGMENT_PROMPT.version,
        )
        answer = result.parsed(JudgmentResponse)
    except LLMError as exc:
        # A judgment that could not run is said, never assumed: silence here would read
        # as a pass, which is the one thing a check must not do.
        context.notices.append(
            f"Judgment check {check.name!r} could not be evaluated: the model did not answer."
        )
        _LOG.warning("judgment check %r skipped: %s", check.name, type(exc).__name__)
        return

    for name in check.value_names:
        context.coverage_record.checked("", homes.get(name, ""))
    if answer.verdict == "pass" and answer.confidence >= _JUDGMENT_CONFIDENCE_FLOOR:
        return

    unsure = answer.verdict == "review" or answer.confidence < _JUDGMENT_CONFIDENCE_FLOOR
    context.add_finding(
        Finding(
            finding_id=context.next_finding_id(),
            type="judgment_failed",
            severity="review" if unsure else check.severity,
            title=(
                f"Check {check.name!r} needs a person to judge"
                if unsure
                else f"Check {check.name!r} failed"
            ),
            detail=(
                f"{check.reasoning} The model read {rendered} against the instruction and "
                f"said: {answer.reason or answer.verdict}."
                + (" It was not confident, so this is for a person to decide." if unsure else "")
            ),
            leg="config_reports",
            rule_ref=ref,
            shadow=shadow,
            evidence=Evidence(report_value=rendered),
        )
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
    values = resolve_all(named, context.reports, context.config)
    # Which report each named value reads, so an evaluated check counts towards the
    # coverage of every report it actually touched (Phase 6.11c).
    homes = {value.name: str(value.report_kind) for value in named if value.kind != "config"}

    for check in admin.checks:
        if not check.applies_to(customer, context.guidance.scope_code):
            continue
        ref = f"check:{check.id}" if check.id is not None else ""
        shadow = bool(ref) and ref in admin.shadow_rule_refs
        if check.kind == "judgment":
            _run_judgment_check(context, check, values, homes, ref, shadow)
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
                    rule_ref=ref,
                    shadow=shadow,
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
                    rule_ref=ref,
                    shadow=shadow,
                )
            )
            continue

        for name in result.resolved:
            context.coverage_record.checked("", homes.get(name, ""))

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
                rule_ref=ref,
                shadow=shadow,
                evidence=Evidence(report_value=inputs),
            )
        )
