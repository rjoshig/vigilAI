"""Train AI mode: observations, candidates, and the rules screen (ADR-021).

Three audiences, one loop. A reviewer records what they know. An administrator reads
the queue, has the model draft a rule, and approves it. The rules screen is where
anyone answers "what made this finding appear".

Nothing here evaluates a rule. Approval writes into the tables the pipeline already
reads, so there is one rule surface and one place to look when a finding is wrong.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Final

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from greenlight_ai.api.deps import CurrentUser, current_user, get_session, require_admin
from greenlight_ai.api.schemas_training import (
    CandidateDecision,
    CandidateOut,
    ConfigNoteIn,
    ObservationDecision,
    ObservationIn,
    ObservationOut,
    RuleAction,
    RuleOut,
    RulesBulkAction,
    RulesBulkResult,
    RuleStateChangeOut,
    FrontDoorIn,
    FrontDoorOut,
    SynthesizeIn,
    TrainingConfigOut,
)
from greenlight_ai.config.store import resolve
from greenlight_ai.db import models, repository
from greenlight_ai.training import conflicts
from greenlight_ai.llm.factory import build_client
from greenlight_ai.llm.settings import resolved_llm_settings
from greenlight_ai.llm.tripwire import PiiDetected, assert_clean
from greenlight_ai.training import front_door, lifecycle, synthesis

__all__ = ["router"]

_LOG: Final = logging.getLogger(__name__)

#: Starlette deprecated its 422 constant; the number is stable and the import is not.
HTTP_422: Final[int] = 422

router = APIRouter(tags=["training"])


def _enabled(session: Session) -> bool:
    """Whether Train AI mode is on.

    Args:
        session: The request's session.

    Returns:
        Whether reviewers may record observations. Off by default, so the user app is
        exactly what it is today until an administrator turns it on.
    """
    return bool(resolve(session, "training.enabled").value)


def _require_enabled(session: Session) -> None:
    """Refuse when the mode is off.

    Args:
        session: The request's session.

    Raises:
        HTTPException: 404 when the mode is off. Not 403: with the mode off these
            endpoints are not part of the product, and saying so is more honest than
            implying the caller lacks a permission.
    """
    if not _enabled(session):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Train AI mode is not enabled")


def _observation_out(row: models.TrainingObservation) -> ObservationOut:
    """Render a stored observation.

    Args:
        row: The observation.

    Returns:
        The wire model. ``editable`` is what the form uses to decide whether the
        author may still change it; once an administrator queues it, it freezes.
    """
    return ObservationOut(
        id=row.id,
        kind=row.kind,  # type: ignore[arg-type]
        anchors=list(row.anchors or []),
        statement=row.statement,
        expectation=row.expectation,
        severity_hint=row.severity_hint,  # type: ignore[arg-type]
        scope_hint=row.scope_hint,  # type: ignore[arg-type]
        run_id=row.run_id,
        finding_id=row.finding_id,
        author=row.author,
        status=row.status,
        status_note=row.status_note,
        candidate_id=row.candidate_id,
        customer_name=row.customer_name,
        scope_code=row.scope_code,
        version=row.version,
        # A configuration note stays editable for life, because its job is to stay
        # true about a configuration that keeps being run (ADR-024).
        editable=row.status == "new" or row.kind == "config_note",
        configuration_id=row.configuration_id,
        is_active=row.is_active,
        revisions=list(row.revisions or []),
        created_at=row.created_at,
        synthesized_at=row.synthesized_at,
    )


def _candidate_out(row: models.RuleCandidate) -> CandidateOut:
    """Render a candidate rule.

    Args:
        row: The candidate.

    Returns:
        The wire model, including its conflicts and what a replay found.
    """
    return CandidateOut(
        id=row.id,
        name=row.name,
        target_kind=row.target_kind,
        body=dict(row.body or {}),
        reasoning=row.reasoning,
        severity=row.severity,
        scope=row.scope,
        status=row.status,
        admin_note=row.admin_note,
        source_observation_ids=list(row.source_observation_ids or []),
        model_used=row.model_used,
        prompt_version=row.prompt_version,
        conflicts=list(row.conflicts or []),
        critique=dict(row.critique or {}),
        redraft=dict(row.redraft or {}),
        replay=dict(row.replay or {}),
        created_by=row.created_by,
        decided_by=row.decided_by,
        created_at=row.created_at,
    )


# ------------------------------------------------------------------ observations


@router.get("/training/config", response_model=TrainingConfigOut)
def training_config(
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(current_user),
) -> TrainingConfigOut:
    """Whether the user app should offer to record observations.

    Args:
        session: The request's session.
        _user: The caller.

    Returns:
        The switch.
    """
    return TrainingConfigOut(enabled=_enabled(session))


@router.post("/observations", response_model=ObservationOut, status_code=201)
def create_observation(
    payload: ObservationIn,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> ObservationOut:
    """Record something a reviewer knows.

    Args:
        payload: What they wrote and what they pointed at.
        session: The request's session.
        user: The author.

    Returns:
        The stored observation, carrying any active rules that already cover what it
        points at. Those are information, not a refusal: an observation contradicting
        an active rule is often the signal that the old rule is wrong (ADR-021).

    Raises:
        HTTPException: 404 when Train AI mode is off, 422 when the text contains
            something that looks like personal data. The tripwire runs **here**, not
            only when a prompt is assembled: a reviewer typing while looking at real
            data is exactly where an account number gets pasted, and the only place
            the person can still fix it is the moment they press save (ADR-018).
    """
    _require_enabled(session)
    try:
        assert_clean(f"{payload.statement}\n{payload.expectation}")
    except PiiDetected as exc:
        raise HTTPException(
            HTTP_422,
            f"this looks like it contains personal data, so it was not saved: {exc}",
        ) from exc

    run = session.get(models.Run, payload.run_id) if payload.run_id else None
    row = models.TrainingObservation(
        run_id=payload.run_id,
        finding_id=payload.finding_id,
        author_user_id=user.id,
        author=user.name,
        kind=payload.kind,
        anchors=[anchor.model_dump(mode="json") for anchor in payload.anchors],
        statement=payload.statement.strip(),
        expectation=payload.expectation.strip(),
        severity_hint=payload.severity_hint,
        scope_hint=payload.scope_hint,
        customer_name=run.customer_name if run else "",
        scope_code=run.scope if run else "",
    )
    session.add(row)
    session.flush()
    # Tell the author now what already covers this, while they can still reconsider.
    # Saying it at the candidate stage says it weeks later, through an administrator,
    # about a sentence they no longer remember writing (Phase 6.1e).
    covered = conflicts.covering_rules(session, row.anchors or [], row.statement)
    repository.audit(
        session,
        "training.observation_created",
        payload.run_id,
        detail=str(row.id),
        user_id=user.id,
        actor=user.name,
    )
    out = _observation_out(row)
    out.covered_by = covered
    return out


@router.get("/observations", response_model=list[ObservationOut])
def list_observations(
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
    mine: bool = Query(default=False),
    obs_status: str | None = Query(default=None, alias="status"),
    kind: str | None = Query(default=None),
) -> list[ObservationOut]:
    """List observations, newest first.

    Args:
        session: The request's session.
        user: The caller.
        mine: Only the caller's own, which is how an author follows what became of
            what they wrote. Participation stops without that.
        obs_status: Filter by status.
        kind: Filter by kind, e.g. ``config_note`` for the configuration comments.

    Returns:
        The observations.
    """
    _require_enabled(session)
    statement = sa.select(models.TrainingObservation).order_by(
        models.TrainingObservation.created_at.desc()
    )
    if mine and user.id is not None:
        statement = statement.where(models.TrainingObservation.author_user_id == user.id)
    if obs_status:
        statement = statement.where(models.TrainingObservation.status == obs_status)
    if kind:
        statement = statement.where(models.TrainingObservation.kind == kind)
    return [_observation_out(row) for row in session.execute(statement).scalars()]


@router.patch("/observations/{observation_id}", response_model=ObservationOut)
def edit_observation(
    observation_id: int,
    payload: ObservationIn,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> ObservationOut:
    """Let the author fix what they wrote, until an administrator picks it up.

    Args:
        observation_id: The observation.
        payload: The corrected text and anchors.
        session: The request's session.
        user: The caller.

    Returns:
        The updated observation, with its version bumped so the trail survives the
        convenience.

    Raises:
        HTTPException: 404 when it does not exist, 409 once it has been queued, and
            403 when someone else wrote it.
    """
    _require_enabled(session)
    row = session.get(models.TrainingObservation, observation_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such observation")
    if row.status != "new":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"this observation is {row.status} and can no longer be edited",
        )
    if row.author_user_id is not None and user.id != row.author_user_id and not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only the author can edit this")

    try:
        assert_clean(f"{payload.statement}\n{payload.expectation}")
    except PiiDetected as exc:
        raise HTTPException(HTTP_422, f"this looks like it contains personal data: {exc}") from exc

    row.statement = payload.statement.strip()
    row.expectation = payload.expectation.strip()
    row.anchors = [anchor.model_dump(mode="json") for anchor in payload.anchors]
    row.severity_hint = payload.severity_hint
    row.scope_hint = payload.scope_hint
    row.kind = payload.kind
    row.version += 1
    session.flush()
    return _observation_out(row)


@router.post("/admin/observations/{observation_id}/reject", response_model=ObservationOut)
def reject_observation(
    observation_id: int,
    payload: ObservationDecision,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(require_admin),
) -> ObservationOut:
    """Turn an observation down, with a reason the author will read.

    The row stays. A rejection with no explanation reads as the tool ignoring the
    person, and the loop only works while people keep contributing.

    Args:
        observation_id: The observation.
        payload: The reason.
        session: The request's session.
        user: The calling administrator.

    Returns:
        The observation, now rejected.

    Raises:
        HTTPException: 404 when it does not exist.
    """
    row = session.get(models.TrainingObservation, observation_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such observation")
    row.status = "rejected"
    row.status_note = payload.reason.strip()
    session.flush()
    repository.audit(
        session,
        "training.observation_rejected",
        detail=str(row.id),
        user_id=user.id,
        actor=user.name,
    )
    return _observation_out(row)


# ------------------------------------------------------------ configuration notes


@router.get("/configs/{configuration_id}/notes", response_model=list[ObservationOut])
def list_config_notes(
    configuration_id: str,
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(current_user),
    include_inactive: bool = Query(default=False),
) -> list[ObservationOut]:
    """The standing notes on one configuration (ADR-024).

    Available whatever Train AI mode says: a note is guidance about a configuration,
    which is useful whether or not the tool is collecting training input.

    Args:
        configuration_id: The ETL configuration.
        session: The request's session.
        _user: The caller.
        include_inactive: Also return notes that have been switched off.

    Returns:
        The notes, oldest first.
    """
    statement = (
        sa.select(models.TrainingObservation)
        .where(
            models.TrainingObservation.kind == "config_note",
            models.TrainingObservation.configuration_id == configuration_id,
        )
        .order_by(models.TrainingObservation.id)
    )
    if not include_inactive:
        statement = statement.where(models.TrainingObservation.is_active)
    return [_observation_out(row) for row in session.execute(statement).scalars()]


@router.post("/configs/{configuration_id}/notes", response_model=ObservationOut, status_code=201)
def create_config_note(
    configuration_id: str,
    payload: ConfigNoteIn,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> ObservationOut:
    """Write a standing note on a configuration.

    It reaches the model as background on the next run of that configuration, and it
    lands in the admin queue as a configuration-specific comment an administrator may
    promote to a rule. On its own it never makes anything pass or fail.

    Args:
        configuration_id: The ETL configuration.
        payload: The note.
        session: The request's session.
        user: The author.

    Returns:
        The stored note.

    Raises:
        HTTPException: 422 when the text looks like it contains personal data, for the
            same reason as an observation: this is the moment it can still be fixed.
    """
    configuration_id = configuration_id.strip()
    if not configuration_id:
        raise HTTPException(HTTP_422, "a note needs a configuration id")
    try:
        assert_clean(payload.statement)
    except PiiDetected as exc:
        raise HTTPException(
            HTTP_422, f"this looks like it contains personal data, so it was not saved: {exc}"
        ) from exc

    row = models.TrainingObservation(
        author_user_id=user.id,
        author=user.name,
        kind="config_note",
        configuration_id=configuration_id,
        anchors=[{"kind": "config_path", "reference": configuration_id}],
        statement=payload.statement.strip(),
        severity_hint=payload.severity_hint,
        scope_hint="customer",
    )
    session.add(row)
    session.flush()
    repository.audit(
        session,
        "training.config_note_created",
        detail=configuration_id,
        user_id=user.id,
        actor=user.name,
    )
    return _observation_out(row)


@router.patch("/config-notes/{note_id}", response_model=ObservationOut)
def edit_config_note(
    note_id: int,
    payload: ConfigNoteIn,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> ObservationOut:
    """Reword a note, keeping what it said before.

    Always allowed, unlike an ordinary observation: a note's job is to stay true about
    a configuration that keeps being run. The earlier wording is kept in ``revisions``.

    Args:
        note_id: The note.
        payload: The new wording.
        session: The request's session.
        user: The caller.

    Returns:
        The updated note.

    Raises:
        HTTPException: 404 when it is not a configuration note, 422 on personal data.
    """
    row = session.get(models.TrainingObservation, note_id)
    if row is None or row.kind != "config_note":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such configuration note")
    try:
        assert_clean(payload.statement)
    except PiiDetected as exc:
        raise HTTPException(HTTP_422, f"this looks like it contains personal data: {exc}") from exc

    revisions = list(row.revisions or [])
    revisions.append(
        {
            "version": row.version,
            "statement": row.statement,
            "at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "by": row.author,
        }
    )
    row.revisions = revisions
    row.statement = payload.statement.strip()
    row.severity_hint = payload.severity_hint
    row.version += 1
    row.author = user.name
    row.author_user_id = user.id
    session.flush()
    repository.audit(
        session,
        "training.config_note_edited",
        detail=str(note_id),
        user_id=user.id,
        actor=user.name,
    )
    return _observation_out(row)


@router.post("/config-notes/{note_id}/active", response_model=ObservationOut)
def set_config_note_active(
    note_id: int,
    is_active: bool,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> ObservationOut:
    """Switch a note off, or back on.

    Off means it stops reaching the model on the next run. The text stays.

    Args:
        note_id: The note.
        is_active: Whether it should apply.
        session: The request's session.
        user: The caller.

    Returns:
        The note.

    Raises:
        HTTPException: 404 when it is not a configuration note.
    """
    row = session.get(models.TrainingObservation, note_id)
    if row is None or row.kind != "config_note":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such configuration note")
    row.is_active = is_active
    session.flush()
    repository.audit(
        session,
        "training.config_note_enabled" if is_active else "training.config_note_disabled",
        detail=str(note_id),
        user_id=user.id,
        actor=user.name,
    )
    return _observation_out(row)


def _what_exists(session: Session) -> tuple[list[str], list[str]]:
    """The attribute names and report types the tool knows.

    Args:
        session: The request's session.

    Returns:
        The known attributes and the known report types, so a drafted rule that names
        something the tool has never heard of is caught by code rather than approved.
    """
    known_fields = sorted(
        {row.canonical_name for row in session.execute(sa.select(models.AttributeAlias)).scalars()}
    )
    report_kinds = sorted(
        {
            row.key
            for row in session.execute(
                sa.select(models.ArtifactType).where(models.ArtifactType.kind == "report")
            ).scalars()
        }
    )
    return known_fields, report_kinds


# -------------------------------------------------------------------- candidates


@router.post("/admin/candidates", response_model=list[CandidateOut], status_code=201)
def synthesize_candidates(
    payload: SynthesizeIn,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(require_admin),
) -> list[CandidateOut]:
    """Have the model draft rules from a group of observations.

    Args:
        payload: Which observations.
        session: The request's session.
        user: The calling administrator.

    Returns:
        The candidates, each validated by code before anyone sees it.

    Raises:
        HTTPException: 404 for an unknown observation, 409 when one has already been
            synthesized, and 422 when the model returns nothing usable.
    """
    rows = list(
        session.execute(
            sa.select(models.TrainingObservation).where(
                models.TrainingObservation.id.in_(payload.observation_ids)
            )
        ).scalars()
    )
    missing = set(payload.observation_ids) - {row.id for row in rows}
    if missing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no observation {sorted(missing)}")

    already = [row.id for row in rows if row.status == "synthesized"]
    if already:
        # Marked, not consumed: the row is still there and still readable, and saying
        # so beats doing the work twice (ADR-021).
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"observation(s) {already} have already been synthesized; their candidate "
            "is in the queue",
        )

    client = build_client(resolved_llm_settings(session))
    known_fields, report_kinds = _what_exists(session)
    try:
        created = synthesis.synthesize(
            session,
            client,
            rows,
            known_fields=known_fields,
            report_kinds=report_kinds,
            actor=user.name,
            user_id=user.id,
        )
    except synthesis.SynthesisError as exc:
        raise HTTPException(HTTP_422, str(exc)) from exc

    repository.audit(
        session,
        "training.synthesized",
        detail=f"{len(created)} candidate(s)",
        user_id=user.id,
        actor=user.name,
    )
    return [_candidate_out(row) for row in created]


# -------------------------------------------------------------------- front door


@router.post("/admin/front-door", response_model=FrontDoorOut)
def front_door_place(
    payload: FrontDoorIn,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(require_admin),
) -> FrontDoorOut:
    """Say what you want checked, in your own words, and let the tool place it.

    There is no new rule table and no new evaluator behind this. The model decides
    which of the existing surfaces the sentence belongs on; the drafting, the
    validation, the fingerprint and the approval are the ones the training queue
    already uses, so a candidate from here is indistinguishable from one from there.

    Args:
        payload: The sentence and where it applies.
        session: The request's session.
        user: The calling administrator.

    Returns:
        A candidate in draft, an offer to the surface that holds background, or the
        question the model needs answered. Nothing is created in the last two cases.

    Raises:
        HTTPException: 404 when Train AI mode is off, 422 when the statement looks
            like personal data or the model could not place it at all.
    """
    _require_enabled(session)
    try:
        assert_clean(payload.statement)
    except PiiDetected as exc:
        raise HTTPException(
            HTTP_422,
            f"this looks like it contains personal data, so it was not saved: {exc}",
        ) from exc

    client = build_client(resolved_llm_settings(session))
    known_fields, report_kinds = _what_exists(session)
    try:
        result = front_door.place(
            session,
            client,
            payload.statement,
            scope=payload.scope,
            known_fields=known_fields,
            report_kinds=report_kinds,
            actor=user.name,
            user_id=user.id,
        )
    except front_door.FrontDoorError as exc:
        raise HTTPException(HTTP_422, str(exc)) from exc

    repository.audit(
        session,
        "training.front_door",
        detail=(
            f"{result.surface}: "
            f"{result.candidate.id if result.candidate else 'nothing created'}"
        ),
        user_id=user.id,
        actor=user.name,
    )
    return FrontDoorOut(
        surface=result.surface,
        reason=result.reason,
        confidence=result.confidence,
        question=result.question,
        note=result.note,
        candidate=_candidate_out(result.candidate) if result.candidate else None,
        observation_id=result.observation_id,
        drafted_as=result.drafted_as,
    )


@router.get("/admin/candidates", response_model=list[CandidateOut])
def list_candidates(
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(require_admin),
    candidate_status: str | None = Query(default=None, alias="status"),
) -> list[CandidateOut]:
    """The candidate rules, newest first.

    Args:
        session: The request's session.
        _user: The calling administrator.
        candidate_status: Filter by status.

    Returns:
        The candidates. A rejected one keeps its sources, so a later attempt can
        start from them.
    """
    statement = sa.select(models.RuleCandidate).order_by(models.RuleCandidate.created_at.desc())
    if candidate_status:
        statement = statement.where(models.RuleCandidate.status == candidate_status)
    return [_candidate_out(row) for row in session.execute(statement).scalars()]


@router.post("/admin/candidates/{candidate_id}/replay", response_model=CandidateOut)
def replay_candidate(
    candidate_id: int,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(require_admin),
) -> CandidateOut:
    """Show what this rule would have changed, before anyone approves it.

    A rule that would have fired on thirty historical runs that were all fine is a
    bad rule, and this is where that becomes visible rather than next month.

    Args:
        candidate_id: The candidate.
        session: The request's session.
        user: The calling administrator.

    Returns:
        The candidate with its replay filled in.

    Raises:
        HTTPException: 404 when it does not exist.
    """
    row = session.get(models.RuleCandidate, candidate_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such candidate")
    row.replay = _replay(session, row)
    session.flush()
    repository.audit(
        session, "training.replayed", detail=str(candidate_id), user_id=user.id, actor=user.name
    )
    return _candidate_out(row)


def _replay(session: Session, candidate: models.RuleCandidate) -> dict[str, Any]:
    """Estimate what a candidate would have done to work already reviewed.

    Args:
        session: The request's session.
        candidate: The candidate.

    Returns:
        A summary the console shows before approval: how many finalized runs were
        examined and how many carry the field or expression the rule touches. This
        counts rather than re-runs the pipeline, because re-running it would re-read
        every stored file and re-ask the model; the count is what answers "is this
        rule about something that actually occurs".
    """
    limit = int(resolve(session, "training.replay_runs").value)
    runs = list(
        session.execute(
            sa.select(models.Run)
            .where(models.Run.status == "finalized")
            .order_by(models.Run.created_at.desc())
            .limit(limit)
        ).scalars()
    )
    body = dict(candidate.body or {})
    field = str(body.get("field", ""))

    touched = 0
    already_ok = 0
    for run in runs:
        findings = session.execute(
            sa.select(models.Finding).where(models.Finding.run_id == run.id)
        ).scalars()
        for finding in findings:
            if field and field.lower() in (finding.title or "").lower():
                touched += 1
                if finding.review_status == "false_positive":
                    already_ok += 1

    return {
        "runs_examined": len(runs),
        "runs_available": len(runs),
        "related_findings": touched,
        "previously_dismissed": already_ok,
        "note": (
            "Counts related findings on recent finalized runs. A rule that touches "
            "many findings reviewers already dismissed is one to narrow before it is "
            "approved."
        ),
    }


@router.post("/admin/candidates/{candidate_id}/approve", response_model=CandidateOut)
def approve_candidate(
    candidate_id: int,
    payload: CandidateDecision,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(require_admin),
) -> CandidateOut:
    """Approve a candidate, which creates the rule in shadow.

    Args:
        candidate_id: The candidate.
        payload: The decision, optionally narrowing the scope.
        session: The request's session.
        user: The calling administrator.

    Returns:
        The candidate, now approved.

    Raises:
        HTTPException: 404 when it does not exist, 422 when it cannot become a rule or
            when it overlaps an existing rule and no resolution was given
            (Phase 6.11g).
    """
    row = session.get(models.RuleCandidate, candidate_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such candidate")

    into_shadow = not payload.activate_now and bool(
        resolve(session, "training.shadow_default").value
    )
    try:
        synthesis.approve(
            session,
            row,
            scope=payload.scope,
            into_shadow=into_shadow,
            actor=user.name,
            user_id=user.id,
            note=payload.note,
            resolution=payload.resolution,
        )
    except synthesis.SynthesisError as exc:
        raise HTTPException(HTTP_422, str(exc)) from exc

    repository.audit(
        session,
        "training.candidate_approved",
        detail=str(candidate_id),
        user_id=user.id,
        actor=user.name,
    )
    return _candidate_out(row)


@router.post("/admin/candidates/{candidate_id}/reject", response_model=CandidateOut)
def reject_candidate(
    candidate_id: int,
    payload: ObservationDecision,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(require_admin),
) -> CandidateOut:
    """Turn a candidate down, keeping it and its sources.

    Args:
        candidate_id: The candidate.
        payload: The reason.
        session: The request's session.
        user: The calling administrator.

    Returns:
        The candidate, now rejected.

    Raises:
        HTTPException: 404 when it does not exist.
    """
    row = session.get(models.RuleCandidate, candidate_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such candidate")
    row.status = "rejected"
    row.admin_note = payload.reason.strip()
    row.decided_by = user.name
    row.decided_by_user_id = user.id
    row.decided_at = dt.datetime.now(dt.timezone.utc)
    session.flush()
    repository.audit(
        session,
        "training.candidate_rejected",
        detail=str(candidate_id),
        user_id=user.id,
        actor=user.name,
    )
    return _candidate_out(row)


# ------------------------------------------------------------------ the rules screen


def _rule_rows(session: Session) -> list[tuple[str, Any]]:
    """Every rule the tool holds, whatever its origin.

    Args:
        session: The request's session.

    Returns:
        Pairs of rule kind and row, across the three rule surfaces. One screen for
        all of them, because a learned rule nobody can find is worse than no learned
        rule: nobody knows why a finding appeared.
    """
    rows: list[tuple[str, Any]] = []
    for kind, table in (
        ("check", models.CheckDefinitionRow),
        ("compliance_rule", models.ComplianceRuleRow),
        ("field_constraint", models.FieldConstraint),
        ("programme_rule", models.ProgrammeRule),
    ):
        rows.extend((kind, row) for row in session.execute(sa.select(table)).scalars())
    return rows


def _statistics(session: Session) -> dict[str, tuple[int, int, dt.datetime | None]]:
    """Per-rule fired count, dismissal count, and when it last fired.

    Args:
        session: The request's session.

    Returns:
        Rule reference to (fired, dismissed, last fired). Without these two counters
        alert fatigue is invisible until reviewers have already stopped reading the
        queue.
    """
    stats: dict[str, tuple[int, int, dt.datetime | None]] = {}
    rows = session.execute(
        sa.select(
            models.Finding.rule_ref,
            sa.func.count(),
            sa.func.sum(sa.case((models.Finding.review_status == "false_positive", 1), else_=0)),
            sa.func.max(models.Finding.reviewed_at),
        )
        .where(models.Finding.rule_ref != "")
        .group_by(models.Finding.rule_ref)
    ).all()
    for ref, fired, dismissed, last in rows:
        stats[str(ref)] = (int(fired or 0), int(dismissed or 0), last)
    return stats


def _summary(rule_kind: str, row: Any) -> str:
    """One line saying what a rule actually checks.

    Args:
        rule_kind: Which rule surface.
        row: The rule.

    Returns:
        The summary the rules screen searches and shows.
    """
    if rule_kind == "field_constraint":
        return f"{row.field} {row.constraint} {row.value}"
    if rule_kind == "programme_rule":
        return f"{row.scope_code} {row.strictness}: {row.text}"
    if rule_kind == "check":
        return str(row.expression or row.instruction)
    return str((row.requirement or {}).get("json_path_contains", ""))


@router.get("/admin/rules", response_model=list[RuleOut])
def list_rules(
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(require_admin),
    state: str = Query(default="active"),
    search: str = Query(default=""),
) -> list[RuleOut]:
    """Every rule, searchable, filtered to active by default.

    This is the screen someone opens when a finding surprises them, so it has to
    answer "what made this fire" quickly.

    Args:
        session: The request's session.
        _user: The calling administrator.
        state: Which state to show, or ``all``. Active by default: the others are one
            click away, so nothing is hidden and nothing is in the way.
        search: Matches the name, the reasoning, and what the rule checks.

    Returns:
        The rules, worst dismissal rate first so the noisy ones surface.
    """
    return collect_rules(session, state=state, search=search)


def collect_rules(session: Session, state: str = "active", search: str = "") -> list[RuleOut]:
    """Gather the rules for the screen.

    Separate from the endpoint so other handlers can reuse it: calling a FastAPI
    route function directly passes its ``Query`` defaults as objects rather than
    values, which fails in a way that only shows up at runtime.

    Args:
        session: An open session.
        state: Which state to show, or ``all``.
        search: Matches the name, the reasoning, and what the rule checks.

    Returns:
        The rules, worst dismissal rate first.
    """
    stats = _statistics(session)
    needle = search.strip().lower()
    out: list[RuleOut] = []

    for rule_kind, row in _rule_rows(session):
        if state != "all" and row.state != state:
            continue
        summary = _summary(rule_kind, row)
        name = getattr(row, "name", "") or getattr(row, "title", "") or getattr(row, "field", "")
        if needle and needle not in f"{name} {summary} {row.reasoning}".lower():
            continue

        fired, dismissed, last = stats.get(f"{rule_kind}:{row.id}", (0, 0, None))
        deleted_at = getattr(row, "deleted_at", None)
        out.append(
            RuleOut(
                id=row.id,
                rule_kind=rule_kind,
                name=name,
                summary=summary,
                reasoning=row.reasoning,
                severity=getattr(row, "severity", "medium"),
                scope=row.scope,
                state=row.state,
                origin=getattr(row, "origin", "admin"),
                fired=fired,
                dismissed=dismissed,
                dismissal_rate=round(dismissed / fired, 3) if fired else 0.0,
                last_fired_at=last,
                source_observation_ids=_sources(session, getattr(row, "candidate_id", None)),
                deleted_at=deleted_at,
                restorable_until=(
                    deleted_at + dt.timedelta(days=lifecycle.RESTORE_WINDOW_DAYS)
                    if deleted_at
                    else None
                ),
            )
        )

    out.sort(key=lambda rule: (-rule.dismissal_rate, -rule.fired, rule.name))
    return out


def _sources(session: Session, candidate_id: int | None) -> list[int]:
    """Which observations a learned rule came from.

    Args:
        session: The request's session.
        candidate_id: The candidate it was approved from, when it was learned.

    Returns:
        The observation ids, so a rule can always be traced back to what someone
        said. Empty for a rule an administrator wrote directly.
    """
    if not candidate_id:
        return []
    candidate = session.get(models.RuleCandidate, candidate_id)
    return list(candidate.source_observation_ids or []) if candidate else []


@router.post("/admin/rules/bulk", response_model=RulesBulkResult)
def act_on_rules(
    payload: RulesBulkAction,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(require_admin),
) -> RulesBulkResult:
    """Apply one state change to several rules under one typed word (ADR-032).

    Args:
        payload: The rules, the action, the typed word and an optional note.
        session: The request's session.
        user: The calling administrator.

    Returns:
        How many changed and which could not (as ``kind:id: reason``).

    Raises:
        HTTPException: 400 when the word does not match the action.
    """
    if payload.confirm.strip().lower() != payload.action:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"type {payload.action!r} to confirm; this applies to every future run",
        )
    who: dict[str, Any] = {"actor": user.name, "user_id": user.id, "note": payload.note}
    handlers = {
        "enable": lifecycle.enable_rule,
        "activate": lifecycle.enable_rule,
        "disable": lifecycle.disable_rule,
        "delete": lifecycle.delete_rule,
        "restore": lifecycle.restore_rule,
    }
    changed = 0
    failed: list[str] = []
    for item in payload.items:
        try:
            handlers[payload.action](session, item.rule_kind, item.id, **who)
            changed += 1
        except lifecycle.LifecycleError as exc:
            failed.append(f"{item.rule_kind}:{item.id}: {exc}")
    repository.audit(
        session,
        f"rule.bulk.{payload.action}",
        detail=f"{changed} of {len(payload.items)}",
        user_id=user.id,
        actor=user.name,
    )
    return RulesBulkResult(changed=changed, failed=failed)


@router.post("/admin/rules/{rule_kind}/{rule_id}/action", response_model=RuleOut)
def act_on_rule(
    rule_kind: str,
    rule_id: int,
    payload: RuleAction,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(require_admin),
) -> RuleOut:
    """Enable, disable, delete, restore, or activate a rule.

    Each asks the administrator to type the word, because a rule change reaches every
    future run and a typed word is the cheapest way to be sure the click was meant.

    Args:
        rule_kind: Which rule surface.
        rule_id: The rule.
        payload: The action and the typed confirmation.
        session: The request's session.
        user: The calling administrator.

    Returns:
        The rule in its new state.

    Raises:
        HTTPException: 400 when the confirmation does not match, 404 when the rule
            does not exist, and 409 when the restore window has passed.
    """
    if payload.confirm.strip().lower() != payload.action:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"type {payload.action!r} to confirm; this applies to every future run",
        )

    actions = {
        "enable": lambda: lifecycle.enable_rule(session, rule_kind, rule_id, **who),
        "activate": lambda: lifecycle.enable_rule(session, rule_kind, rule_id, **who),
        "disable": lambda: lifecycle.disable_rule(session, rule_kind, rule_id, **who),
        "delete": lambda: lifecycle.delete_rule(session, rule_kind, rule_id, **who),
        "restore": lambda: lifecycle.restore_rule(session, rule_kind, rule_id, **who),
    }
    who: dict[str, Any] = {"actor": user.name, "user_id": user.id, "note": payload.note}

    try:
        actions[payload.action]()
    except lifecycle.LifecycleError as exc:
        message = str(exc)
        code = status.HTTP_404_NOT_FOUND if "no " in message else status.HTTP_409_CONFLICT
        raise HTTPException(code, message) from exc

    repository.audit(
        session,
        f"rule.{payload.action}d",
        detail=f"{rule_kind}:{rule_id}",
        user_id=user.id,
        actor=user.name,
    )
    return next(
        rule
        for rule in collect_rules(session, state="all")
        if rule.rule_kind == rule_kind and rule.id == rule_id
    )


@router.get("/admin/rules/{rule_kind}/{rule_id}/history", response_model=list[RuleStateChangeOut])
def rule_history(
    rule_kind: str,
    rule_id: int,
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(require_admin),
) -> list[RuleStateChangeOut]:
    """Every move this rule has made, and who made it.

    Args:
        rule_kind: Which rule surface.
        rule_id: The rule.
        session: The request's session.
        _user: The calling administrator.

    Returns:
        The state changes, newest first.
    """
    rows = session.execute(
        sa.select(models.RuleStateChange)
        .where(
            models.RuleStateChange.rule_kind == rule_kind,
            models.RuleStateChange.rule_id == rule_id,
        )
        .order_by(models.RuleStateChange.at.desc())
    ).scalars()
    return [
        RuleStateChangeOut(
            id=row.id,
            from_state=row.from_state,
            to_state=row.to_state,
            note=row.note,
            actor=row.actor,
            at=row.at,
        )
        for row in rows
    ]
