"""Stage 8: a second opinion on each high-severity finding.

A verified finding that the model disputes is kept and downgraded to Review, never
dropped (``docs/design.md`` "Processing pipeline", step 8). That asymmetry is
deliberate: the model may reduce false positives, but it must not be able to hide a
real problem.
"""

from __future__ import annotations

import logging
from typing import Final

from vigilai.llm.client import LLMError
from vigilai.llm.prompts import VERIFY_PROMPT
from vigilai.llm.prompts.schemas import VerifyResponse
from vigilai.pipeline.context import RunContext
from vigilai.pipeline.guidance import preamble
from vigilai.rules.schema import Evidence, Finding

__all__ = ["run", "format_evidence"]

_LOG: Final = logging.getLogger(__name__)


def run(context: RunContext) -> None:
    """Ask for a second opinion on every high-severity finding.

    Args:
        context: The run context, whose high-severity findings this may downgrade.
    """
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
