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
from vigilai.pipeline.context import RunContext

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

    for kind, path in context.report_paths.items():
        try:
            context.reports[kind] = parser_for(kind).parse(path, masked)
        except KeyError as exc:
            raise ParseError(path, f"no parser for report kind {kind!r}") from exc

    _LOG.info(
        "run %s stage 1: %d OSL sections, %d config blocks, %d reports",
        context.run_id,
        len(context.osl.sections),
        len(context.config.blocks),
        len(context.reports),
    )
