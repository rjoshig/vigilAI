"""Stage 1: parse the OSL, the config, and every report.

Pure code. Masking happens inside the parsers, so no unmasked report value exists
anywhere downstream of this stage (ADR-003).
"""

from __future__ import annotations

import logging
from typing import Final

from vigilai.parsers.base import ParseError
from vigilai.parsers.config_json import JsonConfigParser
from vigilai.parsers.masking import DEFAULT_MASKED_COLUMNS
from vigilai.parsers.osl_docx import DocxOslParser
from vigilai.parsers.reports.xlsx import parser_for
from vigilai.pipeline.context import ReportPart, RunContext

__all__ = ["run"]

_LOG: Final = logging.getLogger(__name__)


def run(context: RunContext) -> None:
    """Parse every input file into the context.

    Args:
        context: The run context, whose ``osl``, ``config``, and ``reports`` this fills.

    Raises:
        ParseError: When any input cannot be parsed. A run cannot proceed on a partially
            read input: a missing section would look like a missing requirement.
    """
    masked = context.masked_columns or DEFAULT_MASKED_COLUMNS

    context.osl = DocxOslParser().parse(context.osl_path)
    context.config = JsonConfigParser().parse(context.config_path)

    # A kind with no parts recorded is the ordinary single-file case, so the two
    # shapes are unified here rather than in every caller (ADR-021).
    for kind, path in context.report_paths.items():
        if kind not in context.report_parts:
            context.report_parts[kind] = [ReportPart(label="", ordinal=1, path=path)]

    parts_read = 0
    for kind, parts in context.report_parts.items():
        parsed: list[ReportPart] = []
        for part in parts:
            try:
                document = parser_for(kind).parse(part.path, masked)
            except KeyError as exc:
                raise ParseError(part.path, f"no parser for report kind {kind!r}") from exc
            parsed.append(
                ReportPart(
                    label=part.label, ordinal=part.ordinal, path=part.path, document=document
                )
            )
            parts_read += 1
        context.report_parts[kind] = parsed
        # The first part is what a check that does not care about parts sees, which
        # is most of them.
        if parsed and parsed[0].document is not None:
            context.reports[kind] = parsed[0].document

    _LOG.info(
        "run %s stage 1: %d OSL sections, %d config blocks, %d reports in %d file(s)",
        context.run_id,
        len(context.osl.sections),
        len(context.config.blocks),
        len(context.reports),
        parts_read,
    )
