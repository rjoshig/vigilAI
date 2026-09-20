"""What the model reads at run time: confirmed entries, global plus the programme's."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Session

from greenlight_ai.db import models

__all__ = ["meaning_lines", "effective_entries"]


def effective_entries(session: Session, scope_code: str) -> list[models.MeaningEntry]:
    """Confirmed entries in force for a run: global ones, overridden by the programme's.

    Args:
        session: An open session.
        scope_code: The run's programme code, or ``""``.

    Returns:
        Entries in OSL section order; a programme entry replaces a global one with
        the same key.
    """
    scope = scope_code.strip().upper()
    rows = session.execute(
        sa.select(models.MeaningEntry)
        .where(
            models.MeaningEntry.status == "confirmed",
            models.MeaningEntry.scope_code.in_([scope, ""] if scope else [""]),
        )
        .order_by(models.MeaningEntry.osl_section, models.MeaningEntry.id)
    ).scalars()
    by_key: dict[str, models.MeaningEntry] = {}
    for row in rows:
        current = by_key.get(row.key)
        if current is None or (row.scope_code and not current.scope_code):
            by_key[row.key] = row
    return sorted(by_key.values(), key=lambda r: (r.osl_section, r.id))


def meaning_lines(entries: list[models.MeaningEntry], programme_label: str = "") -> tuple[str, ...]:
    """Render entries for a prompt: one line each, labels and paths, no values.

    Args:
        entries: The entries in force.
        programme_label: What the programme is called, for the heading.

    Returns:
        Lines; empty when there are no entries.
    """
    if not entries:
        return ()
    where = f" for {programme_label}" if programme_label else ""
    lines = [f"Requirement map{where} (background; code does the comparing):"]
    for entry in entries:
        parts = [
            f"- OSL {entry.osl_section} {entry.osl_phrase}".rstrip()
            + f": {entry.requirement_text.strip()[:200] or entry.key}"
        ]
        refs = []
        if entry.config_path.strip():
            refs.append(f"config {entry.config_path.strip()}")
        for cell in list(entry.report_cells or [])[:3]:
            where_cell = cell.get("label") or cell.get("cell") or "?"
            sheet = f"{cell.get('sheet')}!" if cell.get("sheet") else ""
            refs.append(f"report {cell.get('report_key')} {sheet}{where_cell}")
        if refs:
            parts.append("answers to " + ", ".join(refs))
        if entry.validate.strip():
            parts.append(f"check: {entry.validate.strip()[:200]}")
        if entry.note.strip():
            parts.append(f"note: {entry.note.strip()[:200]}")
        lines.append("; ".join(parts))
    return tuple(lines)
