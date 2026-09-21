"""Stage 7: check the reports. Pure code, no LLM call.

Two things run here: the fixed per-``req_type`` report checks derived from each rule,
and the admin-defined expression checks over named values. A value that cannot be
resolved produces a "could not evaluate" finding; the run never skips a check silently
(``docs/design.md`` "Configurable checks").
"""

from __future__ import annotations

import logging
from typing import Any, Final, Literal, Mapping, cast

from greenlight_ai.checks.definitions import AdminConfig, CheckDefinition
from greenlight_ai.checks import artifact_match, field_labels, programme_match
from greenlight_ai.checks.expressions import ExpressionError, UnresolvedValue, evaluate
from greenlight_ai.checks.named_values import NamedValue, resolve_all
from greenlight_ai.checks.field_constraints import FieldConstraintSpec
from greenlight_ai.checks.field_constraints import evaluate as evaluate_constraints
from greenlight_ai.checks import anomaly
from greenlight_ai.checks.profile import read_profile
from greenlight_ai.checks.reports import (
    DIRT_ATTRIBUTE_SHEET,
    REPORT_CHECKED_KINDS,
    CheckOutcome,
    attribute_stats,
    run_derived_check,
    waterfall_rows,
)
from greenlight_ai.llm.client import LLMError
from greenlight_ai.llm.prompts import JUDGMENT_PROMPT, PROGRAMME_READING_PROMPT, SHAPE_PROMPT
from greenlight_ai.llm.prompts.schemas import JudgmentResponse, ProgrammeReading, ShapeReading
from greenlight_ai.pipeline.guidance import preamble
from greenlight_ai.pipeline import coverage as coverage_module
from greenlight_ai.pipeline.context import RunContext
from greenlight_ai.resolve.layout import LayoutResolver
from greenlight_ai.rules.derive import derive_checks
from greenlight_ai.rules.schema import Evidence, Finding, Severity

__all__ = ["run"]

_LOG: Final = logging.getLogger(__name__)

#: A report that contradicts a requirement is as serious as a config that does: the
#: delivery is already wrong.
_VIOLATION_SEVERITY: Final[Severity] = "high"

#: How many attributes the shape reading is shown. A DIRT can carry hundreds, and
#: a prompt that is mostly a list stops being a prompt.
_MAX_SHAPE_ATTRIBUTES: Final[int] = 60

#: How many extra attributes a note quotes. Enough for a reviewer to recognise what is
#: being talked about, few enough that the detail stays a sentence rather than a column
#: dump — the same reasoning as ``resolve.attributes.MAX_NEAR``.
_MAX_EXTRA_ATTRIBUTES: Final[int] = 10

#: Below this the model was guessing, and a guess about a number it cannot check is
#: not worth a reviewer's time. The same floor every other reading in the product
#: uses.
_SHAPE_FLOOR: Final[float] = 0.6


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
    # Kept on the context, not only in this frame. `repository.save_context` reads the
    # resolver back off it for the layout suggestions (6.21b) and the attribute call
    # count (6.22d) — and it was never assigned, so every run since 6.21b has stored an
    # empty suggestion list however much the model had to reason about. The rail has
    # never once been offered something a real run found.
    resolver = _resolver(context)
    context.resolver = resolver

    for rule in context.rules:
        for check in derive_checks(rule, context.product_codes):
            if check.kind not in REPORT_CHECKED_KINDS:
                # Settled elsewhere: waterfall order is an OSL-against-config question
                # and stage 5 answers it.
                continue
            # A campaign can deliver the same report type several times, so a check
            # runs once per uploaded file and a finding names the one it came from
            # (ADR-021). "The field distribution is wrong" is useless when five were
            # uploaded.
            for documents, part_name in _views(context):
                outcome = run_derived_check(check, documents, context.aliases, resolver)
                if outcome.passed is None:
                    context.coverage_record.unevaluated(rule.rule_id)
                else:
                    context.coverage_record.checked(rule.rule_id, outcome.report_kind or "")
                suffix = f" ({part_name})" if part_name else ""
                # An attribute the report probably carries under another spelling is
                # its own record, raised whether or not the check itself failed
                # (Phase 6.22a). It is never a violation: the delivery may be perfect
                # and the tool merely unable to prove which column is which.
                if outcome.unresolved:
                    context.add_finding(
                        Finding(
                            finding_id=context.next_finding_id(),
                            type="attribute_not_resolved",
                            severity="review",
                            title=(
                                f"Could not tell what the report calls "
                                f"{', '.join(outcome.unresolved)}{suffix}"
                            ),
                            detail=outcome.detail,
                            leg="osl_reports",
                            rule_id=rule.rule_id,
                            evidence=_evidence(rule, outcome),
                        )
                    )
                if outcome.passed is True:
                    continue
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

    _check_beyond_the_product_codes(context, resolver)
    _check_programme(context)
    _check_credit_date(context)
    _check_deliverable_count(context)
    _run_field_constraints(context, resolver)
    _run_admin_checks(context, settings, customer)
    # After every check, because a name is only reasoned about when a check went
    # looking for it. Raised here rather than where it happened so one record covers
    # every check that needed the same sheet (Phase 6.21a).
    _report_reasoned_names(context, resolver)
    _report_capped_attributes(context, resolver)
    _check_anomalies(context, resolver)
    # Read here rather than at render time, because by then the workbooks are long
    # parsed and gone (Phase 6.21f).
    context.waterfall = waterfall_rows(context.reports, resolver)

    # Coverage is settled here, where every check that was going to run has run. It
    # is not a stage of its own: it computes nothing new, it reports what the stage
    # just did (Phase 6.11c).
    context.coverage = coverage_module.compute(context)

    _LOG.info(
        "run %s stage 7: %d findings from report checks",
        context.run_id,
        len(context.findings) - before,
    )


def _resolver(context: RunContext) -> LayoutResolver:
    """Build the layout resolver for this run (Phase 6.21a).

    The client is passed through, so a run that can call a model may spend the ladder's
    fifth rung where its first four fail. A run without one — a re-check, a deployment
    with no model configured — gets a resolver that stops at the deterministic rungs,
    which is the behaviour the product had before the ladder existed.

    Args:
        context: The run context.

    Returns:
        The resolver, carrying the layout map, the run's context block and its worked
        examples.
    """
    return LayoutResolver(
        client=context.client,
        alternates=context.admin.layout_map,
        # Rung 4 for attribute names, and the shortlist rung 5 is shown (Phase 6.22d).
        dictionary=context.dictionary,
        max_attribute_calls=context.max_attribute_calls,
        preamble=preamble(context.guidance),
        examples=context.examples.get("name_locate", ()),
    )


def _report_reasoned_names(context: RunContext, resolver: LayoutResolver) -> None:
    """Say which names the model had to read for us, so a person can disagree.

    A resolved name is **never a pass**. The check it unblocked ran and reported its
    own result; this is the separate record that the layout was not what the tool
    expected, at review severity, naming what was wanted, what was used, and how sure
    the model was. Without it a reviewer would see a passing check and have no way to
    know it was pointed at a sheet nobody confirmed (ADR-001).

    Args:
        context: The run context, whose ``findings`` this appends to.
        resolver: The resolver, read for what its fifth rung reached.
    """
    for reasoned in resolver.reasoned:
        context.add_finding(
            Finding(
                finding_id=context.next_finding_id(),
                type="layout_reasoned",
                severity="review",
                title=reasoned.title,
                detail=(
                    f"No {reasoned.kind} named {reasoned.wanted!r} was found, so the model was "
                    f"shown the {reasoned.kind} names this delivery carries and asked which one "
                    f"was meant. It answered {reasoned.found!r} with a confidence of "
                    f"{reasoned.confidence:.2f}: {reasoned.reason} Every check that needed "
                    f"{reasoned.wanted!r} read {reasoned.found!r} instead. Confirm that is "
                    "right; if it is, an administrator can record it on the artifact type so "
                    "the next run finds it in code."
                ),
                leg="config_reports",
                engine="model",
                confidence=reasoned.confidence,
                evidence=Evidence(
                    report_name=reasoned.artifact,
                    report_sheet=reasoned.found if reasoned.kind == "sheet" else "",
                ),
            )
        )


def _report_capped_attributes(context: RunContext, resolver: LayoutResolver) -> None:
    """Say which attribute names the run's cap stopped it looking for (Phase 6.22d).

    A notice rather than a finding, and the distinction is the point. Nothing is wrong
    with the delivery: the tool ran out of the budget it was given and stopped asking,
    which is a fact about this run rather than about what was delivered. It is a
    **soft** limit — nothing was refused, and the checks that needed those names have
    already said, separately, that they could not be evaluated.

    Silent when nothing was capped, which is every run on a deployment whose dictionary
    covers its deliveries.

    Args:
        context: The run context, whose ``notices`` this appends to.
        resolver: The run's resolver, which counted.
    """
    if not resolver.capped:
        return
    shown = ", ".join(resolver.capped[:_MAX_EXTRA_ATTRIBUTES])
    more = (
        f" and {len(resolver.capped) - _MAX_EXTRA_ATTRIBUTES} more"
        if len(resolver.capped) > _MAX_EXTRA_ATTRIBUTES
        else ""
    )
    context.notices.append(
        f"This run spent its {resolver.max_attribute_calls} attribute lookup(s) and "
        f"stopped asking about {len(resolver.capped)} more: {shown}{more}. Nothing was "
        "refused and nothing failed because of it; the checks that needed those names "
        "report separately that they could not be evaluated. Recording the spellings "
        "in the attribute dictionary removes the lookups altogether."
    )
    _LOG.info(
        "run %s: %d attribute name(s) not looked up; the cap of %d was spent",
        context.run_id,
        len(resolver.capped),
        resolver.max_attribute_calls,
    )


def _check_anomalies(context: RunContext, resolver: LayoutResolver) -> None:
    """Compare this delivery's shape with its own history, and read it (Phase 6.21c).

    The only finding the product makes that no rule covers. Two halves, both graded by
    code and both at the bottom of the severity scale:

    - **Against history.** Pure arithmetic over the previous finalized deliveries of
      this configuration. Says nothing at all until there are enough of them.
    - **On its own terms.** One model call, shown aggregates and nothing else, asked
      what looks odd. Off by default. Code checks every attribute it names was one it
      was shown, applies a floor, and raises a review item.

    Args:
        context: The run context, whose ``findings`` this appends to and whose
            ``profile`` this fills.
    """
    context.profile = read_profile(context.reports, context.aliases, resolver)
    if not context.profile:
        return

    if context.anomalies:
        for deviation in anomaly.compare(
            context.profile,
            context.profile_history,
            sensitivity=context.anomaly_sensitivity,
            min_history=context.anomaly_min_history,
        ):
            context.add_finding(
                Finding(
                    finding_id=context.next_finding_id(),
                    type="profile_anomaly",
                    # Low, always. Code cannot know whether a mean moving matters for
                    # this attribute in this business, and severity is code's to set
                    # (ADR-001) — so it sets the one that means "look when you have a
                    # moment" and puts the numbers in the finding for a person to judge.
                    severity="low",
                    title=deviation.title,
                    detail=anomaly.describe(deviation),
                    leg="config_reports",
                    evidence=Evidence(report_name="dirt", report_sheet=DIRT_ATTRIBUTE_SHEET),
                )
            )

    if context.anomaly_model:
        _read_shape(context)


def _read_shape(context: RunContext) -> None:
    """Ask the model what looks odd about the aggregates, and believe little of it.

    Args:
        context: The run context, whose ``findings`` this appends to.
    """
    if context.client is None or not context.profile:
        return

    lines = []
    for name, entry in sorted(context.profile.items()):
        parts = []
        if entry.null_rate is not None:
            parts.append(f"missing {entry.null_rate:.1%}")
        for measure, label in (("minimum", "min"), ("maximum", "max"), ("mean", "mean")):
            value = getattr(entry, measure)
            if value is not None:
                parts.append(f"{label} {value:,.6g}")
        if parts:
            lines.append(f"- {entry.name or name}: {', '.join(parts)}")
    if not lines:
        return

    offered = {(entry.name or name) for name, entry in context.profile.items()}
    try:
        result = context.client.complete(
            SHAPE_PROMPT.system,
            preamble(context.guidance)
            + SHAPE_PROMPT.render_with_examples(
                context.examples.get("shape_reading", ()),
                attributes="\n".join(lines[:_MAX_SHAPE_ATTRIBUTES]),
            ),
            ShapeReading,
            stage="shape_reading",
            prompt_version=SHAPE_PROMPT.version,
        )
        reading = result.parsed(ShapeReading)
    except LLMError as exc:
        _LOG.info(
            "run %s: the shape reading did not answer (%s)", context.run_id, type(exc).__name__
        )
        return

    for unusual in reading.unusual:
        # The model was told to quote an attribute from the list. Code checks that it
        # did: an attribute nobody offered is a hallucination, and believing one would
        # put a finding on a field this delivery does not carry.
        if unusual.attribute not in offered:
            _LOG.info(
                "run %s: the shape reading named %r, which was not shown",
                context.run_id,
                unusual.attribute,
            )
            continue
        if unusual.confidence < _SHAPE_FLOOR:
            continue
        context.add_finding(
            Finding(
                finding_id=context.next_finding_id(),
                type="profile_anomaly",
                # Review rather than low: this one has no arithmetic behind it, only a
                # reading, so it is put to a person as a question rather than filed as
                # a fact (ADR-001).
                severity="review",
                title=f"{unusual.attribute}: the AI read something odd in the numbers",
                detail=(
                    f"{unusual.observation} The AI was shown this delivery's aggregate "
                    f"statistics — how often each value was missing, the smallest and "
                    f"largest, and the average — and nothing else: no records and no "
                    f"individual values. It was {unusual.confidence:.0%} sure. Nothing has "
                    f"been decided; confirm whether this is expected."
                ),
                leg="config_reports",
                engine="model",
                confidence=unusual.confidence,
                evidence=Evidence(report_name="dirt", report_sheet=DIRT_ATTRIBUTE_SHEET),
            )
        )


def _run_field_constraints(context: RunContext, resolver: LayoutResolver) -> None:
    """Check the per-attribute rules a reviewer wrote in plain words (ADR-021).

    The sentence was the input to synthesis; what runs here is structured data
    compared by code, which is ADR-001 applied to a rule that came from a person.

    Args:
        context: The run context, whose ``findings`` this appends to.
        resolver: The run's resolver, so a field the dictionary knows is found under
            the spelling this delivery uses (Phase 6.22d).
    """
    specs = [
        spec for spec in context.admin.field_constraints if isinstance(spec, FieldConstraintSpec)
    ]
    if not specs:
        return

    for outcome in evaluate_constraints(specs, context.reports, context.aliases, resolver):
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


def _compare_labelled_credit_date(
    context: RunContext, iso: str, hit: field_labels.LabelHit
) -> None:
    """Compare the submitted credit date with the one the report is labelled with.

    The strong form of the check (Phase 6.14b). A report that says what it is cut as
    of can be disagreed with, which is a different and far more useful statement than
    "this date appears nowhere".

    Args:
        context: The run context, whose ``findings`` this may append to.
        iso: The credit date the submitter gave, as ``YYYY-MM-DD``.
        hit: The labelled cell found in a report.
    """
    import datetime as _dt

    try:
        submitted = _dt.date.fromisoformat(iso)
    except ValueError:
        return
    result = artifact_match.compare_credit_date(submitted, hit.value, hit.source)
    if result.kind in ("match", "absent"):
        _LOG.info("run %d stage 7: credit date %s confirmed by %s", context.run_id, iso, hit.source)
        return

    context.add_finding(
        Finding(
            finding_id=context.next_finding_id(),
            type="credit_date_mismatch",
            severity="medium",
            title=(
                f"The reports are cut as of {hit.value}, not the credit date {iso} "
                "given on the form"
            ),
            detail=(
                f"Read {hit.value!r} from {hit.source}, which this delivery labels "
                f"{hit.label!r}, and compared it with the credit date the submitter "
                f"gave ({iso}). They disagree. Either the wrong reports were uploaded "
                "or the credit date on the form is wrong; both are worth settling "
                "before this is signed."
            ),
            leg="osl_reports",
            evidence=Evidence(report_name=hit.source),
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

    # Ask what this delivery calls its credit date, then read that cell and compare
    # (Phase 6.14b). Finding the labelled value turns a presence test into a
    # comparison: it can report "the report says 2026-03-31, you said 2026-04-30",
    # which the old search over every cell could never do.
    hit = field_labels.find_labelled_value(
        context.reports,
        context.credit_date_labels or field_labels.DEFAULT_LABELS[field_labels.CREDIT_DATE],
    )
    if hit is not None:
        _compare_labelled_credit_date(context, iso, hit)
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
                + " No cell labelled as the credit date was found in any report,"
                " so this is the weaker search over every value rather than a"
                " comparison. Confirm the reports were cut as of this credit date."
            ),
            leg="osl_reports",
            evidence=Evidence(report_name="every uploaded report"),
        )
    )


#: How many hits a programme needs before the check believes the inputs are that
#: programme's. One hit is a coincidence; two words from the list is a pattern.
_PROGRAMME_HIT_FLOOR: Final[int] = 2


def _haystack(context: RunContext) -> list[str]:
    """Everything the classification check is allowed to read.

    Args:
        context: The run context, after stage 1 has parsed everything.

    Returns:
        The OSL text, the configuration's JSON paths and descriptions, and the report
        sheet names and headers. Never a data row (ADR-003): a header says what a
        delivery is about, a row says who is in it.
    """
    parts: list[str] = []
    if context.osl is not None:
        parts.extend(section.as_text() for section in context.osl.sections)
    if context.config is not None:
        parts.extend(block.as_text() for block in context.config.blocks)
    for document in context.reports.values():
        for sheet in document.sheets:
            parts.append(sheet.name)
            parts.extend(sheet.header)
    return parts


def _programme_hits(context: RunContext, words: tuple[str, ...]) -> list[str]:
    """Which of a programme's words appear in the inputs.

    Still a grep rather than a judgement, and still deliberately explainable — but a
    grep that survives a hyphen and a plural, which Phase 6.17a measured it failing.
    The matching rules are in `checks/programme_match.py`.

    Args:
        context: The run context, after stage 1 has parsed everything.
        words: The programme's keywords.

    Returns:
        The words found.
    """
    return programme_match.hits(_haystack(context), words)


#: How much of the delivery's own words the reading prompt is shown. Enough to say what
#: the work is for, and far short of the whole OSL: this runs once per delivery and the
#: question is what kind of work it is, not what it requires.
_READING_EXTRACT_CHARS: Final[int] = 4000

#: Below this the model's reading is discarded. A locator that is unsure has told us
#: nothing the keyword match had not, and the keyword match is free.
_READING_CONFIDENCE_FLOOR: Final[float] = 0.6


def _ask_what_it_reads_like(
    context: RunContext, keywords: Mapping[str, tuple[str, ...]], declared: str
) -> "ProgrammeReading | None":
    """Ask the model which programme the delivery's own words describe (6.18f).

    Reached only where the keyword match has already failed, so the common case costs
    nothing. The model is asked what the documents sound like; the caller compares that
    with what was declared, because the comparison is code's (ADR-001).

    Args:
        context: The run context.
        keywords: Every programme's keywords, whose keys are the codes on offer.
        declared: The declared programme's code, which is offered like any other.

    Returns:
        The answer, or ``None`` when it could not be obtained or cannot be believed —
        no client, an unparseable reply, a programme code nobody offered, or an answer
        the model itself was not confident in.
    """
    if context.client is None:
        return None

    labels = context.guidance.programme_labels or {}
    offered = sorted(code for code, words in keywords.items() if words)
    if len(offered) < 2:
        return None
    programmes = "\n".join(f"- {code}: {labels.get(code, code)}" for code in offered)

    extracts = " ".join(" ".join(part.split()) for part in _haystack(context))
    extracts = extracts[:_READING_EXTRACT_CHARS]
    if not extracts.strip():
        return None

    try:
        result = context.client.complete(
            PROGRAMME_READING_PROMPT.system,
            preamble(context.guidance)
            + PROGRAMME_READING_PROMPT.render_with_examples(
                context.examples.get("programme_reading", ()),
                programmes=programmes,
                extracts=extracts,
            ),
            ProgrammeReading,
            stage="programme_reading",
            prompt_version=PROGRAMME_READING_PROMPT.version,
        )
        answer = result.parsed(ProgrammeReading)
    except LLMError as exc:
        _LOG.info("programme reading: no answer (%s)", type(exc).__name__)
        return None

    if answer.verdict != "reads_like":
        return answer
    # The model was given a list of codes. Code checks it used one: a code nobody
    # offered is a hallucination, and believing one would be the comparison ADR-001
    # keeps out of the model's hands.
    if answer.programme_code not in set(offered):
        _LOG.info("programme reading: proposed %r, which was not offered", answer.programme_code)
        return None
    if answer.confidence < _READING_CONFIDENCE_FLOOR:
        _LOG.info(
            "programme reading: %r at confidence %.2f, below the floor",
            answer.programme_code,
            answer.confidence,
        )
        return None
    _ = declared
    return answer


def _check_beyond_the_product_codes(context: RunContext, resolver: LayoutResolver) -> None:
    """Note attributes the delivery carries that the named codes never asked for (6.22c).

    A **low**-severity note and never a failure. A delivery may legitimately carry a
    technical field, and a tool that failed a correct delivery for carrying one would
    teach people to stop reading its findings.

    It is worth a note for two reasons rather than one. The order may be wrong — the
    extract pulled more than the OSL asked for. And **a field nobody asked for may be
    PII**: the one case where carrying extra is not a harmless surplus but a disclosure
    (ADR-003). The note says both, because a reviewer deciding which it is needs to
    know that the second is possible.

    Silent unless a requirement actually names a product code. Without a code there is
    no authoritative list of what was asked for, and calling every unlisted column
    "extra" against a hand-written attribute list would be noise on every run.

    Args:
        context: The run context, whose ``findings`` this appends to.
        resolver: The run's layout resolver, for reading the DIRT's attribute sheet.
    """
    named = tuple(
        dict.fromkeys(code for rule in context.rules for code in rule.product_codes if code.strip())
    )
    if not named:
        return

    stats = attribute_stats(context.reports, context.aliases, resolver)
    delivered = tuple(stat.name for stat in stats.values())
    if not delivered:
        return

    extra = context.product_codes.beyond(named, delivered)
    if not extra:
        return

    shown = ", ".join(extra[:_MAX_EXTRA_ATTRIBUTES])
    more = (
        f" and {len(extra) - _MAX_EXTRA_ATTRIBUTES} more"
        if len(extra) > _MAX_EXTRA_ATTRIBUTES
        else ""
    )
    context.add_finding(
        Finding(
            finding_id=context.next_finding_id(),
            type="attributes_beyond_product_code",
            severity="low",
            title=(
                f"The delivery carries {len(extra)} attribute(s) "
                f"{', '.join(named)} does not list"
            ),
            detail=(
                f"Product code {', '.join(named)} lists what this order asked for, and "
                f"the DIRT also carries {shown}{more}. This is not a failure — a "
                "delivery may legitimately carry a technical field — but it is worth "
                "two looks: the extract may have pulled more than the order asked "
                "for, and a field nobody asked for may be personal data that should "
                "not have left."
            ),
            leg="osl_reports",
            evidence=Evidence(
                report_name="dirt",
                report_sheet=DIRT_ATTRIBUTE_SHEET,
                report_value=f"{len(delivered)} attributes delivered",
            ),
        )
    )
    _LOG.info(
        "run %s: %d attribute(s) beyond product code(s) %s",
        context.run_id,
        len(extra),
        ", ".join(named),
    )


def _check_programme(context: RunContext) -> None:
    """Confirm the inputs read like the declared programme (ADR-026, ADR-045).

    A user says a run is Account Solicitation; the OSL, the configuration, and the
    reports usually say so somewhere in their own words.

    Three steps, cheapest first, and code decides at every one:

    1. **The keyword match**, which tolerates plurals, hyphens and reordered phrases
       (6.17a). A hit anywhere and the check is silent, free, and explainable.
    2. **The model, asked once**, only where that found nothing. It says what the
       documents read like; it is never asked whether the submitter was right.
    3. **Code compares** its answer with the declaration and decides the severity.

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

    # Only a word one programme alone claims is evidence for naming that programme.
    # Two of the shipped Archives keywords were ordinary data-delivery vocabulary, and
    # a shared word cannot tell two programmes apart whoever added it (6.17a).
    others = {
        code: _programme_hits(context, programme_match.discriminating(code, keywords))
        for code, words in keywords.items()
        if code != declared and words
    }
    ranked = sorted(others.items(), key=lambda item: len(item[1]), reverse=True)
    strongest = ranked[0] if ranked else ("", [])
    runner_up = len(ranked[1][1]) if len(ranked) > 1 else 0
    # Clear the floor, and be strictly ahead of the next programme. Two that look
    # equally likely mean the inputs are unfamiliar, not that either one is the answer.
    looks_like = (
        strongest[0]
        if len(strongest[1]) >= _PROGRAMME_HIT_FLOOR and len(strongest[1]) > runner_up
        else ""
    )

    reading = _ask_what_it_reads_like(context, keywords, declared)
    engine: Literal["code", "model"] = "code"
    agreed_phrases: tuple[str, ...] = ()
    if reading is not None and reading.verdict == "reads_like":
        engine = "model"
        if reading.programme_code == declared:
            # The model read the delivery as what the submitter said. The keyword list
            # is missing this customer's vocabulary — a gap in a word list, not a
            # defect in the delivery — so the phrases it quoted are offered to an
            # administrator as the words that would have matched (ADR-045).
            context.add_keyword_suggestion(declared, tuple(reading.phrases))
            _LOG.info(
                "programme reading: agreed with the declared %s; %d phrase(s) suggested",
                declared,
                len(reading.phrases),
            )
            if not looks_like:
                # Code had nothing but "none of its words appear", which is a word-list
                # gap and an administrator's problem. Nothing for a reviewer to do.
                return
            # Code had enough to name a different programme, which is a high-severity
            # finding. **The model may soften that; it may not erase it** — the same
            # rule the compliance locator follows, and for the same reason: a model
            # agreeing with the submitter is the one answer that could hide a real
            # mismatch, so it buys a question rather than a silence.
            context.add_finding(
                Finding(
                    finding_id=context.next_finding_id(),
                    type="programme_mismatch",
                    severity="review",
                    engine="model",
                    title=(
                        f"Declared as {guidance.scope_label or declared}; some words point "
                        f"to {guidance.programme_labels.get(looks_like, looks_like)}"
                    ),
                    detail=(
                        f"None of {guidance.scope_label or declared}'s words appear, and "
                        f"these do: {', '.join(strongest[1])}. Read as a whole, though, the "
                        f"delivery's own words describe {guidance.scope_label or declared}"
                        + (f": {'; '.join(reading.phrases)}." if reading.phrases else ".")
                        + " Confirm the programme, and consider adding this customer's "
                        "words to its keyword list so the question does not recur."
                    ),
                    leg="osl_config",
                    evidence=Evidence(osl_ref="whole OSL, configuration, and report headers"),
                )
            )
            return
        # The model read it as a different programme. That is the case the check
        # exists for, and it now has a reason a person can read.
        looks_like = reading.programme_code
        agreed_phrases = tuple(reading.phrases)
    elif reading is not None:
        # `unclear`: the model could not tell either. It cannot raise the severity,
        # and it stops a keyword coincidence from being reported as certainty.
        looks_like = ""

    label = guidance.programme_labels.get(looks_like, looks_like) if looks_like else ""
    context.add_finding(
        Finding(
            finding_id=context.next_finding_id(),
            type="programme_mismatch",
            severity="high" if looks_like else "review",
            engine=engine,
            title=(
                f"Declared as {guidance.scope_label or declared}, but the inputs read like "
                f"{label}"
                if looks_like
                else (
                    f"Declared as {guidance.scope_label or declared}, but none of its "
                    "words appear in the inputs"
                )
            ),
            detail=(
                f"Looked for: {', '.join(keywords[declared])}. "
                + (
                    f"The delivery's own words say {label}: " f"{'; '.join(agreed_phrases)}."
                    if agreed_phrases
                    else (
                        f"Found instead: {', '.join(strongest[1])}."
                        if looks_like
                        else "Found none of them, and no other programme's words either."
                    )
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
            engine="model",
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
