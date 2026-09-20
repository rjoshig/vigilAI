"""The mapping interview: one cached model call per OSL section.

The model sees the section text, the configuration blocks (path, kind, and the block
as JSON), and the report cells as ``report sheet!label (cell)`` with no values. It
proposes links and asks questions; it never compares (ADR-001). Proposals land as
rows an administrator confirms.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy.orm import Session

from greenlight_ai.db import models
from greenlight_ai.llm.client import LLMClient
from greenlight_ai.llm.prompts import MAP_PROMPT
from greenlight_ai.llm.prompts.schemas import MappingProposal
from greenlight_ai.meaning.samples import samples_in_scope
from greenlight_ai.parsers.base import ParseError
from greenlight_ai.parsers.config_json import JsonConfigParser
from greenlight_ai.parsers.osl import osl_parser_for
from greenlight_ai.parsers.reports.xlsx import parser_for
from greenlight_ai.db.types import utcnow

__all__ = ["InterviewError", "InterviewResult", "propose"]

_LOG: Final = logging.getLogger(__name__)

#: How many report cells a section is shown; beyond this the prompt stops helping.
_MAX_CELLS: Final[int] = 80
#: How much of a block's JSON is shown.
_BLOCK_CHARS: Final[int] = 160
#: Sections that never carry a requirement.
_SKIP: Final[frozenset[str]] = frozenset({"purpose", "background", "contacts"})
_SAFE: Final = re.compile(r"[^a-z0-9]+")


class InterviewError(Exception):
    """The interview could not start: a sample in scope is missing or unreadable."""


class InterviewResult:
    """What one interview did."""

    def __init__(self) -> None:
        self.sections = 0
        self.proposed = 0
        self.open = 0
        self.updated = 0
        self.skipped_confirmed = 0
        self.calls = 0
        self.cached = 0

    def as_dict(self) -> dict[str, int]:
        """The counts, for the API."""
        return dict(vars(self))


def _blocks_text(path: Path) -> str:
    document = JsonConfigParser().parse(path)
    lines = []
    for block in document.blocks:
        body = json.dumps(block.content, sort_keys=True)
        if len(body) > _BLOCK_CHARS:
            body = body[: _BLOCK_CHARS - 1] + "…"
        lines.append(f"- {block.json_path} ({block.kind}): {body}")
    return "\n".join(lines) or "- (none)"


def _value_columns(
    reports: dict[str, list[models.ArtifactSample]], data_dir: Path
) -> dict[tuple[str, str, str], int]:
    """For every ``(report, sheet, label)`` the column holding the row's last value."""
    columns: dict[tuple[str, str, str], int] = {}
    for key, samples in reports.items():
        path = data_dir / samples[0].storage_path
        if not path.exists():
            continue
        try:
            document = parser_for(key).parse(path)
        except ParseError:
            continue
        for sheet in document.sheets:
            for row in sheet.rows:
                label = next(
                    (
                        str(c.value).strip()
                        for c in row
                        if isinstance(c.value, str) and c.value.strip()
                    ),
                    "",
                )
                if not label:
                    continue
                filled = [
                    i for i, c in enumerate(row) if c.value is not None and str(c.value).strip()
                ]
                if len(filled) >= 2:
                    columns.setdefault((key, sheet.name.lower(), label.lower()), filled[-1])
    return columns


def _cells_text(reports: dict[str, list[models.ArtifactSample]], data_dir: Path) -> str:
    """Report cells as ``report sheet!label (cell)``: labels and addresses, never values."""
    lines: list[str] = []
    for key, samples in sorted(reports.items()):
        sample = samples[0]
        path = data_dir / sample.storage_path
        if not path.exists():
            continue
        try:
            document = parser_for(key).parse(path)
        except ParseError:
            continue
        for sheet in document.sheets:
            for row in sheet.rows:
                label = next(
                    (
                        str(c.value).strip()
                        for c in row
                        if isinstance(c.value, str) and c.value.strip()
                    ),
                    "",
                )
                if not label:
                    continue
                first = next((c for c in row if c.value is not None), None)
                lines.append(
                    f"- {key} {sheet.name}!{label[:60]} ({first.address if first else ''})"
                )
                if len(lines) >= _MAX_CELLS:
                    return "\n".join(lines)
    return "\n".join(lines) or "- (none)"


def propose(
    session: Session, scope_code: str, client: LLMClient, data_dir: Path
) -> InterviewResult:
    """Run the interview for one scope and store the proposals.

    Args:
        session: An open session.
        scope_code: ``""`` for global, else a programme code.
        client: The LLM adapter (through the cache).
        data_dir: The shared volume, where samples live.

    Returns:
        Counts of what was proposed.

    Raises:
        InterviewError: When there is no OSL or configuration sample in scope, or one
            cannot be read.
    """
    scope = scope_code.strip().upper()
    samples = samples_in_scope(session, scope)
    osl = samples.get("osl")
    config = samples.get("config")
    if not osl:
        raise InterviewError(
            "no OSL sample in this scope or globally; upload one on Artifact types"
        )
    if not config:
        raise InterviewError("no configuration sample in this scope or globally")
    try:
        document = osl_parser_for(data_dir / osl[0].storage_path).parse(
            data_dir / osl[0].storage_path
        )
        blocks = _blocks_text(data_dir / config[0].storage_path)
    except ParseError as exc:
        raise InterviewError(f"a sample could not be read: {exc}") from exc
    reports = {k: v for k, v in samples.items() if k not in ("osl", "config")}
    cells = _cells_text(reports, data_dir)
    value_columns = _value_columns(reports, data_dir)

    existing = {
        row.key: row
        for row in session.execute(
            sa.select(models.MeaningEntry).where(models.MeaningEntry.scope_code == scope)
        ).scalars()
    }
    result = InterviewResult()
    for section in document.sections:
        if section.heading.strip().lower() in _SKIP:
            continue
        result.sections += 1
        answer = client.complete(
            MAP_PROMPT.system,
            MAP_PROMPT.render(section=section.as_text(), blocks=blocks, cells=cells),
            MAP_PROMPT.schema,
            stage="admin_map_requirement",
            prompt_version=MAP_PROMPT.version,
        )
        result.calls += 1
        result.cached += int(bool(getattr(answer, "cached", False)))
        proposal = MappingProposal.model_validate(_normalize(answer.data))
        for item in proposal.requirements:
            key = _SAFE.sub("_", item.key.lower()).strip("_")[:80] or "requirement"
            placed = bool((item.config_path or "").strip()) and bool(item.report_cells)
            status = "open" if (item.question or not placed) else "proposed"
            row = existing.get(key)
            if row is not None and row.status == "confirmed":
                result.skipped_confirmed += 1
                continue
            if row is None:
                row = models.MeaningEntry(scope_code=scope, key=key)
                session.add(row)
                existing[key] = row
            else:
                result.updated += 1
            row.osl_section = section.number
            row.osl_phrase = section.heading[:300]
            row.requirement_text = item.requirement_text[:4000]
            row.config_path = (item.config_path or "").strip()[:200]
            row.report_cells = [
                {
                    "report_key": cell.report_key,
                    "sheet": cell.sheet,
                    "kind": "cell" if cell.cell and not cell.label else "label",
                    "cell": cell.cell,
                    "label": cell.label,
                    "label_column": 0,
                    "value_column": value_columns.get(
                        (cell.report_key, cell.sheet.lower(), cell.label.lower()), 1
                    ),
                }
                for cell in item.report_cells
            ]
            row.validate = item.validate_text[:4000]
            row.comparison = item.comparison
            row.confidence = float(item.confidence)
            row.question = (item.question or "")[:2000]
            row.compliance_suggestion = (
                item.compliance_suggestion.model_dump() if item.compliance_suggestion else None
            )
            row.status = status
            row.proposed_by = "model"
            row.updated_at = utcnow()
            if status == "open":
                result.open += 1
            else:
                result.proposed += 1
    session.flush()
    _LOG.info(
        "meaning interview scope=%r: %d sections, %d proposed, %d open, %d calls (%d cached)",
        scope or "global",
        result.sections,
        result.proposed,
        result.open,
        result.calls,
        result.cached,
    )
    return result


def _normalize(data: object) -> dict[str, Any]:
    """Fold a real model's answer onto the schema: drop unknown keys, coerce nulls."""
    if not isinstance(data, dict):
        return {"requirements": []}
    raw = data.get("requirements")
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return {"requirements": []}
    keep = {
        "key",
        "requirement_text",
        "config_path",
        "report_cells",
        "validate",
        "comparison",
        "confidence",
        "question",
        "compliance_suggestion",
    }
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict) or not str(item.get("key", "")).strip():
            continue
        entry: dict[str, Any] = {k: v for k, v in item.items() if k in keep}
        cells = entry.get("report_cells")
        entry["report_cells"] = [
            {k: str(c.get(k, "") or "") for k in ("report_key", "sheet", "label", "cell")}
            for c in (cells if isinstance(cells, list) else [])
            if isinstance(c, dict) and c.get("report_key")
        ]
        if entry.get("comparison") not in ("", "equals", "reconciles", None):
            entry["comparison"] = ""
        if entry.get("comparison") is None:
            entry["comparison"] = ""
        if not isinstance(entry.get("confidence"), (int, float)):
            entry["confidence"] = 0.5
        entry["confidence"] = min(1.0, max(0.0, float(entry["confidence"])))
        suggestion = entry.get("compliance_suggestion")
        if not (
            isinstance(suggestion, dict)
            and suggestion.get("name")
            and suggestion.get("json_path_contains")
        ):
            entry["compliance_suggestion"] = None
        else:
            entry["compliance_suggestion"] = {
                k: str(suggestion.get(k, "")) for k in ("name", "json_path_contains", "reasoning")
            }
        for k in ("requirement_text", "validate"):
            if not isinstance(entry.get(k), str):
                entry[k] = ""
        if entry.get("question") is not None and not isinstance(entry["question"], str):
            entry["question"] = str(entry["question"])
        if entry.get("config_path") is not None and not isinstance(entry["config_path"], str):
            entry["config_path"] = str(entry["config_path"])
        out.append(entry)
    return {"requirements": out}
