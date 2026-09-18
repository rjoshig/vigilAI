"""Review endpoints: mark a finding OK or Not OK with a comment.

Review decisions never call the LLM (``docs/llm-privacy.md`` "Never-twice rules").
"""

from __future__ import annotations

import logging
from typing import Final

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from vigilai.api import schemas
from vigilai.api.deps import CurrentUser, current_user, get_session
from vigilai.db import models, repository
from vigilai.db.types import utcnow

__all__ = ["router"]

_LOG: Final = logging.getLogger(__name__)

router = APIRouter(tags=["findings"])


@router.patch("/findings/{finding_id}", response_model=schemas.FindingOut)
def review_finding(
    finding_id: int,
    payload: schemas.FindingPatch,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> schemas.FindingOut:
    """Record a reviewer's decision on one finding.

    Args:
        finding_id: The finding row id.
        payload: The decision and comment.
        session: The request's session.
        user: The caller.

    Returns:
        The updated finding.

    Raises:
        HTTPException: 404 when the finding does not exist, 409 when its run is already
            finalized, because a frozen report must keep matching the decisions it was
            generated from (ADR-005).
    """
    finding = session.get(models.Finding, finding_id)
    if finding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"finding {finding_id} not found")

    frozen = session.execute(
        sa.select(sa.func.count())
        .select_from(models.FinalReport)
        .where(models.FinalReport.run_id == finding.run_id)
    ).scalar_one()
    if int(frozen) > 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"run {finding.run_id} is finalized; its report is frozen and cannot be re-reviewed",
        )

    finding.review_status = payload.review_status
    finding.review_note = payload.review_note
    finding.reviewed_at = utcnow()
    finding.reviewed_by_user_id = user.id
    repository.audit(
        session, "finding.reviewed", finding.run_id, f"{finding.finding_id}={payload.review_status}"
    )
    _LOG.info("finding %s reviewed as %s", finding.finding_id, payload.review_status)
    return schemas.FindingOut.model_validate(finding)


@router.post("/runs/{run_id}/findings/bulk-ok", response_model=int)
def bulk_ok_low_severity(
    run_id: int,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> int:
    """Mark every undecided low-severity finding as confirmed.

    Low-severity findings can be decided in bulk (``docs/design.md`` "Review and final
    report"); high-severity ones never can, because they are what the gate is for.

    Args:
        run_id: The run.
        session: The request's session.
        user: The caller, recorded as the reviewer of each one.

    Returns:
        How many findings were decided.
    """
    result = session.execute(
        sa.update(models.Finding)
        .where(
            models.Finding.run_id == run_id,
            models.Finding.severity == "low",
            models.Finding.review_status == "undecided",
        )
        .values(review_status="confirmed", reviewed_at=utcnow(), reviewed_by_user_id=user.id)
    )
    decided = int(result.rowcount)  # type: ignore[attr-defined]
    repository.audit(
        session,
        "finding.bulk_ok",
        run_id,
        f"{decided} low-severity",
        user_id=user.id,
        actor=user.name,
    )
    return decided
