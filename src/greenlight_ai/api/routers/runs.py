"""Run endpoints: create, list, inspect, edit, re-check, review, clone, stats."""

from __future__ import annotations

import datetime as dt
import json
import logging
import time
from dataclasses import asdict
import shutil
import tempfile
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

from greenlight_ai.api import provenance, gate, schemas
from greenlight_ai.api.deps import (
    CurrentUser,
    current_user,
    get_auth_settings,
    get_data_dir,
    get_session,
)
from greenlight_ai import availability, spend
from greenlight_ai.auth.settings import AuthSettings
from greenlight_ai.checks import artifact_match, field_labels
from greenlight_ai.api.uploads import UploadError, store_upload
from greenlight_ai.config.store import resolve
from greenlight_ai.db import catalog, models, repository, drift
from greenlight_ai.db.queue import JobQueue
from greenlight_ai.db.types import utcnow
from greenlight_ai.llm.factory import build_client
from greenlight_ai.llm.settings import resolved_llm_settings
from greenlight_ai.parsers import detect
from greenlight_ai.parsers.base import NON_REPORT_KINDS, RECORD_LAYOUT_KIND, ParseError
from greenlight_ai.parsers.reports import parser_for
from greenlight_ai.pipeline.s4_trace import describe_rule
from greenlight_ai.report.pdf import renderer_available
from greenlight_ai.rules.schema import Rule
from greenlight_ai.worker.app import TASK_RECHECK, TASK_RUN_PIPELINE

__all__ = ["router"]

_LOG: Final = logging.getLogger(__name__)

router = APIRouter(prefix="/runs", tags=["runs"])

#: Starlette renamed its 422 constant and deprecated the old spelling; the number is
#: stable across every version we support, so it is named here once.
HTTP_422_UNPROCESSABLE: Final[int] = 422

#: At most this many runs may be queued for one order number at a time. A user who
#: submits the same order repeatedly is almost always retrying, not asking for parallel
#: work, and each run costs model tokens.
#: The default cap on runs queued for one order number. An administrator can change
#: it in the console; this is the value used when they have not (ADR-023).
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
        # Shadow findings are counted for the Rules screen, never here (ADR-021).
        .where(models.Finding.run_id == run_id, models.Finding.shadow.is_(False)).group_by(
            models.Finding.severity
        )
    ).all()
    counts = {"high": 0, "medium": 0, "low": 0, "review": 0}
    for severity, count in rows:
        counts[severity] = int(count)
    return counts


def _can_finalize(session: Session, run: models.Run, user_auth: bool = False) -> tuple[bool, str]:
    """Whether the run can be frozen, and what stands in the way.

    The gate is ADR-035's, which widens ADR-015's: every high and every ``review``
    finding decided, and every coverage gap acknowledged. The one implementation lives
    in :mod:`greenlight_ai.api.gate` so the answer the screen shows and the answer
    finalize enforces cannot differ.

    Args:
        session: An open session.
        run: The run row.
        user_auth: Whether login is on, which the four-eyes rule needs (ADR-036).

    Returns:
        Whether the gate is satisfied, and the reason when it is not.
    """
    state = gate.gate_state(session, run, user_auth)
    return state.can_finalize, state.reason


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
        submitted_by=_submitter(session, run.user_id),
        scope=run.scope,
        scope_label=_scope_label(session, run.scope),
        credit_date=run.credit_date,
        **counts,
    )


def _submitter(session: Session, user_id: int | None) -> str:
    """The name to show beside a run.

    Args:
        session: An open session.
        user_id: The submitter's account id.

    Returns:
        Their display name. There is always a current user (ADR-022), so this is
        empty only for a run stored before accounts existed.
    """
    if user_id is None:
        return ""
    row = session.get(models.User, user_id)
    return row.name or row.username if row is not None else ""


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


def _detail(
    session: Session, run: models.Run, queue: JobQueue, user_auth: bool = False
) -> schemas.RunDetail:
    """Build the full view of a run.

    Args:
        session: An open session.
        run: The run row.
        queue: The queue, for the position.

    Returns:
        The detail payload.
    """
    base = _summary(session, run, queue)
    can_finalize, blocked_by = _can_finalize(session, run, user_auth)
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
        # `or ""` rather than the bare column: a database migrated before the
        # backfill holds NULL here, and the review screen is the wrong place to
        # discover that. Empty and absent mean the same thing to a reader.
        error_detail=run.error_detail or "",
        notes=run.notes,
        rules_version=run.rules_version,
        model_used=run.model_used,
        prompt_version=run.prompt_version,
        summary=run.summary,
        top_issues=list(run.top_issues or []),
        rerun_reason=run.rerun_reason,
        input_fingerprint=run.input_fingerprint,
        has_suppressions=run.has_suppressions,
        config_notes=[str(n) for n in (run.config_notes_snapshot or [])],
        can_finalize=can_finalize,
        finalize_blocked_by=blocked_by,
        finalized=finalized,
        stages=stages,
        files={f.kind: f.filename for f in run.files},
        mismatches=[_mismatch_out(row) for row in _mismatches_for(session, run.id)],
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
    accept = {"osl": ".docx,.pdf", "config": ".json", RECORD_LAYOUT_KIND: ".xlsx"}
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
    osl: Annotated[UploadFile, File()],
    config: Annotated[UploadFile, File()],
    # Informational: the order's ETL configuration number. Optional and free to
    # repeat; the run's own id is its identity, and the config history is keyed on
    # this only when it is given.
    configuration_id: Annotated[str, Form(min_length=1)],
    notes: Annotated[str, Form()] = "",
    credit_date: Annotated[Optional[str], Form()] = None,
    rerun_reason: Annotated[str, Form()] = "",
    scope: Annotated[str, Form()] = "",
    has_suppressions: Annotated[bool, Form()] = False,
    deliverable_count: Annotated[int, Form()] = 0,
    outputs_validated: Annotated[int, Form()] = 0,
    delivery_notes: Annotated[str, Form()] = "",
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
        credit_date: The credit date the delivery is cut as of, ISO format. Optional,
            and when given the artifacts are checked for it.
        rerun_reason: Required to re-run identical inputs.
        scope: The delivery programme, e.g. ``"AM"``. Gives the model the compliance
            regime the delivery sits under (ADR-020).
        has_suppressions: Whether suppressions were applied. Defaults to no, because
            assuming they were would let a missing suppression pass unremarked.
        deliverable_count: How many deliverables the campaign has. Zero means the
            submitter did not say. Code checks it against the files that arrive
            (ADR-021).
        outputs_validated: How many of those this run covers. Zero means unstated.
        delivery_notes: Anything else about the delivery worth knowing.
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

    # (key, file, part ordinal, part label). A slot may carry several files: some
    # campaigns deliver one field distribution per segment (ADR-021). `getlist` is
    # what makes that work; `get` would silently keep only the last.
    uploads: list[tuple[str, UploadFile, int, str]] = [
        ("osl", osl, 1, ""),
        ("config", config, 1, ""),
    ]
    for key in sorted(active - {"osl", "config"}):
        labels = [str(value) for value in form.getlist(f"{key}__label")]
        ordinal = 0
        for value in form.getlist(key):
            # `request.form()` yields Starlette's UploadFile; FastAPI's is a subclass,
            # so testing against the subclass silently matched nothing and every
            # report was dropped. Test the base.
            if not isinstance(value, StarletteUploadFile) or not value.filename:
                continue
            ordinal += 1
            label = labels[ordinal - 1] if ordinal <= len(labels) else ""
            uploads.append((key, cast(UploadFile, value), ordinal, label.strip()))

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
    per_order = int(resolve(session, "queue.per_order_limit").value)
    if int(already_queued) >= per_order:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{already_queued} runs are already queued for order {order_number}; "
            "wait for one to finish",
        )

    # A rate limit on starting work, so a bulk submission cannot empty the token
    # budget in a minute. The run is refused rather than queued, because the person
    # is standing there and a queue they cannot see the end of is worse than a clear
    # "try again shortly" (ADR-023).
    window_s = int(resolve(session, "queue.window_s").value)
    started_recently = int(
        session.execute(
            sa.select(sa.func.count())
            .select_from(models.Run)
            .where(models.Run.created_at >= utcnow() - dt.timedelta(seconds=window_s))
        ).scalar_one()
    )
    starts_allowed = int(resolve(session, "queue.starts_per_window").value)
    if started_recently >= starts_allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"{started_recently} runs have started in the last {window_s // 60} minutes, "
            f"which is the configured limit of {starts_allowed}. Try again shortly.",
        )

    # Before a single byte is stored: is the tool accepting work at all? (Phase 6.14j)
    # Refusing here rather than after the upload means somebody who cannot submit has
    # not waited for seven files to travel first.
    available = availability.read(session)
    if not available.accepting:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            available.message
            or "Greenlight AI is not accepting submissions at the moment. Try again shortly.",
        )

    run = models.Run(
        customer_name=customer_name.strip(),
        order_number=order_number.strip(),
        configuration_id=configuration_id.strip(),
        notes=notes,
        credit_date=_parse_date(credit_date),
        status="queued",
        user_id=user.id,
        scope=scope.strip().upper(),
        has_suppressions=has_suppressions,
        deliverable_count=max(0, deliverable_count),
        outputs_validated=max(0, outputs_validated),
        delivery_notes=delivery_notes.strip(),
        # Copied at submission so the run page and the frozen report show what the
        # model was told even after the note is edited or switched off (ADR-024).
        config_notes_snapshot=repository.active_config_notes(session, configuration_id.strip()),
    )
    session.add(run)
    session.flush()
    run.expires_at = repository.expiry_from(run.created_at or utcnow())
    # The product-code catalogue as it stands right now (Phase 6.22c). The catalogue
    # keeps no history, so this is what makes a finalized report reproduce: a re-check
    # next year expands the codes exactly as this run did, whatever an administrator
    # has since changed. Empty on a deployment that defines no codes.
    run.product_code_attributes = repository.product_code_snapshot(
        repository.load_product_codes(session, run.customer_name, run.configuration_id, run.scope)
    )

    stored: list[tuple[Any, int, str]] = []
    try:
        for kind, upload, part, part_label in uploads:
            stored.append(
                (
                    store_upload(
                        upload.file,
                        upload.filename or kind,
                        upload.content_type or "",
                        kind,
                        data_dir,
                        str(run.id),
                        part=part,
                    ),
                    part,
                    part_label,
                )
            )
    except UploadError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    digest = repository.fingerprint(
        (f.sha256 for f, _, _ in stored), repository.active_check_versions(session)
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
    for file, part, part_label in stored:
        session.add(
            models.RunFile(
                run_id=run.id,
                kind=file.kind,
                part=part,
                part_label=part_label,
                filename=file.filename,
                storage_key=file.storage_key,
                sha256=file.sha256,
                size_bytes=file.size_bytes,
            )
        )

    _capture_config_from_upload(session, run, data_dir, stored, user)

    # Do these artifacts belong to the delivery that was just described? Code compares,
    # before anything is asked of the model (ADR-041). A run whose artifacts agree
    # queues exactly as it always did; one whose artifacts disagree is held with its
    # files intact, so accepting costs a click rather than a re-upload.
    mismatches = _record_mismatches(session, run, data_dir, stored)
    if mismatches:
        run.status = "held"
        session.flush()
        repository.audit(
            session,
            "run.held",
            run.id,
            ",".join(row.field for row in mismatches),
        )
        _LOG.info(
            "run %d held: %s disagree with the artifacts",
            run.id,
            ", ".join(row.field for row in mismatches),
        )
        return schemas.CreateRunResult(
            run_id=run.id,
            status=run.status,
            mismatches=[_mismatch_out(row) for row in mismatches],
        )

    # The change-your-mind window. `run_after` already means "earliest a job may be
    # claimed", so this is the existing mechanism given a purpose rather than a new one.
    queue.enqueue(TASK_RUN_PIPELINE, run_id=run.id, run_after=utcnow() + available.grace)
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


def _mismatches_for(session: Session, run_id: int) -> list[models.ArtifactMismatch]:
    """Read a run's artifact mismatches, oldest first.

    Args:
        session: An open session.
        run_id: The run.

    Returns:
        Every mismatch recorded for the run, accepted or not. Accepted ones are kept
        and shown, because a reviewer signing the delivery should see what was waived.
    """
    return list(
        session.execute(
            sa.select(models.ArtifactMismatch)
            .where(models.ArtifactMismatch.run_id == run_id)
            .order_by(models.ArtifactMismatch.id)
        ).scalars()
    )


#: How each compared field is named on screen, so the vocabulary lives in one place.
#: How long the pre-flight may spend reading reports before it gives up and leaves
#: the credit date to stage 7. The point of the check is to answer before the model is
#: involved, not to make somebody wait: a submission that takes four seconds to accept
#: is a worse experience than one whose date is confirmed a few seconds later.
PREFLIGHT_PARSE_BUDGET_S: Final[float] = 1.5

MATCH_FIELD_LABELS: Final[dict[str, str]] = {
    "configuration_id": "Configuration id",
    "customer": "Customer",
    "credit_date": "Credit date",
}


def _mismatch_out(row: models.ArtifactMismatch) -> schemas.ArtifactMismatchOut:
    """Render one stored mismatch for the wire.

    Args:
        row: The stored row.

    Returns:
        The wire model, with the field's display label filled in.
    """
    return schemas.ArtifactMismatchOut(
        id=row.id,
        field=row.field,
        label=MATCH_FIELD_LABELS.get(row.field, row.field),
        submitted=row.submitted,
        declared=row.declared,
        kind=row.kind,
        source=row.source,
        reason=row.reason,
        accepted_at=row.accepted_at,
        accepted_by=row.accepted_by,
    )


def _labelled_credit_date(
    session: Session, run: models.Run, data_dir: Path, stored: list[Any]
) -> field_labels.LabelHit | None:
    """Read the credit date a report says it is cut as of, if one says so.

    Parsing the reports here repeats work stage 1 will do, which is the honest cost of
    asking the question before the model is involved rather than at stage 7 of 9. It is
    bounded: a whole run parses in tens of milliseconds, and the alternative is paying
    for a full validation against a delivery that was cut for a different date.

    A report that cannot be parsed is skipped rather than reported — an unreadable
    workbook is the pipeline's failure to describe properly, with the parser's own
    message, not a disagreement about dates.

    Args:
        session: An open session, for the scoped labels.
        run: The run row.
        data_dir: The shared volume.
        stored: The stored files.

    Returns:
        The first labelled date found, or ``None``.
    """
    if run.credit_date is None:
        return None
    labels = field_labels.resolve_labels(
        session,
        field_labels.CREDIT_DATE,
        customer=run.customer_name,
        programme=run.scope,
        configuration_id=run.configuration_id,
    )
    # Smallest first, and stop at the first hit. Measured on this machine, parsing a
    # workbook costs about 17 ms per thousand rows: a 50,000-row DIRT is 850 ms on its
    # own, and five of those would put four seconds in front of somebody pressing
    # Submit. The as-of line lives in a small summary report far more often than in the
    # largest one, so reading in size order answers the common case in milliseconds and
    # the budget below bounds the rest. Anything not read here is still checked at
    # stage 7, which is where this check has always run.
    candidates = sorted(
        (
            (file.kind, data_dir / file.storage_key)
            for file, _, _ in stored
            # Reports only. The record layout is a schema and carries no credit date,
            # and reading it with a report parser would spend the budget on a file
            # that cannot answer (Phase 6.22b).
            if file.kind not in NON_REPORT_KINDS
        ),
        key=lambda pair: pair[1].stat().st_size if pair[1].exists() else 0,
    )
    deadline = time.monotonic() + PREFLIGHT_PARSE_BUDGET_S
    for kind, path in candidates:
        if time.monotonic() > deadline:
            _LOG.info(
                "run %d: credit-date pre-flight stopped after %.1fs; stage 7 will check it",
                run.id,
                PREFLIGHT_PARSE_BUDGET_S,
            )
            break
        try:
            document = parser_for(kind).parse(path)
        except (ParseError, OSError):
            continue
        hit = field_labels.find_labelled_value({kind: document}, labels)
        if hit is not None:
            return hit
    return None


def _record_mismatches(
    session: Session, run: models.Run, data_dir: Path, stored: list[Any]
) -> list[models.ArtifactMismatch]:
    """Compare the submission with its artifacts and store what disagrees.

    The configuration is the only artifact read here. It is small, it is already being
    decoded a few lines earlier for the config history, and it is the one artifact that
    declares its own identity. The credit date needs a labelled cell from a report and
    is compared by stage 7 until 6.14b moves it forward.

    Args:
        session: An open session.
        run: The run row, already flushed so it has an id.
        data_dir: The shared volume.
        stored: The stored files.

    Returns:
        The rows written, empty when everything agreed. An unreadable configuration
        produces no rows: that is the pipeline's failure to report, not a disagreement.
    """
    config_file = next((f for f, _, _ in stored if f.kind == "config"), None)
    if config_file is None:
        return []
    try:
        decoded = json.loads((data_dir / config_file.storage_key).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(decoded, dict):
        return []

    declared_id = decoded.get("configuration_id")
    declared_customer = decoded.get("customer")
    hit = _labelled_credit_date(session, run, data_dir, stored)
    results = (
        artifact_match.compare_configuration_id(
            run.configuration_id, declared_id if isinstance(declared_id, str) else ""
        ),
        artifact_match.compare_customer(
            run.customer_name, declared_customer if isinstance(declared_customer, str) else ""
        ),
        artifact_match.compare_credit_date(
            run.credit_date,
            hit.value if hit else "",
            hit.source if hit else "",
        ),
    )

    rows: list[models.ArtifactMismatch] = []
    for result in artifact_match.disagreements(results):
        row = models.ArtifactMismatch(
            run_id=run.id,
            field=result.field,
            submitted=result.submitted[:400],
            declared=result.declared[:400],
            kind=result.kind,
            source=result.source[:200],
        )
        session.add(row)
        rows.append(row)
    if rows:
        session.flush()
    return rows


@router.post("/{run_id}/cancel", response_model=schemas.RunSummary)
def cancel_run(
    run_id: int,
    request: Request,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> schemas.RunSummary:
    """Take back a submission that has not started (Phase 6.14j).

    The wrong file, the wrong order number, a second thought. A run that has not been
    picked up has cost nothing — no model call, no tokens, no partial state — so
    cancelling is free and leaves nothing to unwind. Once a run is under way it is not
    cancellable: stopping halfway leaves a half-validated delivery that no reviewer can
    tell from a whole one.

    The files are kept. A cancelled run stays on the list with its inputs, so the
    ordinary next step is to clone it with the mistake corrected rather than to hunt
    for seven files again.

    Args:
        run_id: The run to cancel.
        request: The incoming request, carrying the backend flag for the queue.
        session: The request's session.
        user: Who cancelled, recorded in the audit trail.

    Returns:
        The run, now cancelled.

    Raises:
        HTTPException: 404 when it does not exist, 409 when it has already started.
    """
    run = session.get(models.Run, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"run {run_id} not found")
    if run.status not in ("queued", "held"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"run {run_id} is {run.status}; only a run that has not started can be cancelled",
        )

    claimed = _queue(request, session).cancel_jobs(run_id)
    if claimed is False:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"run {run_id} was picked up a moment ago and is running now",
        )

    run.status = "cancelled"
    run.finished_at = utcnow()
    session.flush()
    repository.audit(
        session, "run.cancelled", run.id, f"was {run.status}", user_id=user.id, actor=user.name
    )
    _LOG.info("run %d cancelled by %s", run.id, user.name)
    return _summary(session, run)


@router.post("/{run_id}/match/accept", response_model=schemas.AcceptMismatchesResult)
def accept_mismatches(
    run_id: int,
    body: schemas.AcceptMismatches,
    request: Request,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> schemas.AcceptMismatchesResult:
    """Accept the artifact disagreements on a held run and let it start (ADR-041).

    Anyone who can submit a run can accept one. The check exists to put the
    disagreement in front of the person, not to route it to somebody else; who ought
    to be consulted first is a delivery-process question, not a role in the tool.

    Args:
        run_id: The held run.
        body: The reason, and optionally which fields it covers.
        request: The incoming request, carrying the backend flag for the queue.
        session: The request's session.
        user: Who accepted, recorded against every row.

    Returns:
        The run's new status and its queue position.

    Raises:
        HTTPException: 404 when the run does not exist, 409 when it is not held.
    """
    run = session.get(models.Run, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"run {run_id} not found")
    if run.status != "held":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"run {run_id} is {run.status}, not held; there is nothing to accept",
        )

    wanted = {field.strip() for field in body.fields if field.strip()}
    outstanding = list(
        session.execute(
            sa.select(models.ArtifactMismatch).where(
                models.ArtifactMismatch.run_id == run_id,
                models.ArtifactMismatch.accepted_at.is_(None),
            )
        ).scalars()
    )
    accepting = [row for row in outstanding if not wanted or row.field in wanted]
    for row in accepting:
        row.reason = body.reason.strip()
        row.accepted_at = utcnow()
        row.accepted_by = user.name
        row.accepted_by_user_id = user.id

    still_open = [row for row in outstanding if row not in accepting]
    queue = _queue(request, session)
    if not still_open:
        run.status = "queued"
        session.flush()
        queue.enqueue(
            TASK_RUN_PIPELINE,
            run_id=run.id,
            run_after=utcnow() + availability.read(session).grace,
        )
        _LOG.info("run %d accepted by %s and queued", run.id, user.name)
    repository.audit(
        session,
        "run.match_accepted",
        run.id,
        f"{len(accepting)} accepted, {len(still_open)} outstanding",
        user_id=user.id,
        actor=user.name,
    )
    return schemas.AcceptMismatchesResult(
        run_id=run.id,
        status=run.status,
        accepted=len(accepting),
        queue_position=queue.queue_position(run.id) if not still_open else None,
    )


def _parse_date(value: str | None) -> dt.date | None:
    """Parse an ISO date from a form field.

    Args:
        value: The submitted string.

    Returns:
        The date, or ``None`` when absent.

    Raises:
        HTTPException: 422 when the value is not a date. It used to become ``None``
            quietly, which switched the credit-date check off for that run with nobody
            told; a label the tool checks against is an input after all (6.13a).
    """
    if not value or not value.strip():
        return None
    try:
        return dt.date.fromisoformat(value.strip())
    except ValueError as exc:
        raise HTTPException(
            HTTP_422_UNPROCESSABLE,
            f"credit_date must be a date written YYYY-MM-DD, not {value.strip()!r}",
        ) from exc


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
    config_file = next((f for f, _, _ in stored if f.kind == "config"), None)
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
    submitted_by: int | None = Query(default=None),
    q: str | None = Query(default=None),
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
        submitted_by: Only this account's runs. An id rather than a name, because two
            people can share a display name and a link that quietly widened to both
            would be worse than one that found nobody.
        q: Free text over the fields a person remembers a run by — the order number,
            the customer, the configuration id, and the submitter's name.
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
    if submitted_by is not None:
        statement = statement.where(models.Run.user_id == submitted_by)
    if q and q.strip():
        term = f"%{q.strip()}%"
        # The submitter is on another table, so their name is matched by resolving it
        # to account ids first: a join would need an outer one for the runs stored
        # before accounts existed, and would drop them from every search.
        matching_users = [
            int(row)
            for row in session.execute(
                sa.select(models.User.id).where(
                    sa.or_(
                        models.User.name.ilike(term),
                        models.User.username.ilike(term),
                    )
                )
            ).scalars()
        ]
        wanted = [
            models.Run.order_number.ilike(term),
            models.Run.customer_name.ilike(term),
            models.Run.configuration_id.ilike(term),
        ]
        if matching_users:
            wanted.append(models.Run.user_id.in_(matching_users))
        statement = statement.where(sa.or_(*wanted))

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
    auth: AuthSettings = Depends(get_auth_settings),
) -> schemas.RunDetail:
    """Read one run, including live stage progress.

    Polled every three seconds by the UI, which is plenty at this scale and avoids
    WebSocket setup (``docs/design.md`` "API endpoints").

    Args:
        run_id: The run.
        request: The incoming request.
        session: The request's session.
        _user: The caller.
        auth: The settings the app is running with, which decide whether the
            four-eyes rule can mean anything (ADR-036).

    Returns:
        The run detail.
    """
    run = _get_run(session, run_id)
    return _detail(session, run, _queue(request, session), auth.user_auth)


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
        # A shadow rule's findings are stored and counted and shown to nobody (ADR-021).
        .where(models.Finding.run_id == run_id, models.Finding.shadow.is_(False)).order_by(
            order, models.Finding.id
        )
    )
    if severity:
        statement = statement.where(models.Finding.severity == severity)
    if finding_type:
        statement = statement.where(models.Finding.type == finding_type)
    findings = [
        schemas.FindingOut.model_validate(row) for row in session.execute(statement).scalars()
    ]
    return provenance.decorate_findings(session, findings)


@router.get("/{run_id}/rules", response_model=schemas.RunRulesOut)
def list_run_rules(
    run_id: int,
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(current_user),
) -> schemas.RunRulesOut:
    """The rules that touched this run, grouped by where they came from.

    A reviewer could see a finding and not that a colleague's observation produced the
    rule behind it (Phase 6.13b). Shadow rules are named and nothing more: their
    findings are the administrator's to look at (ADR-021, ADR-040).

    Args:
        run_id: The run.
        session: The request's session.
        _user: The caller.

    Returns:
        The rules that produced a visible finding, with counts, and the rules that ran
        silently.
    """
    _get_run(session, run_id)
    rows = session.execute(
        sa.select(models.Finding.rule_ref, models.Finding.shadow, sa.func.count())
        .where(models.Finding.run_id == run_id, models.Finding.rule_ref != "")
        .group_by(models.Finding.rule_ref, models.Finding.shadow)
    ).all()
    facts = provenance.facts_for_refs(session, (str(ref) for ref, _, _ in rows))

    applied: list[schemas.RunRuleOut] = []
    silent: list[schemas.RunRuleOut] = []
    for ref, shadow, count in rows:
        fact = facts.get(str(ref))
        if fact is None:
            continue
        entry = schemas.RunRuleOut(
            rule_ref=fact.ref,
            kind=fact.kind,
            name=fact.name,
            summary=fact.summary,
            origin=fact.origin,
            state=fact.state,
            findings=0 if shadow else int(count),
            shadow=bool(shadow),
        )
        (silent if shadow else applied).append(entry)
    applied.sort(key=lambda r: (r.origin, r.name))
    silent.sort(key=lambda r: (r.origin, r.name))
    return schemas.RunRulesOut(applied=applied, running_silently=silent)


@router.get("/{run_id}/drift", response_model=schemas.DriftOut)
def run_drift(
    run_id: int,
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(current_user),
) -> schemas.DriftOut:
    """What changed since the previous finalized run of this configuration (ADR-030).

    Args:
        run_id: The run.
        session: The request's session.
        _user: The caller.

    Returns:
        New, resolved, and carried-over findings, requirements whose value changed,
        and the configuration diff by path; or a ``reason`` when there is no earlier
        run to compare with.
    """
    run = _get_run(session, run_id)
    return drift_out(drift.compute_drift(session, run))


def drift_out(result: drift.Drift) -> schemas.DriftOut:
    """Turn a computed drift into its wire shape.

    Args:
        result: The comparison.

    Returns:
        The wire model.
    """
    return schemas.DriftOut(
        previous_run_id=result.previous_run_id,
        previous_finished_at=result.previous_finished_at,
        previous_verdict=result.previous_verdict,
        reason=result.reason,
        new=[schemas.DriftFinding(**asdict(f)) for f in result.new],
        resolved=[schemas.DriftFinding(**asdict(f)) for f in result.resolved],
        carried_not_ok=[schemas.DriftFinding(**asdict(f)) for f in result.carried_not_ok],
        requirements=[schemas.DriftRequirement(**asdict(r)) for r in result.requirements],
        config=[schemas.DriftConfigChange(**asdict(c)) for c in result.config],
        previous_config_version=result.previous_config_version,
        config_version=result.config_version,
        # Both of these existed on the wire model and were never filled: the panel
        # showed an empty list whatever the comparison found. `newly_unchecked` has
        # been computed since Phase 6.11c and has never reached a screen.
        newly_unchecked=list(result.newly_unchecked),
        record_layout=[schemas.DriftRecordLayoutChange(**asdict(c)) for c in result.record_layout],
    )


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
        credit_date=source.credit_date,
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

    # Which path produced each finding (Phase 6.16). Counted from the stored
    # findings rather than inferred from a token count: a run can make model calls
    # that produce no finding at all, and usually does.
    by_engine: dict[str, int] = {
        str(engine): int(count)
        for engine, count in session.execute(
            sa.select(models.Finding.engine, sa.func.count())
            .where(models.Finding.run_id == run_id)
            .group_by(models.Finding.engine)
        ).all()
    }

    rate = spend.rate_for(session)
    tokens = int(totals[2]) + int(totals[3])
    return schemas.RunStats(
        run_id=run_id,
        total_duration_ms=sum(s.duration_ms for s in stages),
        llm_calls=int(totals[0]),
        cache_hits=int(totals[1]),
        findings_by_engine=by_engine,
        prompt_tokens=int(totals[2]),
        completion_tokens=int(totals[3]),
        cost=round(spend.cost_of(tokens, rate), 4),
        currency=rate.currency,
        rate_per_million=rate.per_million,
        budget_tokens=resolved_llm_settings(session).max_tokens_per_run,
        stages=stages,
    )


#: Extension the detection scratch file is written under, so openpyxl recognises it.
DETECT_SUFFIX: Final[str] = ".xlsx"


def _detected_sheets(results: dict[str, detect.DetectionResult]) -> list[schemas.DetectedSheet]:
    """Convert per-sheet detection into wire models.

    Args:
        results: Sheet name to its result.

    Returns:
        One row per sheet, in workbook order.
    """
    rows: list[schemas.DetectedSheet] = []
    for name, result in results.items():
        best = result.best
        rows.append(
            schemas.DetectedSheet(
                sheet=name,
                verdict=result.verdict,
                reason=result.reason,
                key=best.key if best else None,
                label=best.label if best else None,
                score=best.score if best else 0.0,
            )
        )
    return rows


@router.post("/detect-type", response_model=schemas.TypeDetection)
def detect_type(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    data_dir: Path = Depends(get_data_dir),
    _user: CurrentUser = Depends(current_user),
) -> schemas.TypeDetection:
    """Work out what an uploaded workbook is, before a run exists.

    The file is written to a temporary path, read, and deleted. It is deliberately not
    stored: an upload that has not been assigned to a run belongs to nothing, so no
    retention rule would ever delete it and it would sit on the shared volume for good.

    Args:
        file: The workbook to identify.
        session: The request's session.
        data_dir: The shared volume, where the samples it is compared against live.
        _user: The caller.

    Returns:
        The scored candidates, a verdict the form can show as "I am not sure", and a
        per-sheet mapping so a multi-tab workbook can map to several types.

    Raises:
        HTTPException: 400 when the upload cannot be read as a workbook.
    """
    scratch = Path(tempfile.mkdtemp(prefix="greenlight-ai-detect-")) / f"upload{DETECT_SUFFIX}"
    try:
        with scratch.open("wb") as handle:
            shutil.copyfileobj(file.file, handle)
        try:
            # A model may break a tie code could not, choosing only from the shortlist
            # code produced (Phase 6.21e). Built here rather than held open, because
            # this route is called once per upload and most uploads never tie.
            client = build_client(resolved_llm_settings(session))
            result = detect.detect(session, scratch, data_dir, client)
            per_sheet = detect.detect_sheets(session, scratch, data_dir)
        except ParseError as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"could not read that file as a workbook ({exc})"
            ) from exc
    finally:
        shutil.rmtree(scratch.parent, ignore_errors=True)

    best = result.best
    return schemas.TypeDetection(
        verdict=result.verdict,
        reason=result.reason,
        key=best.key if best else None,
        label=best.label if best else None,
        score=best.score if best else 0.0,
        candidates=[
            schemas.DetectedCandidate(key=c.key, label=c.label, score=c.score)
            for c in result.candidates
        ],
        sheets=_detected_sheets(per_sheet),
    )
