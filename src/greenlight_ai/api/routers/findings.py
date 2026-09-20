"""Review endpoints: mark a finding OK or Not OK with a comment.

Review decisions never call the LLM (``docs/llm-privacy.md`` "Never-twice rules").
"""

from __future__ import annotations

import logging
from typing import Final

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from greenlight_ai.api import provenance, schemas
from greenlight_ai.api.deps import CurrentUser, current_user, get_session
from greenlight_ai.db import models, repository
from greenlight_ai.db.types import utcnow

__all__ = ["decision_problem", "router"]

_LOG: Final = logging.getLogger(__name__)

router = APIRouter(tags=["findings"])

#: The stored value for OK, in bulk: the reviewer saw nothing wrong, so the findings
#: were false positives. "confirmed" is the *Not OK* value (``report/render.py``).
_BULK_OK_STATUS: Final = "false_positive"

#: Starlette deprecated its 422 constant; the number is stable and the import is not.
_HTTP_422: Final[int] = 422

#: Severities on which a Not OK decision must say why (Phase 6.11a). High is the gate's
#: concern; review means the model was unsure and a person's reason is the record.
_NOTE_REQUIRED_FOR_NOT_OK: Final = frozenset({"high", "review"})


def decision_problem(severity: str, review_status: str, review_note: str) -> str:
    """Why a decision cannot be recorded as given, or an empty string when it can.

    A decision has to carry what it means. Accepting a risk always needs the reason
    written down, at any severity, because that sentence is what the frozen report
    shows and what the next reviewer of this configuration reads. Marking a serious
    or uncertain finding Not OK needs a comment for the same reason. OK as a false
    positive needs none: the reason is the choice itself.

    Args:
        severity: The finding's severity.
        review_status: The decision being recorded.
        review_note: The reviewer's comment.

    Returns:
        A message for the reviewer, or ``""`` when the decision is complete.
    """
    if review_note.strip():
        return ""
    if review_status == "accepted_risk":
        return "Accepting a risk needs a comment saying why."
    if review_status == "confirmed" and severity in _NOTE_REQUIRED_FOR_NOT_OK:
        return f"Not OK on a {severity}-severity finding needs a comment saying what is wrong."
    return ""


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
            generated from (ADR-005), 422 when the decision needs a comment it does not
            have (Phase 6.11a).
    """
    finding = session.get(models.Finding, finding_id)
    if finding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"finding {finding_id} not found")

    problem = decision_problem(finding.severity, payload.review_status, payload.review_note)
    if problem:
        raise HTTPException(_HTTP_422, problem)

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
    return provenance.decorate_findings(session, [schemas.FindingOut.model_validate(finding)])[0]


@router.post("/runs/{run_id}/findings/bulk-ok", response_model=int)
def bulk_ok_low_severity(
    run_id: int,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> int:
    """Mark every undecided low-severity finding OK, as a false positive.

    Low-severity findings can be decided in bulk (``docs/design.md`` "Review and final
    report"); high-severity ones never can, because they are what the gate is for. The
    stored value is ``false_positive``: "confirmed" would read as Not OK on the screen
    and turn the run's verdict, which is the opposite of what the button says.

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
        .values(review_status=_BULK_OK_STATUS, reviewed_at=utcnow(), reviewed_by_user_id=user.id)
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
