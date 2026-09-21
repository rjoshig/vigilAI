"""Try this setup against the samples, before a real delivery does (Phase 6.21f).

An administrator can define an artifact type, upload samples, write a validation guide,
confirm a dozen meaning entries and author a handful of checks — and until a real
delivery arrives there is no way to find out whether any of it fires. The only feedback
loop in the product ran through somebody else's working day.

So: run what code can run, against the samples that are already stored, and say what
happened. Three questions, which are the three ways a setup is wrong:

1. **Can the tool read these files at all?** Which sheets each sample carries, and
   which of the names the fixed checks look for resolve on it — deterministically,
   because that is the state a real run wants to be in (ADR-051).
2. **Do the pointers point at anything?** Every named value an administrator defined,
   resolved against the samples, with the value it found.
3. **Would the checks run?** Every active expression check evaluated over those values.

**It is a rehearsal, not a run.** No model is called, nothing is stored, no finding is
raised and no rule changes state. That is what makes it safe to press repeatedly while
editing, which is the point: the loop has to be fast enough to use.

What it cannot tell anybody is whether the *judgement* is right — a check that runs
cleanly against a sample can still be asking the wrong question. It answers "is this
wired up", which is the question that currently has no answer at all.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy.orm import Session

from greenlight_ai.checks import reports as report_checks
from greenlight_ai.checks.expressions import ExpressionError, UnresolvedValue, evaluate
from greenlight_ai.checks.named_values import NamedValue, resolve_all
from greenlight_ai.db import models
from greenlight_ai.parsers.base import ParseError, ReportDocument, ReportKind
from greenlight_ai.meaning.samples import samples_in_scope
from greenlight_ai.parsers.reports.xlsx import parser_for

__all__ = ["Rehearsal", "ArtifactReading", "NamedValueReading", "CheckReading", "rehearse"]

_LOG: Final = logging.getLogger(__name__)


#: Which sheet each report type's fixed checks go looking for. A type not listed here
#: has no fixed check of its own — an administrator's named values and checks reach it
#: instead, and those are reported below in their own right.
_WANTED: Final[dict[str, tuple[str, ...]]] = {
    "dirt": (report_checks.DIRT_ATTRIBUTE_SHEET,),
    "state_distribution": (report_checks.STATE_SHEET,),
    "field_distribution": (report_checks.FIELD_SHEET,),
    "counts": (report_checks.FLOW_SHEET,),
}


@dataclass(frozen=True, slots=True)
class ArtifactReading:
    """What the tool made of one artifact type's samples.

    Attributes:
        key: The artifact type.
        label: What it is called.
        sample_count: How many samples are stored for it in this scope.
        sheets: Every sheet name across them, in first-seen order.
        resolved: The names the fixed checks look for that code found, as
            ``wanted -> what it is here``.
        unresolved: The names it looked for and no deterministic rung settled. **Not
            an error**: most of them do not apply to most report types, and the caller
            says so rather than listing them as failures.
        error: Why nothing could be read, when the workbook would not open.
    """

    key: str
    label: str
    sample_count: int = 0
    sheets: tuple[str, ...] = ()
    resolved: dict[str, str] = field(default_factory=dict)
    unresolved: tuple[str, ...] = ()
    error: str = ""


@dataclass(frozen=True, slots=True)
class NamedValueReading:
    """One pointer, resolved against the samples.

    Attributes:
        name: The named value.
        description: What an administrator said it is.
        found: Whether it resolved.
        value: What was there, rendered, when it did.
    """

    name: str
    description: str = ""
    found: bool = False
    value: str = ""


@dataclass(frozen=True, slots=True)
class CheckReading:
    """One check, evaluated over the samples.

    Attributes:
        name: The check.
        expression: What it compares.
        passed: ``True``, ``False``, or ``None`` when a value it needs was not found —
            which on a real run is a "could not evaluate" finding, never a silent skip.
        detail: What happened, in words.
        shadow: Whether it is still in shadow, so a passing check nobody sees is not
            read as one that is live.
    """

    name: str
    expression: str = ""
    passed: bool | None = None
    detail: str = ""
    shadow: bool = False


@dataclass(frozen=True, slots=True)
class Rehearsal:
    """What a setup would do, as far as the samples can say.

    Attributes:
        scope: The programme the samples were taken from, or empty for global.
        artifacts: One entry per artifact type that has a sample.
        named_values: Every pointer, resolved or not.
        checks: Every active check, evaluated or not.
        notes: What the rehearsal could not tell anybody, said plainly.
    """

    scope: str = ""
    artifacts: tuple[ArtifactReading, ...] = ()
    named_values: tuple[NamedValueReading, ...] = ()
    checks: tuple[CheckReading, ...] = ()
    notes: tuple[str, ...] = ()


def _load(session: Session, data_dir: Path, scope: str) -> dict[ReportKind, ReportDocument]:
    """Parse one sample per report type, newest first within the scope.

    Args:
        session: An open session.
        data_dir: The shared volume.
        scope: The programme code, or empty for the global samples.

    Returns:
        Report kind to its parsed sample. A type whose sample will not open is left
        out; :func:`rehearse` reports that separately, because "could not read it" is
        the most useful thing a rehearsal can say.
    """
    parsed: dict[ReportKind, ReportDocument] = {}
    for key, samples in samples_in_scope(session, scope).items():
        for sample in samples:
            path = data_dir / sample.storage_path
            if not path.exists():
                continue
            try:
                parsed[key] = parser_for(key).parse(path)
            except (ParseError, KeyError):
                continue
            break
    return parsed


def rehearse(session: Session, data_dir: Path, scope: str = "") -> Rehearsal:
    """Run what code can run against the stored samples.

    Args:
        session: An open session.
        data_dir: The shared volume the samples live under.
        scope: The programme whose samples to use, or empty for the global ones.

    Returns:
        What happened. Nothing is stored and no model is called, so this is safe to
        call repeatedly while somebody is editing a definition.
    """
    in_scope = samples_in_scope(session, scope)
    parsed = _load(session, data_dir, scope)
    labels = {
        row.key: row.label for row in session.execute(sa.select(models.ArtifactType)).scalars()
    }
    # Deterministic rungs only, through the document's own lookups. A rehearsal that
    # spent a model call every time somebody pressed the button would be one nobody
    # presses, and the state worth reporting is the one a real run wants to be in
    # anyway: resolved in code (ADR-051).
    artifacts: list[ArtifactReading] = []
    for key, samples in sorted(in_scope.items()):
        document = parsed.get(key)
        if document is None:
            artifacts.append(
                ArtifactReading(
                    key=key,
                    label=labels.get(key, key),
                    sample_count=len(samples),
                    error="the stored sample could not be opened as a workbook",
                )
            )
            continue

        resolved: dict[str, str] = {}
        unresolved: list[str] = []
        # Only the names *this* type's checks look for. Asking every type about every
        # sheet would report the state sheet as missing from the DIRT, which is true
        # and useless, and a screen full of true-and-useless is one nobody reads.
        for wanted in _WANTED.get(key, ()):
            found = document.resolve_sheet(wanted)
            if found is not None:
                resolved[wanted] = found.value
            else:
                unresolved.append(wanted)

        artifacts.append(
            ArtifactReading(
                key=key,
                label=labels.get(key, key),
                sample_count=len(samples),
                sheets=document.sheet_names,
                resolved=resolved,
                unresolved=tuple(unresolved),
            )
        )

    named = _named_values(session)
    values = resolve_all(named, parsed, None)
    readings = tuple(
        NamedValueReading(
            name=pointer.name,
            description=pointer.description,
            found=values.get(pointer.name) is not None,
            value="" if values.get(pointer.name) is None else str(values[pointer.name]),
        )
        for pointer in named
    )

    checks = tuple(_evaluate(session, values))

    notes = [
        "No model was called and nothing was stored. This says whether the setup is "
        "wired up, not whether it asks the right questions.",
    ]
    if not parsed:
        notes.append(
            "No sample could be read, so every check below could only say that it had "
            "nothing to read. Upload a sample workbook on the artifact type first."
        )

    _LOG.info(
        "rehearsal for scope %r: %d artifacts, %d named values, %d checks",
        scope or "everywhere",
        len(artifacts),
        len(readings),
        len(checks),
    )
    return Rehearsal(
        scope=scope,
        artifacts=tuple(artifacts),
        named_values=readings,
        checks=checks,
        notes=tuple(notes),
    )


def _named_values(session: Session) -> list[NamedValue]:
    """Every pointer an administrator has defined.

    Args:
        session: An open session.

    Returns:
        The pointers, in name order.
    """
    return [
        NamedValue(
            name=row.name,
            report_kind=row.report_type,
            sheet=row.sheet,
            kind=(row.locator or {}).get("kind", "label"),
            cell=(row.locator or {}).get("cell", ""),
            label=(row.locator or {}).get("label", ""),
            label_column=(row.locator or {}).get("label_column", 0),
            value_column=(row.locator or {}).get("value_column", 1),
            description=row.description,
        )
        for row in session.execute(
            sa.select(models.NamedValueRow).order_by(models.NamedValueRow.name)
        ).scalars()
    ]


def _evaluate(session: Session, values: dict[str, Any]) -> list[CheckReading]:
    """Run every check that is not retired over the resolved values.

    Args:
        session: An open session.
        values: The named values, as resolved against the samples.

    Returns:
        One reading per check, in name order.
    """
    rows = session.execute(
        sa.select(models.CheckDefinitionRow).order_by(models.CheckDefinitionRow.name)
    ).scalars()

    readings: list[CheckReading] = []
    for row in rows:
        if row.state == "retired":
            continue
        expression = row.expression or ""
        if row.kind != "expression" or not expression:
            readings.append(
                CheckReading(
                    name=row.name,
                    expression=expression,
                    detail=(
                        "A judgment check. It reads named values with the model at run "
                        "time, so a rehearsal cannot run it without spending a call."
                    ),
                    shadow=row.state == "shadow",
                )
            )
            continue

        try:
            outcome = evaluate(expression, values)
        except UnresolvedValue as exc:
            readings.append(
                CheckReading(
                    name=row.name,
                    expression=expression,
                    detail=(
                        f"{exc} On a real run this is a 'could not evaluate' finding, "
                        "never a silent skip."
                    ),
                    shadow=row.state == "shadow",
                )
            )
            continue
        except ExpressionError as exc:
            readings.append(
                CheckReading(
                    name=row.name,
                    expression=expression,
                    detail=f"The expression could not be read: {exc}",
                    shadow=row.state == "shadow",
                )
            )
            continue

        inputs = ", ".join(f"{name} = {value}" for name, value in outcome.resolved.items())
        readings.append(
            CheckReading(
                name=row.name,
                expression=expression,
                passed=outcome.passed,
                # The inputs, not a verdict: a check that failed against a *sample* has
                # not found a problem with anything, and wording it as one would teach
                # an administrator to distrust the rehearsal.
                detail=f"Read {inputs}." if inputs else "Nothing to compare.",
                shadow=row.state == "shadow",
            )
        )
    return readings
