"""Stage 9: the plain-English summary.

The model receives the findings list only, never the files
(``docs/design.md`` "Processing pipeline", step 9). If the call fails the run still
completes: a missing summary is a cosmetic loss, and the findings are the record.
"""

from __future__ import annotations

import logging
from typing import Final

from vigilai.llm.client import LLMError
from vigilai.llm.prompts import SUMMARIZE_PROMPT
from vigilai.llm.prompts.schemas import SummarizeResponse
from vigilai.pipeline.context import RunContext
from vigilai.pipeline.guidance import preamble

__all__ = ["run", "format_findings"]

_LOG: Final = logging.getLogger(__name__)

#: Severity order for the findings list handed to the model, worst first.
_ORDER: Final[dict[str, int]] = {"high": 0, "medium": 1, "low": 2, "review": 3}

#: A fallback used when the model cannot be reached, so the report is never blank.
_FALLBACK: Final[str] = (
    "The summary could not be generated. The findings below are complete and were "
    "produced by code; only the prose summary is missing."
)


def run(context: RunContext) -> None:
    """Write the summary shown at the top of the report.

    Args:
        context: The run context, whose ``summary`` and ``top_issues`` this fills.
    """
    try:
        result = context.client.complete(
            SUMMARIZE_PROMPT.system,
            preamble(context.guidance) + SUMMARIZE_PROMPT.render(findings=format_findings(context)),
            SUMMARIZE_PROMPT.schema,
            stage="s9_summarize",
            prompt_version=SUMMARIZE_PROMPT.version,
        )
        answer = result.parsed(SummarizeResponse)
    except LLMError as exc:
        _LOG.warning(
            "run %s: summary failed (%s); the findings stand on their own",
            context.run_id,
            type(exc).__name__,
        )
        context.summary = _FALLBACK
        context.top_issues = ()
        return

    context.summary = answer.summary
    context.top_issues = tuple(answer.top_issues)
    _LOG.info(
        "run %s stage 9: summary written (%d top issues)",
        context.run_id,
        len(context.top_issues),
    )


def format_findings(context: RunContext) -> str:
    """Render the findings list for the summary prompt.

    Args:
        context: The run context.

    Returns:
        One line per finding, worst first, carrying severity, type, and title only.
        ``"(none)"`` when the run found nothing, which the prompt has a worked example
        for.
    """
    if not context.findings:
        return "(none)"
    ordered = sorted(context.findings, key=lambda f: (_ORDER.get(f.severity, 9), f.finding_id))
    return "\n".join(f"- {f.severity} | {f.type} | {f.title}" for f in ordered)
