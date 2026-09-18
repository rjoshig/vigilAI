"""Run endpoints: create, list, inspect, edit, re-check, review, clone, stats."""

from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path
from typing import Annotated, Any, Final, Optional, cast

import sqlalchemy as sa
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile as StarletteUploadFile

from vigilai.api import schemas
from vigilai.api.deps import CurrentUser, current_user, get_data_dir, get_session
from vigilai.api.uploads import UploadError, store_upload
from vigilai.db import catalog, models, repository
from vigilai.db.queue import JobQueue
from vigilai.db.types import utcnow
from vigilai.pipeline.s4_trace import describe_rule
from vigilai.report.pdf import renderer_available
from vigilai.rules.schema import Rule
from vigilai.worker.app import TASK_RECHECK, TASK_RUN_PIPELINE

__all__ = ["router"]

_LOG: Final = logging.getLogger(__name__)

router = APIRouter(prefix="/runs", tags=["runs"])

#: Starlette renamed its 422 constant and deprecated the old spelling; the number is
#: stable across every version we support, so it is named here once.
HTTP_422_UNPROCESSABLE: Final[int] = 422

#: At most this many runs may be queued for one order number at a time. A user who
#: submits the same order repeatedly is almost always retrying, not asking for parallel
#: work, and each run costs model tokens.
MAX_QUEUED_PER_ORDER: Final[int] = 3


def _queue(request: Request, session: Session) -> JobQueue:
    """Build a queue bound to this request's session.

    Args:
        request: The incoming request, carrying the backend flag.
        session: The request's session.

    Returns:
        The queue.
    """
    return JobQueue(session, request.app.state.is_sqlite)


def _severity_counts(session: Session, run_id: int) -> dict[str, int]:
    """Count a run's findings by severity.

    Args:
        session: An open session.
        run_id: The run.

    Returns:
        Severity to count, with every severity present so the UI needs no defaults.
    """
    rows = session.execute(
        sa.select(models.Finding.severity, sa.func.count())
        .where(models.Finding.run_id == run_id)
        .group_by(models.Finding.severity)
    ).all()
    counts = {"high": 0, "medium": 0, "low": 0, "review": 0}
    for severity, count in rows:
        counts[severity] = int(count)
    return counts


def _can_finalize(session: Session, run_id: int) -> bool:
    """Whether every high-severity finding has a decision (ADR-015).

    Args:
        session: An open session.
        run_id: The run.

    Returns:
        ``True`` when the gate is satisfied.
    """
    undecided = session.execute(
        sa.select(sa.func.count())
        .select_from(models.Finding)
        .where(
            models.Finding.run_id == run_id,
            models.Finding.severity == "high",
            models.Finding.review_status == "undecided",
        )
    ).scalar_one()
    return int(undecided) == 0


def _summary(
    session: Session, run: models.Run, queue: JobQueue | None = None
) -> schemas.RunSummary:
    """Build the list view of a run.

    Args:
        session: An open session.
        run: The run row.
        queue: The queue, when a position should be reported.

    Returns:
        The summary.
    """
    counts = _severity_counts(session, run.id)
    return schemas.RunSummary(
        id=run.id,
        customer_name=run.customer_name,
        order_number=run.order_number,
        configuration_id=run.configuration_id,
        status=run.status,
        current_stage=run.current_stage,
        error=run.error,
        created_at=run.created_at,
        finished_at=run.finished_at,
        queue_position=queue.queue_position(run.id) if queue is not None else None,
        scope=run.scope,
        scope_label=_scope_label(session, run.scope),
        **counts,
    )


def _scope_label(session: Session, code: str) -> str:
    """The human name for a run's delivery programme.

    Args:
        session: An open session.
        code: The stored scope code.

    Returns:
        The label, or the code itself when the scope has since been removed. A run
        whose programme was deleted still shows what it was submitted as.
    """
    if not code:
        return ""
    found = catalog.scope_for(session, code)
    return found.label if found else code


def _detail(session: Session, run: models.Run, queue: JobQueue) -> schemas.RunDetail:
    """Build the full view of a run.

    Args:
        session: An open session.
        run: The run row.
        queue: The queue, for the position.

    Returns:
        The detail payload.
    """
    base = _summary(session, run, queue)
    finalized = (
        session.execute(
            sa.select(sa.func.count())
            .select_from(models.FinalReport)
            .where(models.FinalReport.run_id == run.id)
        ).scalar_one()
        > 0
    )
    stages = [
        schemas.StageInfo.model_validate(row)
        for row in session.execute(
            sa.select(models.RunStage)
            .where(models.RunStage.run_id == run.id)
            .order_by(models.RunStage.stage)
        ).scalars()
    ]
    return schemas.RunDetail(
        **base.model_dump(),
        pdf_available=renderer_available(),
        notes=run.notes,
        run_date=run.run_date,
        rules_version=run.rules_version,
        model_used=run.model_used,
        prompt_version=run.prompt_version,
        summary=run.summary,
        top_issues=list(run.top_issues or []),
        rerun_reason=run.rerun_reason,
        input_fingerprint=run.input_fingerprint,
        has_suppressions=run.has_suppressions,
        can_finalize=_can_finalize(session, run.id),
        finalized=finalized,
        stages=stages,
        files={f.kind: f.filename for f in run.files},
    )


@router.get("/options", response_model=schemas.NewRunOptions)
def new_run_options(
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(current_user),
) -> schemas.NewRunOptions:
    """What the new-run form should offer.

    Generated from the admin catalog rather than hardcoded, so switching a report type
    off removes its upload slot without a deploy (ADR-020).

    Args:
        session: The request's session.
        _user: The caller.

    Returns:
        The active upload slots and delivery programmes, in display order.
    """
    catalog.seed_defaults(session)
    accept = {"osl": ".docx", "config": ".json"}
    return schemas.NewRunOptions(
        artifacts=[
            schemas.ArtifactSlot(
                key=artifact.key,
                label=artifact.label,
                kind=artifact.kind,
                description=artifact.description,
                is_required=artifact.is_required,
                accept=accept.get(artifact.kind, ".xlsx"),
            )
            for artifact in catalog.load_artifacts(session, active_only=True)
        ],
        scopes=[
            schemas.ScopeOption(code=s.code, label=s.label, description=s.description)
            for s in catalog.load_scopes(session, active_only=True)
        ],
    )


@router.post("", response_model=schemas.CreateRunResult, status_code=status.HTTP_201_CREATED)
async def create_run(  # noqa: PLR0913 - a multipart form has many fields by nature
    request: Request,
    customer_name: Annotated[str, Form()],
    order_number: Annotated[str, Form()],
    configuration_id: Annotated[str, Form()],
    osl: Annotated[UploadFile, File()],
    config: Annotated[UploadFile, File()],
    notes: Annotated[str, Form()] = "",
    run_date: Annotated[Optional[str], Form()] = None,
    rerun_reason: Annotated[str, Form()] = "",
    scope: Annotated[str, Form()] = "",
    has_suppressions: Annotated[bool, Form()] = False,
    session: Session = Depends(get_session),
    data_dir: Path = Depends(get_data_dir),
    user: CurrentUser = Depends(current_user),
) -> schemas.CreateRunResult:
    """Create a run from uploaded files.

    Identical inputs return the existing run rather than spending tokens again, unless
    a ``rerun_reason`` is supplied, which is recorded and shown in the audit log
    (``docs/design.md`` "LLM cost controls").

    Report slots come from the admin catalog rather than a fixed list, so they are read
    off the raw form (ADR-020).

    Args:
        request: The incoming request, which also carries the dynamic report uploads.
        customer_name: Who the delivery is for.
        order_number: The order.
        configuration_id: The config's own identifier.
        osl: The requirement spec.
        config: The ETL configuration.
        notes: Anything the reviewer should know.
        run_date: The run date, ISO format.
        rerun_reason: Required to re-run identical inputs.
        scope: The delivery programme, e.g. ``"AM"``. Gives the model the compliance
            regime the delivery sits under (ADR-020).
        has_suppressions: Whether suppressions were applied. Defaults to no, because
            assuming they were would let a missing suppression pass unremarked.
        session: The request's session.
        data_dir: The shared volume.
        user: The caller.

    Returns:
        The new run, or the duplicate it matched.

    Raises:
        HTTPException: 400 when an upload is rejected or no report is supplied, 409 when
            too many runs are already queued for this order.
    """
    # Report slots are whatever the admin catalog has active, so a type added in the
    # console needs no code change here (ADR-020).
    catalog.seed_defaults(session)
    active = {a.key for a in catalog.load_artifacts(session, active_only=True)}
    form = await request.form()

    uploads: list[tuple[str, UploadFile]] = [("osl", osl), ("config", config)]
    for key in sorted(active - {"osl", "config"}):
        value = form.get(key)
        # `request.form()` yields Starlette's UploadFile; FastAPI's is a subclass, so
        # testing against the subclass silently matched nothing and every report was
        # dropped. Test the base.
        if isinstance(value, StarletteUploadFile) and value.filename:
            uploads.append((key, cast(UploadFile, value)))

    if len(uploads) < 3:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "at least one output report must be uploaded"
        )

    queue = _queue(request, session)
    already_queued = session.execute(
        sa.select(sa.func.count())
        .select_from(models.Run)
        .where(models.Run.order_number == order_number, models.Run.status == "queued")
    ).scalar_one()
    if int(already_queued) >= MAX_QUEUED_PER_ORDER:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{already_queued} runs are already queued for order {order_number}; "
            "wait for one to finish",
        )

    run = models.Run(
        customer_name=customer_name.strip(),
        order_number=order_number.strip(),
        configuration_id=configuration_id.strip(),
        notes=notes,
        run_date=_parse_date(run_date),
        status="queued",
        user_id=user.id,
        scope=scope.strip().upper(),
        has_suppressions=has_suppressions,
    )
    session.add(run)
    session.flush()
    run.expires_at = repository.expiry_from(run.created_at or utcnow())

    stored = []
    try:
        for kind, upload in uploads:
            stored.append(
                store_upload(
                    upload.file,
                    upload.filename or kind,
                    upload.content_type or "",
                    kind,
                    data_dir,
                    str(run.id),
                )
            )
    except UploadError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    digest = repository.fingerprint(
        (f.sha256 for f in stored), repository.active_check_versions(session)
    )
    duplicate = session.execute(
        sa.select(models.Run)
        .where(
            models.Run.input_fingerprint == digest,
            models.Run.id != run.id,
            models.Run.status != "failed",
        )
        .order_by(models.Run.id.desc())
        .limit(1)
    ).scalar_one_or_none()

    if duplicate is not None and not rerun_reason.strip():
        session.delete(run)
        repository.audit(session, "run.duplicate_blocked", duplicate.id, digest[:12])
        return schemas.CreateRunResult(
            duplicate=schemas.DuplicateRun(
                run_id=duplicate.id,
                status=duplicate.status,
                created_at=duplicate.created_at,
                message=(
                    "These inputs were already run. Supply a reason to run them again; "
                    "the cache keeps the re-run cheap."
                ),
            )
        )

    run.input_fingerprint = digest
    run.rerun_reason = rerun_reason.strip()
    for file in stored:
        session.add(
            models.RunFile(
                run_id=run.id,
                kind=file.kind,
                filename=file.filename,
                storage_key=file.storage_key,
                sha256=file.sha256,
                size_bytes=file.size_bytes,
            )
        )

    _capture_config_from_upload(session, run, data_dir, stored, user)
    queue.enqueue(TASK_RUN_PIPELINE, run_id=run.id)
    repository.audit(
        session,
        "run.created",
        run.id,
        f"rerun={bool(rerun_reason.strip())} files={len(stored)}",
    )
    _LOG.info("run %d created for order %s (%d files)", run.id, order_number, len(stored))

    return schemas.CreateRunResult(
        run_id=run.id, status=run.status, queue_position=queue.queue_position(run.id)
    )


def _parse_date(value: str | None) -> dt.date | None:
    """Parse an ISO date from a form field.

    Args:
        value: The submitted string.

    Returns:
        The date, or ``None`` when absent or unparseable. A bad date is not worth
        rejecting an upload over; it is a label, not an input to the comparison.
    """
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value.strip())
    except ValueError:
        return None


def _capture_config_from_upload(
    session: Session, run: models.Run, data_dir: Path, stored: list[Any], user: CurrentUser
) -> None:
    """Record the uploaded config in the versioned config history.

    Args:
        session: An open session.
        run: The run row.
        data_dir: The shared volume.
        stored: The stored files.
        user: Who submitted the run, recorded against the captured version so the
            config history can show who ran it (ADR-022).
    """
    config_file = next((f for f in stored if f.kind == "config"), None)
    if config_file is None:
        return
    try:
        content = json.loads((data_dir / config_file.storage_key).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # An unreadable config is the pipeline's problem to report as a finding, not a
        # reason to reject the upload here.
        return
    if not isinstance(content, dict):
        return
    captured = repository.capture_config(
        session,
        run.configuration_id,
        run.customer_name,
        content,
        config_file.sha256,
        created_by=user.id,
        created_by_name=user.name,
    )
    run.config_last_modified = captured.last_modified


@router.get("", response_model=list[schemas.RunSummary])
def list_runs(
    request: Request,
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(current_user),
    customer: str | None = Query(default=None),
    run_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[schemas.RunSummary]:
    """List runs, newest first.

    Args:
        request: The incoming request.
        session: The request's session.
        _user: The caller.
        customer: Filter by customer.
        run_status: Filter by status.
        limit: Page size.
        offset: Page offset.

    Returns:
        The runs.
    """
    statement = sa.select(models.Run).order_by(models.Run.id.desc()).limit(limit).offset(offset)
    if customer:
        statement = statement.where(models.Run.customer_name == customer)
    if run_status:
        statement = statement.where(models.Run.status == run_status)

    queue = _queue(request, session)
    return [_summary(session, run, queue) for run in session.execute(statement).scalars()]


def _get_run(session: Session, run_id: int) -> models.Run:
    """Load a run or raise 404.

    Args:
        session: An open session.
        run_id: The run.

    Returns:
        The run row.

    Raises:
        HTTPException: 404 when the run does not exist or has been purged.
    """
    run = session.get(models.Run, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"run {run_id} not found")
    return run


@router.get("/{run_id}", response_model=schemas.RunDetail)
def get_run(
    run_id: int,
    request: Request,
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(current_user),
) -> schemas.RunDetail:
    """Read one run, including live stage progress.

    Polled every three seconds by the UI, which is plenty at this scale and avoids
    WebSocket setup (``docs/design.md`` "API endpoints").

    Args:
        run_id: The run.
        request: The incoming request.
        session: The request's session.
        _user: The caller.

    Returns:
        The run detail.
    """
    run = _get_run(session, run_id)
    return _detail(session, run, _queue(request, session))


@router.get("/{run_id}/findings", response_model=list[schemas.FindingOut])
def list_findings(
    run_id: int,
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(current_user),
    severity: str | None = Query(default=None),
    finding_type: str | None = Query(default=None, alias="type"),
) -> list[schemas.FindingOut]:
    """List a run's findings, worst first.

    Args:
        run_id: The run.
        session: The request's session.
        _user: The caller.
        severity: Filter by severity.
        finding_type: Filter by finding type.

    Returns:
        The findings.
    """
    _get_run(session, run_id)
    order = sa.case(
        {"high": 0, "medium": 1, "low": 2, "review": 3}, value=models.Finding.severity, else_=9
    )
    statement = (
        sa.select(models.Finding)
        .where(models.Finding.run_id == run_id)
        .order_by(order, models.Finding.id)
    )
    if severity:
        statement = statement.where(models.Finding.severity == severity)
    if finding_type:
        statement = statement.where(models.Finding.type == finding_type)
    return [schemas.FindingOut.model_validate(row) for row in session.execute(statement).scalars()]


@router.get("/{run_id}/requirements", response_model=schemas.RequirementsOut)
def get_requirements(
    run_id: int,
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(current_user),
) -> schemas.RequirementsOut:
    """Read the traceability matrix.

    Args:
        run_id: The run.
        session: The request's session.
        _user: The caller.

    Returns:
        Rules, traces, and config elements.
    """
    run = _get_run(session, run_id)
    rules = repository.load_rules(session, run_id)
    return schemas.RequirementsOut(
        rules=[
            schemas.RuleOut(
                rule_id=rule.rule_id,
                source=rule.source,
                req_type=rule.req_type,
                summary=describe_rule(rule),
                confidence=rule.confidence,
                source_ref=rule.source_ref,
                source_text=rule.source_text,
                rule=rule.model_dump(mode="json"),
            )
            for rule in rules
        ],
        traces=[
            schemas.TraceOut(**trace.model_dump())
            for trace in repository.load_traces(session, run_id)
        ],
        elements=[
            element.model_dump(mode="json") for element in repository.load_elements(session, run_id)
        ],
        rules_version=run.rules_version,
    )


@router.put("/{run_id}/requirements", response_model=schemas.RecheckResult)
def edit_requirements(
    run_id: int,
    payload: schemas.RequirementsPut,
    request: Request,
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(current_user),
) -> schemas.RecheckResult:
    """Edit requirements or trace links, then queue a re-check.

    Editing bumps ``rules.version``; findings record the version that produced them, so
    an earlier report stays reproducible (``docs/design.md`` "Data model").

    Args:
        run_id: The run.
        payload: The edits.
        request: The incoming request.
        session: The request's session.
        _user: The caller.

    Returns:
        The new rules version and confirmation that a re-check was queued.

    Raises:
        HTTPException: 404 when a named rule does not belong to this run, 422 when an
            edited rule fails validation.
    """
    run = _get_run(session, run_id)
    version = run.rules_version + 1

    for edit in payload.edits:
        rule_row = session.execute(
            sa.select(models.Rule).where(
                models.Rule.run_id == run_id, models.Rule.rule_id == edit.rule_id
            )
        ).scalar_one_or_none()
        if rule_row is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"rule {edit.rule_id} is not part of run {run_id}"
            )

        if edit.rule is not None:
            try:
                validated = Rule(**{**edit.rule, "rule_id": edit.rule_id, "source": "user"})
            except ValueError as exc:
                raise HTTPException(HTTP_422_UNPROCESSABLE, f"{edit.rule_id}: {exc}") from exc
            rule_row.rule = validated.model_dump(mode="json")
            rule_row.source = "user"
            rule_row.confidence = validated.confidence
            rule_row.version = version
            rule_row.edited_at = utcnow()
            rule_row.edited_by = _user.name

        if edit.element_id is not None or edit.clear_link:
            trace_row = session.execute(
                sa.select(models.Trace).where(
                    models.Trace.run_id == run_id, models.Trace.rule_id == edit.rule_id
                )
            ).scalar_one_or_none()
            if trace_row is None:
                trace_row = models.Trace(run_id=run_id, rule_id=edit.rule_id, verdict="not_related")
                session.add(trace_row)
            trace_row.element_id = None if edit.clear_link else edit.element_id
            trace_row.verdict = "not_related" if edit.clear_link else "implemented"
            trace_row.reason = edit.reason or "Corrected by a reviewer."
            trace_row.by_code = False
            trace_row.edited_by = _user.name

    run.rules_version = version
    repository.audit(
        session, "run.requirements_edited", run_id, f"v{version} edits={len(payload.edits)}"
    )
    _queue(request, session).enqueue(TASK_RECHECK, run_id=run_id)

    return schemas.RecheckResult(run_id=run_id, rules_version=version, queued=True)


@router.post("/{run_id}/recheck", response_model=schemas.RecheckResult)
def recheck(
    run_id: int,
    request: Request,
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(current_user),
) -> schemas.RecheckResult:
    """Queue a re-check without editing anything.

    Args:
        run_id: The run.
        request: The incoming request.
        session: The request's session.
        _user: The caller.

    Returns:
        Confirmation that a re-check was queued.
    """
    run = _get_run(session, run_id)
    _queue(request, session).enqueue(TASK_RECHECK, run_id=run_id)
    repository.audit(session, "run.recheck_requested", run_id)
    return schemas.RecheckResult(run_id=run_id, rules_version=run.rules_version, queued=True)


@router.post(
    "/{run_id}/clone", response_model=schemas.CloneResult, status_code=status.HTTP_201_CREATED
)
def clone_run(
    run_id: int,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> schemas.CloneResult:
    """Create a draft run prefilled from an existing one.

    The clone is left in ``draft`` rather than queued: its files must be uploaded
    afresh, because the point of cloning is usually to re-run with corrected inputs.

    Args:
        run_id: The run to copy.
        session: The request's session.
        user: The caller, recorded as the clone's submitter.

    Returns:
        The new run.
    """
    source = _get_run(session, run_id)
    clone = models.Run(
        customer_name=source.customer_name,
        order_number=source.order_number,
        configuration_id=source.configuration_id,
        notes=source.notes,
        run_date=source.run_date,
        status="draft",
        cloned_from_id=source.id,
        user_id=user.id,
        scope=source.scope,
        has_suppressions=source.has_suppressions,
    )
    session.add(clone)
    session.flush()
    clone.expires_at = repository.expiry_from(clone.created_at or utcnow())
    repository.audit(
        session,
        "run.cloned",
        clone.id,
        f"from {source.id}",
        user_id=user.id,
        actor=user.name,
    )
    return schemas.CloneResult(run_id=clone.id, cloned_from=source.id, status=clone.status)


@router.get("/{run_id}/stats", response_model=schemas.RunStats)
def run_stats(
    run_id: int,
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(current_user),
) -> schemas.RunStats:
    """Report stage timings, model calls, tokens, and cache hits.

    Args:
        run_id: The run.
        session: The request's session.
        _user: The caller.

    Returns:
        The statistics.
    """
    _get_run(session, run_id)
    stages = [
        schemas.StageInfo.model_validate(row)
        for row in session.execute(
            sa.select(models.RunStage)
            .where(models.RunStage.run_id == run_id)
            .order_by(models.RunStage.stage)
        ).scalars()
    ]
    totals = session.execute(
        sa.select(
            sa.func.count(),
            sa.func.coalesce(sa.func.sum(sa.cast(models.LlmCall.cached, sa.Integer)), 0),
            sa.func.coalesce(sa.func.sum(models.LlmCall.prompt_tokens), 0),
            sa.func.coalesce(sa.func.sum(models.LlmCall.completion_tokens), 0),
        ).where(models.LlmCall.run_id == run_id)
    ).one()

    return schemas.RunStats(
        run_id=run_id,
        total_duration_ms=sum(s.duration_ms for s in stages),
        llm_calls=int(totals[0]),
        cache_hits=int(totals[1]),
        prompt_tokens=int(totals[2]),
        completion_tokens=int(totals[3]),
        stages=stages,
    )
