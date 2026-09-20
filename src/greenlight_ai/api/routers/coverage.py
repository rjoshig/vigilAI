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
from greenlight_ai.api.deps import CurrentUser, current_user, get_auth_settings, get_session
from greenlight_ai.auth.settings import AuthSettings
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
    auth: AuthSettings = Depends(get_auth_settings),
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
    state = gate.gate_state(session, run, auth.user_auth)

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


@router.get("/runs/{run_id}/second-approval", response_model=schemas.SecondApprovalOut)
def read_second_approval(
    run_id: int,
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(current_user),
    auth: AuthSettings = Depends(get_auth_settings),
) -> schemas.SecondApprovalOut:
    """Whether this run needs a second person, and whether one has signed (ADR-036).

    Args:
        run_id: The run.
        session: The request's session.
        _user: The caller.

    Returns:
        What the rule is waiting on. ``required`` is false for a programme that does
        not ask, which is every programme by default.

    Raises:
        HTTPException: 404 when the run does not exist.
    """
    run = _run_or_404(session, run_id)
    programme = (
        session.execute(
            sa.select(models.RunScope).where(models.RunScope.code == run.scope)
        ).scalar_one_or_none()
        if run.scope
        else None
    )
    approval = session.execute(
        sa.select(models.SecondApproval).where(models.SecondApproval.run_id == run.id)
    ).scalar_one_or_none()
    outstanding = gate.second_approval_needed(session, run, auth.user_auth)

    return schemas.SecondApprovalOut(
        required=bool(programme is not None and programme.second_approver),
        findings=outstanding or list(approval.covered or []) if approval else outstanding,
        outstanding=bool(outstanding),
        approved_by=approval.actor if approval else "",
        approved_at=approval.created_at if approval else None,
        note=approval.note if approval else "",
    )


@router.post("/runs/{run_id}/second-approval", response_model=schemas.SecondApprovalOut)
def approve_second(
    run_id: int,
    payload: schemas.SecondApprovalPayload,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
    auth: AuthSettings = Depends(get_auth_settings),
) -> schemas.SecondApprovalOut:
    """Record that a second person has approved what the reviewer waved through.

    Not a re-review: the first reviewer decided, and this says somebody else saw the
    decisions the programme treats as serious and agreed the run can be frozen.

    Args:
        run_id: The run.
        payload: An optional note.
        session: The request's session.
        user: The approver.

    Returns:
        The state of the rule afterwards.

    Raises:
        HTTPException: 404 when the run does not exist, 409 when it is already
            finalized, 422 when nothing is waiting for a signature or when the
            approver is the person who made the decisions. A signature from the
            reviewer is not a second pair of eyes, which is also why this control
            means nothing with login off: everyone is the same placeholder (ADR-022).
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
            f"run {run_id} is finalized; its report is frozen",
        )

    outstanding = gate.second_approval_needed(session, run, auth.user_auth)
    if not outstanding:
        raise HTTPException(422, "nothing on this run is waiting for a second approval")

    reviewers = {
        row
        for row in session.execute(
            sa.select(models.Finding.reviewed_by_user_id).where(
                models.Finding.run_id == run.id,
                models.Finding.finding_id.in_(outstanding),
            )
        ).scalars()
        if row is not None
    }
    if user.id is not None and user.id in reviewers:
        raise HTTPException(
            422,
            "a second approval has to come from someone other than the reviewer who "
            "made these decisions",
        )

    existing = session.execute(
        sa.select(models.SecondApproval).where(models.SecondApproval.run_id == run.id)
    ).scalar_one_or_none()
    if existing is not None:
        session.delete(existing)
        session.flush()

    session.add(
        models.SecondApproval(
            run_id=run.id,
            actor=user.name,
            actor_user_id=user.id,
            note=payload.note,
            covered=list(outstanding),
            created_at=utcnow(),
        )
    )
    repository.audit(
        session,
        "run.second_approval",
        run.id,
        ", ".join(outstanding),
        user_id=user.id,
        actor=user.name,
    )
    _LOG.info(
        "run %s: second approval by %s over %d finding(s)", run.id, user.name, len(outstanding)
    )
    return read_second_approval(run_id, session, user, auth)
