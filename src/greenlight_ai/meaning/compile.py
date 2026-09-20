"""Turn a confirmed meaning entry into what code runs (ADR-033).

A confirmed entry with a configuration path, a first report cell that resolves on a
sample in scope, and a comparison becomes two named values and one check, born in
shadow (ADR-021), scoped to the programme. A confirmed compliance suggestion becomes a
compliance rule, also shadow. Rejecting or deleting the entry retires both.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Final

import sqlalchemy as sa
from sqlalchemy.orm import Session

from greenlight_ai.checks.named_values import NamedValue, resolve
from greenlight_ai.db import models
from greenlight_ai.db.types import utcnow
from greenlight_ai.meaning.samples import samples_in_scope
from greenlight_ai.parsers.base import ParseError
from greenlight_ai.parsers.reports.xlsx import parser_for

__all__ = ["MEANING_ORIGIN", "check_name", "compile_entry", "fill_examples", "retire_entry"]

_LOG: Final = logging.getLogger(__name__)

#: The origin recorded on everything a meaning entry compiles into.
MEANING_ORIGIN: Final[str] = "meaning"


def _scope_token(scope_code: str) -> str:
    return f"programme:{scope_code}" if scope_code else "all"


def _slug(scope_code: str) -> str:
    return scope_code.lower() or "global"


def check_name(entry: models.MeaningEntry) -> str:
    """The check an entry compiles into.

    Args:
        entry: The entry.

    Returns:
        A name unique to the scope and the key.
    """
    return f"meaning:{_slug(entry.scope_code)}:{entry.key}"


def _value_names(entry: models.MeaningEntry) -> tuple[str, str]:
    base = f"meaning_{_slug(entry.scope_code)}_{entry.key}"
    return base, f"{base}_config"


def _pointer(entry: models.MeaningEntry, name: str) -> NamedValue | None:
    cells = list(entry.report_cells or [])
    if not cells:
        return None
    first = cells[0]
    return NamedValue(
        name=name,
        report_kind=str(first.get("report_key", "")),
        sheet=str(first.get("sheet", "")),
        kind="cell" if first.get("kind") == "cell" else "label",
        cell=str(first.get("cell", "")),
        label=str(first.get("label", "")),
        label_column=int(first.get("label_column", 0) or 0),
        value_column=int(first.get("value_column", 1) or 1),
    )


def fill_examples(session: Session, entry: models.MeaningEntry, data_dir: Path) -> None:
    """Resolve the entry's first report cell on every sample in scope.

    Args:
        session: An open session.
        entry: The entry; its ``examples`` are replaced.
        data_dir: The shared volume.
    """
    pointer = _pointer(entry, "probe")
    if pointer is None:
        entry.examples = []
        return
    samples = samples_in_scope(session, entry.scope_code).get(pointer.report_kind, [])
    examples = []
    for sample in samples:
        path = data_dir / sample.storage_path
        if not path.exists():
            continue
        try:
            document = parser_for(pointer.report_kind).parse(path)
        except ParseError:
            continue
        value = resolve(pointer, {pointer.report_kind: document})
        if value is not None:
            examples.append(
                {"sample_id": sample.id, "label": sample.label, "value": str(value)[:200]}
            )
    entry.examples = examples


def _upsert_named_value(session: Session, name: str, **fields: object) -> None:
    row = session.execute(
        sa.select(models.NamedValueRow).where(models.NamedValueRow.name == name)
    ).scalar_one_or_none()
    if row is None:
        row = models.NamedValueRow(name=name)
        session.add(row)
    for key, value in fields.items():
        setattr(row, key, value)


def compile_entry(session: Session, entry: models.MeaningEntry, data_dir: Path) -> dict[str, bool]:
    """Compile a confirmed entry; retire what it no longer supports.

    Args:
        session: An open session.
        entry: A confirmed entry.
        data_dir: The shared volume.

    Returns:
        ``{"check": bool, "compliance": bool}``: what exists after this call.
    """
    fill_examples(session, entry, data_dir)
    concrete = bool(entry.config_path.strip() and entry.comparison and entry.examples)
    name = check_name(entry)
    scope = _scope_token(entry.scope_code)
    existing = session.execute(
        sa.select(models.CheckDefinitionRow).where(
            models.CheckDefinitionRow.name == name,
            models.CheckDefinitionRow.origin == MEANING_ORIGIN,
        )
    ).scalar_one_or_none()
    if concrete:
        report_name, config_name = _value_names(entry)
        pointer = _pointer(entry, report_name)
        assert pointer is not None
        _upsert_named_value(
            session,
            report_name,
            report_type=pointer.report_kind,
            sheet=pointer.sheet,
            locator={
                "kind": pointer.kind,
                "cell": pointer.cell,
                "label": pointer.label,
                "label_column": pointer.label_column,
                "value_column": pointer.value_column,
            },
            description=f"Meaning: {entry.requirement_text[:120] or entry.key} (report)",
        )
        _upsert_named_value(
            session,
            config_name,
            report_type="config",
            sheet="",
            locator={"kind": "config", "cell": entry.config_path.strip()},
            description=f"Meaning: {entry.requirement_text[:120] or entry.key} (configuration)",
        )
        if entry.comparison == "reconciles" and entry.tolerance > 0:
            expression = (
                f"abs({report_name} - {config_name}) <= {entry.tolerance} * abs({config_name})"
            )
        else:
            expression = f"{report_name} == {config_name}"
        reasoning = entry.validate.strip() or (
            f"OSL section {entry.osl_section}: the report must agree with the configuration "
            f"at {entry.config_path.strip()}."
        )
        if existing is None:
            session.add(
                models.CheckDefinitionRow(
                    name=name,
                    version=1,
                    kind="expression",
                    expression=expression,
                    reasoning=reasoning,
                    severity="medium",
                    scope=scope,
                    is_active=False,
                    state="shadow",
                    origin=MEANING_ORIGIN,
                )
            )
        else:
            if existing.expression != expression or existing.reasoning != reasoning:
                existing.version += 1
            existing.expression = expression
            existing.reasoning = reasoning
            existing.scope = scope
            if existing.state == "deleted":
                existing.state = "shadow"
                existing.is_active = False
                existing.deleted_at = None
    elif existing is not None and existing.state != "deleted":
        existing.state = "deleted"
        existing.is_active = False
        existing.deleted_at = utcnow()

    compliance = False
    suggestion = entry.compliance_suggestion or {}
    rule_name = f"meaning:{_slug(entry.scope_code)}:{entry.key}"
    rule = session.execute(
        sa.select(models.ComplianceRuleRow).where(
            models.ComplianceRuleRow.name == rule_name,
            models.ComplianceRuleRow.origin == MEANING_ORIGIN,
        )
    ).scalar_one_or_none()
    if suggestion.get("json_path_contains"):
        compliance = True
        if rule is None:
            rule = models.ComplianceRuleRow(
                name=rule_name, origin=MEANING_ORIGIN, state="shadow", is_active=False
            )
            session.add(rule)
        rule.requirement = {
            "json_path_contains": str(suggestion["json_path_contains"]),
            "expected_value": True,
        }
        rule.reasoning = str(suggestion.get("reasoning") or suggestion.get("name") or "")
        rule.scope = scope
        if rule.state == "deleted":
            rule.state = "shadow"
            rule.is_active = False
            rule.deleted_at = None
    elif rule is not None and rule.state != "deleted":
        rule.state = "deleted"
        rule.is_active = False
        rule.deleted_at = utcnow()
    session.flush()
    _LOG.info("meaning %s compiled: check=%s compliance=%s", name, concrete, compliance)
    return {"check": concrete, "compliance": compliance}


def retire_entry(session: Session, entry: models.MeaningEntry) -> None:
    """Retire what an entry compiled into, when it is rejected or deleted.

    Args:
        session: An open session.
        entry: The entry.
    """
    name = check_name(entry)
    check = session.execute(
        sa.select(models.CheckDefinitionRow).where(
            models.CheckDefinitionRow.name == name,
            models.CheckDefinitionRow.origin == MEANING_ORIGIN,
        )
    ).scalar_one_or_none()
    if check is not None and check.state != "deleted":
        check.state = "deleted"
        check.is_active = False
        check.deleted_at = utcnow()
    rule = session.execute(
        sa.select(models.ComplianceRuleRow).where(
            models.ComplianceRuleRow.name == name, models.ComplianceRuleRow.origin == MEANING_ORIGIN
        )
    ).scalar_one_or_none()
    if rule is not None and rule.state != "deleted":
        rule.state = "deleted"
        rule.is_active = False
        rule.deleted_at = utcnow()
    session.flush()
