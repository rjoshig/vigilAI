"""Stage 8: a second opinion on each high-severity finding.

A verified finding that the model disputes is kept and downgraded to Review, never
dropped (``docs/design.md`` "Processing pipeline", step 8). That asymmetry is
deliberate: the model may reduce false positives, but it must not be able to hide a
real problem.
"""

from __future__ import annotations

import logging
from typing import Final, Sequence

from greenlight_ai.llm.client import LLMError
from greenlight_ai.llm.prompts.s8_coverage import COVERAGE_PROMPT
from greenlight_ai.llm.prompts.s8_lenses import LENS_LABEL, lens_prompt
from greenlight_ai.llm.prompts.s8_programme import PROGRAMME_PROMPT
from greenlight_ai.llm.prompts import VERIFY_PROMPT
from greenlight_ai.llm.prompts.schemas import (
    CoverageGapResponse,
    LensResponse,
    MissedItem,
    ProgrammeRulesResponse,
)
from greenlight_ai.pipeline.context import RunContext
from greenlight_ai.pipeline.guidance import guide_block, preamble
from greenlight_ai.rules.schema import Evidence, Finding, Severity

__all__ = ["run", "format_evidence"]

_LOG: Final = logging.getLogger(__name__)

#: Below this a lens was guessing, and a guess is not worth a reviewer's time.
_PROPOSAL_CONFIDENCE_FLOOR: Final[float] = 0.5


def run(context: RunContext) -> None:
    """Read every high-severity finding through the configured lenses.

    One lens (``single``) is the second opinion the tool has always asked for. Several
    lenses read the same evidence independently, never each other's answers, and code
    merges what they say (Phase 6.11e, ADR-034).

    Args:
        context: The run context, whose high-severity findings this may downgrade and
            whose findings this may add review items to.
    """
    _read_programme_rules(context)
    _read_coverage_gaps(context)

    lenses = tuple(context.verify_lenses)
    if not lenses:
        high = sum(1 for f in context.findings if f.severity == "high" and not f.verified)
        if high:
            context.notices.append(
                f"Verification is switched off, so {high} high-severity finding(s) were not "
                "read a second time. They are shown exactly as the checks produced them."
            )
        return

    verified: list[Finding] = []
    disputed = 0
    unverified: list[str] = []
    proposals: list[tuple[Finding, str, MissedItem]] = []
    calls = 0
    capped = False

    for finding in context.findings:
        if finding.severity != "high" or finding.verified:
            verified.append(finding)
            continue
        if calls + len(lenses) > context.max_lens_calls:
            capped = True
            unverified.append(finding.finding_id)
            verified.append(finding.model_copy(update={"verified": False}))
            continue

        opinions: list[dict[str, object]] = []
        for lens in lenses:
            calls += 1
            answer = _ask(context, lens, finding)
            if answer is None:
                # A lens that did not answer counts as neither agreement nor
                # disagreement: two lenses that agree still verify the finding.
                opinions.append({"lens": lens, "answered": False})
                continue
            opinions.append(
                {
                    "lens": lens,
                    "answered": True,
                    "agreed": answer.agreed,
                    "reason": answer.reason,
                    "confidence": answer.confidence,
                }
            )
            for item in getattr(answer, "missed", ()):
                proposals.append((finding, lens, item))

        answered = [o for o in opinions if o.get("answered")]
        if not answered:
            _LOG.warning(
                "run %s: no lens answered for %s; keeping the finding unchanged",
                context.run_id,
                finding.finding_id,
            )
            unverified.append(finding.finding_id)
            verified.append(
                finding.model_copy(update={"verified": False, "lens_opinions": tuple(opinions)})
            )
            continue

        dissenting = [o for o in answered if not o.get("agreed")]
        if not dissenting:
            verified.append(
                finding.model_copy(
                    update={
                        "verified": True,
                        "verify_agreed": True,
                        "lens_opinions": tuple(opinions),
                    }
                )
            )
            continue

        # Any disagreement sends the finding to a person, with every reason attached.
        # A lens can lower confidence in a finding; it can never raise a severity.
        disputed += 1
        summary = _disagreement(answered, dissenting)
        verified.append(
            finding.model_copy(
                update={
                    "verified": True,
                    "verify_agreed": False,
                    "severity": "review",
                    "lens_opinions": tuple(opinions),
                    "detail": (
                        f"{finding.detail} {summary} " "The finding is kept for a person to judge."
                    ),
                }
            )
        )

    context.findings = verified
    _add_proposals(context, proposals)
    if capped:
        context.notices.append(
            f"The per-run limit of {context.max_lens_calls} verification call(s) was reached, "
            "so some high-severity findings were not read a second time."
        )
    if unverified:
        context.notices.append(
            f"The second opinion could not be obtained for {len(unverified)} high-severity "
            f"finding(s) ({', '.join(unverified[:5])}"
            + (", …" if len(unverified) > 5 else "")
            + "). They are shown exactly as the checks produced them."
        )
    _LOG.info(
        "run %s stage 8: %d high-severity findings verified, %d downgraded to review",
        context.run_id,
        sum(1 for f in verified if f.verified),
        disputed,
    )


def _read_coverage_gaps(context: RunContext) -> None:
    """Ask which unchecked requirements read like obligations (Phase 6.11f).

    Code decides which requirements no report evidenced; this asks only which of those
    look like something someone must obey. What comes back is a review item, never a
    graded finding: there is no evidence behind it to grade, which is the whole reason
    it is on the list (ADR-034).

    Args:
        context: The run context, whose ``findings`` this may append to.
    """
    if not context.verify_lenses:
        return
    coverage = context.coverage
    if coverage is None or not coverage.unresolved:
        return

    by_id = {entry.rule_id: entry for entry in coverage.unresolved}
    listed = "\n".join(
        f"- {entry.rule_id} ({entry.osl_ref or 'no reference'}): {entry.summary}"
        for entry in coverage.unresolved
    )[:6000]

    try:
        result = context.client.complete(
            COVERAGE_PROMPT.system,
            preamble(context.guidance) + COVERAGE_PROMPT.render(requirements=listed),
            COVERAGE_PROMPT.schema,
            stage=COVERAGE_PROMPT.stage,
            prompt_version=COVERAGE_PROMPT.version,
        )
        answer = result.parsed(CoverageGapResponse)
    except LLMError as exc:
        _LOG.warning(
            "run %s: the unchecked requirements were not read (%s)",
            context.run_id,
            type(exc).__name__,
        )
        context.notices.append(
            f"The {len(coverage.unresolved)} requirement(s) no report evidenced were not "
            "read for obligations: the model could not be reached. They are listed in the "
            "coverage panel either way."
        )
        return

    raised = 0
    for gap in answer.gaps:
        entry = by_id.get(gap.rule_id)
        if entry is None:
            # A requirement id the prompt never listed is invention, and inventions are
            # dropped rather than shown (ADR-026's rule, applied here).
            _LOG.info("run %s: ignoring invented requirement id %r", context.run_id, gap.rule_id)
            continue
        if gap.confidence < _PROPOSAL_CONFIDENCE_FLOOR:
            continue
        raised += 1
        context.add_finding(
            Finding(
                finding_id=context.next_finding_id(),
                type="coverage_gap",
                severity="review",
                title=f"Nothing evidenced {entry.rule_id}, which reads like an obligation",
                detail=(
                    f"{gap.reason} No report check reached this requirement, so nothing "
                    "here says the delivery breaks it — only that nothing shows it was "
                    "applied. A person decides."
                ),
                leg="osl_reports",
                rule_id=entry.rule_id,
                evidence=Evidence(osl_ref=entry.osl_ref, osl_text=entry.summary),
            )
        )
    _LOG.info(
        "run %s: %d of %d unchecked requirement(s) read as obligations",
        context.run_id,
        raised,
        len(coverage.unresolved),
    )


def _reason_of(opinion: dict[str, object]) -> str:
    """One lens's reason, without its trailing stop.

    Args:
        opinion: The stored opinion.

    Returns:
        The reason, or a stand-in when the lens gave none.
    """
    return str(opinion.get("reason") or "no reason given").rstrip(". ")


def _disagreement(
    answered: Sequence[dict[str, object]], dissenting: Sequence[dict[str, object]]
) -> str:
    """Say who disagreed and why, for the finding's detail.

    One reader is the second opinion the tool has always asked for, and reads as such.
    Several readers are a split, and the reviewer is told how it fell and what each
    dissenting lens said, because a reviewer judging a disputed finding needs the
    argument and not only the verdict.

    Args:
        answered: Every lens that answered.
        dissenting: The ones that disagreed.

    Returns:
        A sentence.
    """
    if len(answered) == 1:
        return f"Second opinion disagreed: {_reason_of(dissenting[0])}."
    reasons = "; ".join(
        f"{LENS_LABEL.get(str(o.get('lens', '')), str(o.get('lens', '')))}: {_reason_of(o)}"
        for o in dissenting
    )
    return f"{len(dissenting)} of {len(answered)} readers disagreed — {reasons}."


def _ask(context: RunContext, lens: str, finding: Finding) -> LensResponse | None:
    """Put one finding to one lens.

    Each lens is its own prompt with its own stage name, so each answer is cached
    separately and a re-run costs nothing (ADR-005).

    Args:
        context: The run context.
        lens: The lens name, or ``"single"`` for the one second opinion the tool has
            always asked for.
        finding: The finding to read.

    Returns:
        The answer, or ``None`` when the model could not be reached. A lens that did
        not answer counts as neither agreement nor disagreement.
    """
    prompt = VERIFY_PROMPT if lens == "single" else lens_prompt(lens)
    try:
        result = context.client.complete(
            prompt.system,
            preamble(context.guidance)
            + prompt.render(
                finding=f"{finding.type} — {finding.title}. {finding.detail}",
                evidence=format_evidence(finding.evidence),
            ),
            prompt.schema,
            stage=prompt.stage,
            prompt_version=prompt.version,
        )
        return result.parsed(LensResponse)
    except LLMError as exc:
        # A verification that cannot run leaves the finding exactly as it was: the
        # second opinion is an improvement, not a gate. It is not silent either: the
        # reviewer is told which findings went unverified (Phase 6.11c).
        _LOG.warning(
            "run %s: lens %s could not read %s (%s)",
            context.run_id,
            lens,
            finding.finding_id,
            type(exc).__name__,
        )
        return None


def _add_proposals(
    context: RunContext, proposals: Sequence[tuple[Finding, str, MissedItem]]
) -> None:
    """Turn what the lenses noticed into review items, one per distinct question.

    Never graded findings: the severities code set stand, and a lens may raise a
    possibility but not decide one (ADR-034). They are added after the merge so a
    proposal is not itself put back through the lenses.

    The same observation usually arrives several times, because one lens reads every
    high-severity finding and the same gap is visible from more than one of them. A
    reviewer needs the question once, with the readings that raised it named, not once
    per finding: a proposal repeated five times is five times the noise and none of the
    extra information.

    Args:
        context: The run context, whose ``findings`` this appends to.
        proposals: What each lens said, in the order it was said.
    """
    grouped: dict[str, tuple[Finding, MissedItem, list[str], list[str]]] = {}
    for source, lens, item in proposals:
        title = item.title.strip()
        if not title or item.confidence < _PROPOSAL_CONFIDENCE_FLOOR:
            continue
        key = " ".join(title.lower().split())
        if key not in grouped:
            grouped[key] = (source, item, [], [])
        _, _, lenses, sources = grouped[key]
        if lens not in lenses:
            lenses.append(lens)
        if source.finding_id not in sources:
            sources.append(source.finding_id)

    for source, item, lenses, sources in grouped.values():
        labels = ", ".join(LENS_LABEL.get(lens, lens) for lens in lenses)
        context.add_finding(
            Finding(
                finding_id=context.next_finding_id(),
                type="lens_proposed",
                severity="review",
                title=item.title.strip()[:200],
                detail=(
                    f"Raised by the {labels} reading of "
                    f"{', '.join(sources[:3])}"
                    f"{' and others' if len(sources) > 3 else ''}, from the same "
                    f"evidence: {item.reason} Nothing was compared to produce this; it "
                    "is a question for a person."
                ),
                leg=source.leg,
                rule_id=source.rule_id,
                evidence=source.evidence,
            )
        )


def format_evidence(evidence: Evidence) -> str:
    """Render a finding's evidence for the verify prompt.

    Carries the OSL text, the config path and value, and the report cell and aggregate.
    Sample row numbers are deliberately omitted: the model does not need them, and
    prompts never carry row data (ADR-003).

    Args:
        evidence: The finding's evidence.

    Returns:
        A one-paragraph rendering, or a note when there is nothing to show.
    """
    parts: list[str] = []
    if evidence.osl_text:
        parts.append(f'{evidence.osl_ref or "The OSL"} says "{evidence.osl_text}".')
    if evidence.config_path:
        parts.append(f"Configuration {evidence.config_path} is {evidence.config_value}.")
    if evidence.report_name:
        location = evidence.report_name
        if evidence.report_sheet:
            address = f"!{evidence.report_cell}" if evidence.report_cell else ""
            location += f" ({evidence.report_sheet}{address})"
        parts.append(f"Report {location} shows {evidence.report_value or 'the value above'}.")
    return " ".join(parts) or "No structured evidence was recorded for this finding."


#: The severity a breach carries, from the rule's strictness. Set here by code, never
#: by the model (ADR-026).
_STRICTNESS_SEVERITY: Final[dict[str, Severity]] = {
    "must": "high",
    "should": "medium",
    "advisory": "low",
}

#: Below this the model was guessing, and a guess becomes a review item rather than a
#: graded finding.
_BREACH_CONFIDENCE_FLOOR: Final[float] = 0.5


def _delivery_summary(context: RunContext) -> str:
    """What the delivery contains, in the shape the programme prompt reads.

    Args:
        context: The run context.

    Returns:
        Requirements, configuration description, and one-line report summaries.
        Aggregates and requirement text only; never a sample row (ADR-003).
    """
    requirements = "; ".join(
        str(getattr(rule.source, "text", "") or f"{rule.req_type}: {rule.values}")
        for rule in context.rules
    )[:4000]
    elements = "; ".join(
        f"{element.description}" for element in context.elements if element.description
    )[:4000]
    reports = "; ".join(
        f"{kind}: sheets {', '.join(sheet.name for sheet in document.sheets)}"
        for kind, document in context.reports.items()
    )[:1500]
    return (
        f"Requirements: {requirements or 'none extracted'}.\n"
        f"Configuration: {elements or 'none described'}.\n"
        f"Reports: {reports or 'none'}."
    )


def _read_programme_rules(context: RunContext) -> None:
    """Ask which programme rules the delivery breaks, and grade them by strictness.

    Args:
        context: The run context, whose ``findings`` this appends to.
    """
    guidance = context.guidance
    if not guidance.programme_rules:
        return

    rules_text = "\n".join(
        f"- [{rule_id}] ({strictness}) {text}"
        for rule_id, _title, text, strictness in guidance.programme_rules
    )
    try:
        result = context.client.complete(
            PROGRAMME_PROMPT.system,
            guide_block(context.guidance)
            + PROGRAMME_PROMPT.render(
                programme=guidance.scope_label or guidance.scope_code,
                rules=rules_text,
                delivery=_delivery_summary(context),
            ),
            PROGRAMME_PROMPT.schema,
            stage="s8_programme",
            prompt_version=PROGRAMME_PROMPT.version,
        )
        answer = result.parsed(ProgrammeRulesResponse)
    except LLMError as exc:
        _LOG.warning(
            "run %s: programme-rule reading failed (%s); no programme findings",
            context.run_id,
            type(exc).__name__,
        )
        context.notices.append(
            f"The delivery was not read against {guidance.scope_label or guidance.scope_code}'s "
            f"{len(guidance.programme_rules)} programme rule(s): the model could not be "
            "reached. Nothing here says the delivery obeys them."
        )
        return

    by_id = {
        rule_id: (title, text, strictness)
        for rule_id, title, text, strictness in guidance.programme_rules
    }
    shadow_refs = context.admin.shadow_rule_refs
    for breach in answer.breaches:
        rule = by_id.get(breach.rule_id)
        if rule is None:
            # A rule id the prompt never listed is the model inventing; ignore it.
            continue
        title, text, strictness = rule
        ref = f"programme_rule:{breach.rule_id}"
        low_confidence = breach.confidence < _BREACH_CONFIDENCE_FLOOR
        context.add_finding(
            Finding(
                finding_id=context.next_finding_id(),
                type="programme_rule_violation",
                severity=(
                    "review" if low_confidence else _STRICTNESS_SEVERITY.get(strictness, "medium")
                ),
                title=f"Programme rule: {title}",
                detail=(
                    f"{text} — {breach.reason}"
                    + (
                        " The model was not confident; kept for a person to judge."
                        if low_confidence
                        else ""
                    )
                ),
                leg="osl_config",
                rule_ref=ref,
                shadow=ref in shadow_refs,
                evidence=Evidence(osl_text=breach.evidence[:500]),
            )
        )
