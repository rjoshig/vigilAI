"""Storing a record layout: per run, remembered for the configuration (Phase 6.22b).

A record layout is uploaded with a delivery, but it describes the *configuration* — the
same order delivered next month has the same shape unless somebody changed it. So the
layout is read per run and promoted per configuration:

* **stage 1 reads it** off the uploaded file and snapshots it onto the run, because a
  finalized report has to keep reproducing after the promoted layout has moved on;
* **finalize promotes it** onto the configuration, so the next delivery of the same
  order has something to fall back on;
* **a run that uploads none borrows** the promoted one, and says so. The borrowing is
  recorded on the run and quoted in every finding that rests on it, because a layout
  one delivery out of date is exactly the thing a reviewer has to be told.

Promotion happens at **finalize**, not at submission. A layout that arrived with a
delivery nobody has signed off is not yet the shape of this configuration; promoting it
earlier would let a mistaken upload become the baseline the next run is judged against.
That is the same rule the anomaly baseline follows (Phase 6.21c) and for the same
reason.

Everything here is code. No model reads a record layout to decide anything (ADR-001).
"""

from __future__ import annotations

import logging
from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy.orm import Session

from greenlight_ai.db import models, versions
from greenlight_ai.db.types import utcnow
from greenlight_ai.parsers.record_layout import RecordLayoutDocument

__all__ = [
    "layout_snapshot",
    "load_for_run",
    "promote",
    "promoted_for",
    "run_layout",
]

_LOG: Final = logging.getLogger(__name__)


def promoted_for(
    session: Session, customer: str, configuration_id: str
) -> models.RecordLayoutRow | None:
    """The record layout a configuration is known to deliver.

    Args:
        session: An open session.
        customer: Who the delivery is for.
        configuration_id: The configuration.

    Returns:
        The promoted row, or ``None``. A configuration with no id has nothing
        remembered for it, because the id is what says "the same order again" — the
        same rule :func:`greenlight_ai.db.drift.previous_finalized_run` follows.
    """
    if not configuration_id.strip():
        return None
    return session.execute(
        sa.select(models.RecordLayoutRow).where(
            models.RecordLayoutRow.customer_name == customer,
            models.RecordLayoutRow.configuration_id == configuration_id,
        )
    ).scalar_one_or_none()


def load_for_run(session: Session, run: models.Run) -> RecordLayoutDocument:
    """The record layout one run was checked against, rebuilt from its snapshot.

    Args:
        session: An open session; unused, kept so the helper reads beside the others.
        run: The run row.

    Returns:
        The document. Empty when the run had none, which is the ordinary state and is
        checked exactly as it was before the slot existed.
    """
    del session
    source_run_id = int(run.record_layout_run_id or 0)
    return RecordLayoutDocument.from_rows(
        run.record_layout,
        source_run_id=source_run_id,
        source_date=_source_date(run) if source_run_id else "",
    )


def _source_date(run: models.Run) -> str:
    """When the run that supplied a borrowed layout was finalized, as an ISO date.

    Args:
        run: The borrowing run, whose snapshot carries the date.

    Returns:
        The date, or an empty string when the snapshot does not carry one. Stored on
        the run rather than looked up, so a finding reads the same after the source run
        is purged.
    """
    return str(run.record_layout_source_date or "")


def run_layout(
    session: Session,
    customer: str,
    configuration_id: str,
    uploaded: RecordLayoutDocument | None,
) -> RecordLayoutDocument:
    """What layout a run should be checked against.

    Args:
        session: An open session.
        customer: Who the delivery is for.
        configuration_id: The configuration.
        uploaded: What this run uploaded, or ``None`` when it uploaded none.

    Returns:
        The uploaded layout when there is one; otherwise the configuration's promoted
        layout, marked with the run and date it came from; otherwise an empty document.
    """
    if uploaded is not None and uploaded.fields:
        return uploaded

    row = promoted_for(session, customer, configuration_id)
    if row is None:
        return RecordLayoutDocument()

    borrowed = RecordLayoutDocument.from_rows(
        row.fields,
        source_run_id=int(row.source_run_id or 0),
        source_date=(
            row.source_finished_at.date().isoformat() if row.source_finished_at is not None else ""
        ),
    )
    if not borrowed.fields:
        return RecordLayoutDocument()
    _LOG.info(
        "configuration %s: no record layout uploaded; borrowing run %s's (%d field(s))",
        configuration_id,
        borrowed.source_run_id or "?",
        len(borrowed.fields),
    )
    return borrowed


def layout_snapshot(row: models.RecordLayoutRow) -> dict[str, Any]:
    """The promoted layout as a version snapshot.

    Args:
        row: The promoted row, after the change has been flushed.

    Returns:
        Enough to show what a version held and to revert onto it. Deliberately **not**
        the source run or filename: what is versioned is the *layout*, and a second
        delivery of the same shape is not a new version of it. Including the run id
        would write a version on every finalize and fill the ten the console lists
        with identical entries. Which run promoted it is in the version's summary.
    """
    return {
        "customer_name": row.customer_name,
        "configuration_id": row.configuration_id,
        "entries": list(row.fields or []),
    }


def promote(
    session: Session,
    run: models.Run,
    actor: str = "",
) -> models.RecordLayoutRow | None:
    """Make this run's record layout the one the configuration is known to deliver.

    Called at finalize. Idempotent in the way that matters: promoting the same layout
    twice writes no new version, so the ten the console lists stay meaningful.

    A **borrowed** layout is never promoted. It is already the configuration's, and
    re-promoting it would move the source run and date forward to a run that never
    uploaded anything — which would make a finding quote a provenance that is not true.

    Args:
        session: An open session.
        run: The run being finalized.
        actor: Who finalized it.

    Returns:
        The promoted row, or ``None`` when there was nothing to promote.
    """
    if not run.configuration_id.strip():
        return None
    fields = list(run.record_layout or [])
    if not fields or int(run.record_layout_run_id or 0):
        return None

    row = promoted_for(session, run.customer_name, run.configuration_id)
    if row is None:
        row = models.RecordLayoutRow(
            customer_name=run.customer_name,
            configuration_id=run.configuration_id,
        )
        session.add(row)
    row.fields = fields
    row.source_run_id = run.id
    row.source_finished_at = run.finished_at or utcnow()
    row.source_filename = _uploaded_filename(run)
    row.promoted_at = utcnow()
    row.promoted_by = actor[:200]
    session.flush()

    versions.record_layout_version(
        session,
        run.customer_name,
        run.configuration_id,
        layout_snapshot(row),
        actor,
        summary=f"{len(fields)} field(s) promoted from run {run.id}",
    )
    _LOG.info(
        "run %d promoted a record layout of %d field(s) for configuration %s",
        run.id,
        len(fields),
        run.configuration_id,
    )
    return row


def _uploaded_filename(run: models.Run) -> str:
    """The name of the record layout file this run uploaded.

    Args:
        run: The run, whose files are already loaded.

    Returns:
        The filename, or an empty string when the run uploaded none.
    """
    from greenlight_ai.parsers.base import RECORD_LAYOUT_KIND  # noqa: PLC0415 - cycle

    for file in run.files:
        if file.kind == RECORD_LAYOUT_KIND:
            return str(file.filename or "")
    return ""
