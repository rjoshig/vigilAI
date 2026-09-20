"""Coverage endpoints: what the run checked, and acknowledging what it did not.

A findings list says what disagreed. Coverage says what was never compared, which is
the question a short findings list cannot answer on its own (Phase 6.11c). Nothing here
calls a model, and nothing here decides anything: an acknowledgement records that a
person saw a gap before the report was frozen (Phase 6.11d).
"""

from __future__ import annotations

import logging
from typing import Final

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from greenlight_ai.api import gate, schemas
from greenlight_ai.api.deps import CurrentUser, current_user, get_session
from greenlight_ai.db import models, repository
from greenlight_ai.db.types import utcnow

__all__ = ["router"]

_LOG: Final = logging.getLogger(__name__)

router = APIRouter(tags=["coverage"])


def _run_or_404(session: Session, run_id: int) -> models.Run:
    """Fetch a run or refuse.

    Args:
        session: The request's session.
        run_id: The run.

    Returns:
        The run row.

    Raises:
        HTTPException: 404 when it does not exist.
    """
    run = session.get(models.Run, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"run {run_id} not found")
    return run


def _acknowledgements(session: Session, run_id: int) -> dict[str, models.CoverageAcknowledgement]:
    """Every acknowledgement on a run, by target.

    Args:
        session: The request's session.
        run_id: The run.

    Returns:
        Target id to the acknowledgement row.
    """
    rows = session.execute(
        sa.select(models.CoverageAcknowledgement).where(
            models.CoverageAcknowledgement.run_id == run_id
        )
    ).scalars()
    return {row.target: row for row in rows}


@router.get("/runs/{run_id}/coverage", response_model=schemas.CoverageOut)
def read_coverage(
    run_id: int,
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(current_user),
) -> schemas.CoverageOut:
    """What this run checked, and what it did not.

    Args:
        run_id: The run.
        session: The request's session.
        _user: The caller.

    Returns:
        One entry per requirement and per uploaded report, the checks that could not be
        evaluated, and the run's notices. A run processed before coverage existed
        returns empty lists and a reason, so the screen says why rather than showing an
        empty panel.

    Raises:
        HTTPException: 404 when the run does not exist.
    """
    run = _run_or_404(session, run_id)
    coverage = gate.run_coverage(run)
    acknowledged = _acknowledgements(session, run.id)

    unevaluated_rows = session.execute(
        sa.select(models.Finding)
        .where(
            models.Finding.run_id == run.id,
            models.Finding.type == "could_not_evaluate",
            models.Finding.shadow.is_(False),
        )
        .order_by(models.Finding.id)
    ).scalars()

    requirements = [
        schemas.RequirementCoverageOut(
            rule_id=entry.rule_id,
            req_type=entry.req_type,
            state=entry.state,
            osl_ref=entry.osl_ref,
            summary=entry.summary,
            reason=entry.reason,
            acknowledged=entry.rule_id in acknowledged,
            acknowledged_by=getattr(acknowledged.get(entry.rule_id), "actor", "") or "",
            acknowledgement_note=getattr(acknowledged.get(entry.rule_id), "note", "") or "",
        )
        for entry in coverage.requirements
    ]
    unevaluated = [
        schemas.UnevaluatedCheckOut(
            finding_id=row.finding_id,
            title=row.title,
            acknowledged=row.finding_id in acknowledged,
            acknowledged_by=getattr(acknowledged.get(row.finding_id), "actor", "") or "",
            acknowledgement_note=getattr(acknowledged.get(row.finding_id), "note", "") or "",
        )
        for row in unevaluated_rows
    ]
    state = gate.gate_state(session, run)

    return schemas.CoverageOut(
        requirements=requirements,
        reports=[
            schemas.ReportCoverageOut(kind=entry.kind, checks_applied=entry.checks_applied)
            for entry in coverage.reports
        ],
        unevaluated=unevaluated,
        notices=list(coverage.notices),
        counts=coverage.counts,
        outstanding=list(state.unacknowledged_requirements) + list(state.unacknowledged_findings),
        reason=(
            ""
            if coverage.requirements
            else "This run was processed before coverage was recorded, so there is nothing to show."
        ),
    )


@router.post("/runs/{run_id}/coverage/acknowledge", response_model=int)
def acknowledge(
    run_id: int,
    payload: schemas.AcknowledgePayload,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> int:
    """Record that a person has seen one or more gaps.

    An acknowledgement is not a decision that the delivery is fine. It is the record
    that the gap was in front of somebody before the report was frozen, which is what
    the gate asks for (ADR-035).

    Args:
        run_id: The run.
        payload: The requirement ids or finding ids, and an optional note.
        session: The request's session.
        user: The caller, recorded as the acknowledger.

    Returns:
        How many acknowledgements were written.

    Raises:
        HTTPException: 404 when the run does not exist, 409 when it is already
            finalized, 422 when a target is not a gap on this run.
    """
    run = _run_or_404(session, run_id)
    frozen = session.execute(
        sa.select(sa.func.count())
        .select_from(models.FinalReport)
        .where(models.FinalReport.run_id == run.id)
    ).scalar_one()
    if int(frozen) > 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"run {run_id} is finalized; its report is frozen and cannot be re-reviewed",
        )

    coverage = gate.run_coverage(run)
    allowed = {entry.rule_id for entry in coverage.unresolved}
    finding_targets = {
        row
        for row in session.execute(
            sa.select(models.Finding.finding_id).where(
                models.Finding.run_id == run.id,
                models.Finding.type == "could_not_evaluate",
                models.Finding.shadow.is_(False),
            )
        ).scalars()
    }

    unknown = [t for t in payload.targets if t not in allowed and t not in finding_targets]
    if unknown:
        # Refusing an unknown target is not pedantry: an acknowledgement that names
        # nothing would satisfy the gate while covering no gap at all.
        raise HTTPException(
            422,
            f"nothing on this run needs acknowledging for: {', '.join(sorted(unknown))}",
        )

    existing = _acknowledgements(session, run.id)
    written = 0
    for target in dict.fromkeys(payload.targets):
        if target in existing:
            continue
        session.add(
            models.CoverageAcknowledgement(
                run_id=run.id,
                target=target,
                kind="finding" if target in finding_targets else "requirement",
                note=payload.note,
                actor=user.name,
                actor_user_id=user.id,
                created_at=utcnow(),
            )
        )
        written += 1

    repository.audit(
        session,
        "coverage.acknowledged",
        run.id,
        ", ".join(dict.fromkeys(payload.targets)),
        user_id=user.id,
        actor=user.name,
    )
    _LOG.info("run %s: %d coverage gap(s) acknowledged by %s", run.id, written, user.name)
    return written
