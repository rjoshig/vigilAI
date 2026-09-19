"""Stage 8: a second opinion on each high-severity finding.

A verified finding that the model disputes is kept and downgraded to Review, never
dropped (``docs/design.md`` "Processing pipeline", step 8). That asymmetry is
deliberate: the model may reduce false positives, but it must not be able to hide a
real problem.
"""

from __future__ import annotations

import logging
from typing import Final

from greenlight_ai.llm.client import LLMError
from greenlight_ai.llm.prompts.s8_programme import PROGRAMME_PROMPT
from greenlight_ai.llm.prompts import VERIFY_PROMPT
from greenlight_ai.llm.prompts.schemas import ProgrammeRulesResponse, VerifyResponse
from greenlight_ai.pipeline.context import RunContext
from greenlight_ai.pipeline.guidance import guide_block, preamble
from greenlight_ai.rules.schema import Evidence, Finding, Severity

__all__ = ["run", "format_evidence"]

_LOG: Final = logging.getLogger(__name__)


def run(context: RunContext) -> None:
    """Ask for a second opinion on every high-severity finding.

    Args:
        context: The run context, whose high-severity findings this may downgrade.
    """
    _read_programme_rules(context)

    verified: list[Finding] = []
    disputed = 0

    for finding in context.findings:
        if finding.severity != "high" or finding.verified:
            verified.append(finding)
            continue

        try:
            result = context.client.complete(
                VERIFY_PROMPT.system,
                preamble(context.guidance)
                + VERIFY_PROMPT.render(
                    finding=f"{finding.type} — {finding.title}. {finding.detail}",
                    evidence=format_evidence(finding.evidence),
                ),
                VERIFY_PROMPT.schema,
                stage="s8_verify",
                prompt_version=VERIFY_PROMPT.version,
            )
            answer = result.parsed(VerifyResponse)
        except LLMError as exc:
            # A verification that cannot run leaves the finding exactly as it was: the
            # second opinion is an improvement, not a gate.
            _LOG.warning(
                "run %s: verification of %s failed (%s); keeping the finding unchanged",
                context.run_id,
                finding.finding_id,
                type(exc).__name__,
            )
            verified.append(finding.model_copy(update={"verified": False}))
            continue

        if answer.agreed:
            verified.append(finding.model_copy(update={"verified": True, "verify_agreed": True}))
            continue

        disputed += 1
        verified.append(
            finding.model_copy(
                update={
                    "verified": True,
                    "verify_agreed": False,
                    "severity": "review",
                    "detail": (
                        f"{finding.detail} Second opinion disagreed: {answer.reason} "
                        "The finding is kept for a person to judge."
                    ),
                }
            )
        )

    context.findings = verified
    _LOG.info(
        "run %s stage 8: %d high-severity findings verified, %d downgraded to review",
        context.run_id,
        sum(1 for f in verified if f.verified),
        disputed,
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
