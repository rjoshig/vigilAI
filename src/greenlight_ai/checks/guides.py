"""Validation guides: what a report cell means and where it answers to (Phase 6.8b).

A guide is an ordered list of entries on an artifact type. Each names a cell or a
label in the report, says what it means, points at the OSL (a section, a phrase, or
both) and at the configuration (a JSON path), and says what to validate. Examples
fill themselves from the stored samples when the locator resolves on them.

Two things happen with a guide, and they are kept apart (ADR-029):

- **The model reads it.** Entries reach stage 4 and stage 8 as a short structured
  block, labelled as background. No values beyond the examples; the model reads
  meaning and never compares.
- **Code enforces the concrete part.** An entry with a locator that resolves on a
  sample *and* a config path compiles into two named values and one check, born in
  shadow with origin ``guide``, so an administrator watches it fire before it
  counts. Entries without a config path stay explanation only.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Final, Literal, Sequence

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from greenlight_ai import scopes
from greenlight_ai.checks.named_values import NamedValue, resolve
from greenlight_ai.db import models
from greenlight_ai.parsers.base import ParseError, ReportKind
from greenlight_ai.parsers.reports.xlsx import parser_for

__all__ = [
    "GUIDE_ORIGIN",
    "Comparison",
    "GuideEntry",
    "GuideExample",
    "GuideLocator",
    "check_name",
    "compile_checks",
    "fill_examples",
    "guide_lines",
    "value_names",
]

_LOG: Final = logging.getLogger(__name__)

#: The origin recorded on every named value and check a guide compiles.
GUIDE_ORIGIN: Final[str] = "guide"

#: How the report cell is checked against the config value, when it is.
Comparison = Literal["", "equals", "reconciles"]

#: Guide identifiers are used inside named-value and check names, so they are kept
#: to what an expression can reference.
_SAFE_ID: Final = re.compile(r"[^a-z0-9]+")

#: How many examples an entry shows the model: one per sample, three samples at most.
_MAX_EXAMPLES: Final[int] = 3


class GuideLocator(BaseModel):
    """Where in the report the entry points."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["cell", "label"] = "label"
    sheet: str = ""
    cell: str = ""
    label: str = ""
    label_column: int = 0
    value_column: int = 1


class GuideExample(BaseModel):
    """The entry's value in one stored sample, filled by code."""

    model_config = ConfigDict(extra="forbid")

    sample_id: int
    label: str = ""
    value: str = ""


class GuideEntry(BaseModel):
    """One line of a validation guide."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(min_length=1, max_length=40)
    locator: GuideLocator = Field(default_factory=GuideLocator)
    #: What the cell means, in a sentence.
    meaning: str = ""
    #: Where it answers to in the OSL: a section number, a phrase, or both.
    osl_section: str = ""
    osl_phrase: str = ""
    #: Where it answers to in the configuration, as a JSON path.
    config_path: str = ""
    #: What to validate, in plain words, for the model.
    validate_text: str = Field(default="", alias="validate")
    #: What code checks when there is a config path: nothing, equality, or
    #: reconciliation within ``tolerance`` (a fraction of the config value).
    comparison: Comparison = ""
    tolerance: float = 0.0
    examples: list[GuideExample] = Field(default_factory=list)

    @property
    def is_concrete(self) -> bool:
        """Whether this entry compiles into a check.

        Returns:
            ``True`` when it has a config path, a comparison, and at least one example,
            which is the proof that the locator resolves on a real layout.
        """
        return bool(self.config_path.strip() and self.comparison and self.examples)


def _slug(entry_id: str) -> str:
    return _SAFE_ID.sub("_", entry_id.strip().lower()).strip("_") or "entry"


def value_names(artifact_key: str, entry: GuideEntry) -> tuple[str, str]:
    """The two named values an entry compiles into.

    Args:
        artifact_key: The report type.
        entry: The entry.

    Returns:
        The report-side and config-side names.
    """
    base = f"guide_{artifact_key}_{_slug(entry.id)}"
    return base, f"{base}_config"


def check_name(artifact_key: str, entry: GuideEntry) -> str:
    """The check an entry compiles into.

    Args:
        artifact_key: The report type.
        entry: The entry.

    Returns:
        A name unique to the type and the entry.
    """
    return f"guide:{artifact_key}:{_slug(entry.id)}"


# --- examples --------------------------------------------------------------------------


def fill_examples(
    artifact_key: str,
    entries: Sequence[GuideEntry],
    samples: Sequence[models.ArtifactSample],
    data_dir: Path,
) -> list[GuideEntry]:
    """Resolve every entry's locator on every stored sample.

    Args:
        artifact_key: The report type, which selects the parser.
        entries: The entries as submitted.
        samples: The type's stored samples.
        data_dir: The shared volume.

    Returns:
        The entries with ``examples`` replaced by what actually resolved. An entry
        whose locator finds nothing in any sample has no examples, and therefore
        never compiles into a check.
    """
    documents = []
    for sample in samples[:_MAX_EXAMPLES]:
        path = data_dir / sample.storage_path
        if not path.exists():
            continue
        try:
            documents.append((sample, parser_for(artifact_key).parse(path)))
        except ParseError as exc:
            _LOG.info("guide %s: sample %d unreadable: %s", artifact_key, sample.id, exc)

    filled: list[GuideEntry] = []
    for entry in entries:
        pointer = NamedValue(
            name=value_names(artifact_key, entry)[0],
            report_kind=_report_kind(artifact_key),
            sheet=entry.locator.sheet,
            kind=entry.locator.kind,
            cell=entry.locator.cell,
            label=entry.locator.label,
            label_column=entry.locator.label_column,
            value_column=entry.locator.value_column,
        )
        examples = []
        for sample, document in documents:
            value = resolve(pointer, {pointer.report_kind: document})
            if value is not None:
                examples.append(
                    GuideExample(sample_id=sample.id, label=sample.label, value=str(value)[:200])
                )
        filled.append(entry.model_copy(update={"examples": examples}))
    return filled


def _report_kind(artifact_key: str) -> ReportKind:
    # The pipeline keys reports by artifact key already; the alias narrows the type.
    return artifact_key


# --- compilation -----------------------------------------------------------------------


def compile_checks(
    session: Session, artifact_key: str, entries: Sequence[GuideEntry], actor: str = ""
) -> int:
    """Turn the concrete entries into named values and shadow checks; retire the rest.

    Args:
        session: An open session.
        artifact_key: The report type.
        entries: The entries, with examples already filled.
        actor: Who saved the guide.

    Returns:
        How many checks are compiled after this call.
    """
    wanted: dict[str, GuideEntry] = {
        check_name(artifact_key, entry): entry for entry in entries if entry.is_concrete
    }

    # Retire compiled checks whose entry is gone or no longer concrete. Deleting is
    # reversible for six months from the Rules screen, like every other rule.
    existing = list(
        session.execute(
            sa.select(models.CheckDefinitionRow).where(
                models.CheckDefinitionRow.origin == GUIDE_ORIGIN,
                models.CheckDefinitionRow.name.like(f"guide:{artifact_key}:%"),
            )
        ).scalars()
    )
    for row in existing:
        if row.name not in wanted and row.state != "deleted":
            row.state = "deleted"
            row.is_active = False
            row.deleted_at = sa.func.now()
            for name in _names_of(row.name, artifact_key):
                session.execute(
                    sa.delete(models.NamedValueRow).where(models.NamedValueRow.name == name)
                )

    by_name = {row.name: row for row in existing}
    for name, entry in wanted.items():
        report_name, config_name = value_names(artifact_key, entry)
        _upsert_named_value(
            session,
            report_name,
            report_type=artifact_key,
            sheet=entry.locator.sheet,
            locator={
                "kind": entry.locator.kind,
                "cell": entry.locator.cell,
                "label": entry.locator.label,
                "label_column": entry.locator.label_column,
                "value_column": entry.locator.value_column,
            },
            description=f"Guide: {entry.meaning or entry.id} (report)",
        )
        _upsert_named_value(
            session,
            config_name,
            report_type="config",
            sheet="",
            locator={"kind": "config", "cell": entry.config_path.strip()},
            description=f"Guide: {entry.meaning or entry.id} (configuration)",
        )
        expression = _expression(report_name, config_name, entry)
        reasoning = entry.validate_text.strip() or (
            f"The report's {entry.meaning or entry.id} must agree with the configuration "
            f"at {entry.config_path.strip()}."
        )
        existing_row = by_name.get(name)
        if existing_row is None:
            session.add(
                models.CheckDefinitionRow(
                    name=name,
                    version=1,
                    kind="expression",
                    expression=expression,
                    reasoning=reasoning,
                    severity="medium",
                    scope=scopes.EVERYWHERE,
                    is_active=False,
                    state="shadow",
                    origin=GUIDE_ORIGIN,
                )
            )
        else:
            changed = existing_row.expression != expression or existing_row.reasoning != reasoning
            existing_row.expression = expression
            existing_row.reasoning = reasoning
            if existing_row.state == "deleted":
                # The entry came back: the check does too, in shadow again.
                existing_row.state = "shadow"
                existing_row.is_active = False
                existing_row.deleted_at = None
            if changed:
                existing_row.version += 1
    session.flush()
    _LOG.info("guide %s: %d check(s) compiled by %s", artifact_key, len(wanted), actor or "?")
    return len(wanted)


def _names_of(check: str, artifact_key: str) -> tuple[str, str]:
    slug = check.rsplit(":", 1)[-1]
    base = f"guide_{artifact_key}_{slug}"
    return base, f"{base}_config"


def _expression(report_name: str, config_name: str, entry: GuideEntry) -> str:
    if entry.comparison == "reconciles" and entry.tolerance > 0:
        return f"abs({report_name} - {config_name}) <= {entry.tolerance} * abs({config_name})"
    return f"{report_name} == {config_name}"


def _upsert_named_value(
    session: Session,
    name: str,
    *,
    report_type: str,
    sheet: str,
    locator: dict[str, Any],
    description: str,
) -> None:
    row = session.execute(
        sa.select(models.NamedValueRow).where(models.NamedValueRow.name == name)
    ).scalar_one_or_none()
    if row is None:
        row = models.NamedValueRow(name=name)
        session.add(row)
    row.report_type = report_type
    row.sheet = sheet
    row.locator = locator
    row.description = description


# --- what the model reads ---------------------------------------------------------------


def guide_lines(artifact_label: str, entries: Sequence[GuideEntry]) -> tuple[str, ...]:
    """Render a guide for a prompt: one line per entry, no values beyond the examples.

    Args:
        artifact_label: What the report type is called.
        entries: The guide.

    Returns:
        Lines, the first naming the report type. Empty when there are no entries.
    """
    if not entries:
        return ()
    lines = [f"Validation guide for {artifact_label} (background; code does the comparing):"]
    for entry in entries:
        where = entry.locator.label or entry.locator.cell or "?"
        if entry.locator.sheet:
            where = f"{entry.locator.sheet}!{where}"
        parts = [f"- {where}: {entry.meaning.strip() or entry.id}"]
        refs = []
        if entry.osl_section.strip():
            refs.append(f"OSL section {entry.osl_section.strip()}")
        if entry.osl_phrase.strip():
            refs.append(f'OSL "{entry.osl_phrase.strip()}"')
        if entry.config_path.strip():
            refs.append(f"config {entry.config_path.strip()}")
        if refs:
            parts.append("answers to " + ", ".join(refs))
        if entry.validate_text.strip():
            parts.append(f"check: {entry.validate_text.strip()}")
        if entry.examples:
            shown = ", ".join(
                f"{example.label or example.sample_id}={example.value}"
                for example in entry.examples[:_MAX_EXAMPLES]
            )
            parts.append(f"e.g. {shown}")
        lines.append("; ".join(parts))
    return tuple(lines)
