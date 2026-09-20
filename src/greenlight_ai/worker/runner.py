"""Running one run: build the context from the database, execute, write back.

This is where the Phase 2 pipeline meets the service. The stage code is unchanged; this
module supplies its inputs from the database and persists what it produced, including
per-stage status so a retry resumes at the last good stage rather than repeating work
(``docs/design.md`` "Processing pipeline").
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Final

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.checks.guides import GuideEntry, guide_lines
from greenlight_ai.meaning.render import effective_entries, meaning_lines
from greenlight_ai.db import catalog, models, repository, versions
from greenlight_ai.db.cache import DbCache, record_calls
from greenlight_ai.db.session import session_scope
from greenlight_ai.db.types import utcnow
from greenlight_ai.llm.cache import LLMCache
from greenlight_ai.llm.client import CallLog
from greenlight_ai.llm.factory import build_client
from greenlight_ai.llm.settings import LLMSettings
from greenlight_ai.pipeline.context import (
    RECHECK_STAGES,
    STAGE_ORDER,
    ReportPart,
    RunContext,
    StageRecord,
)
from greenlight_ai.pipeline.guidance import RunGuidance
from greenlight_ai.pipeline.run import PipelineError, run_pipeline

__all__ = ["execute_run", "recheck_run", "build_context"]

_LOG: Final = logging.getLogger(__name__)

#: The two uploaded kinds that are not reports. Everything else a run carries is one,
#: including report types an administrator defined (ADR-020).
_NON_REPORT_KINDS: Final[frozenset[str]] = frozenset({"osl", "config"})


def build_guidance(session: Session, run: models.Run) -> RunGuidance:
    """Collect what an administrator configured about this run's context.

    Args:
        session: An open session.
        run: The run row.

    Returns:
        The guidance. Empty when nothing is configured, in which case every prompt is
        exactly what it was before any of this existed (ADR-020).
    """
    scope = catalog.scope_for(session, run.scope)
    return RunGuidance(
        scope_label=scope.label if scope else "",
        scope_instructions=scope.standing_instructions if scope else "",
        has_suppressions=run.has_suppressions,
        deliverable_count=run.deliverable_count,
        outputs_validated=run.outputs_validated,
        delivery_notes=run.delivery_notes,
        config_notes=tuple(str(n) for n in (run.config_notes_snapshot or [])),
        credit_date=run.credit_date.isoformat() if run.credit_date else "",
        scope_code=run.scope,
        programme_rules=tuple(
            (row.id, row.title, row.text, row.strictness)
            for row in session.execute(
                sa.select(models.ProgrammeRule)
                .where(
                    models.ProgrammeRule.scope_code == run.scope,
                    models.ProgrammeRule.state.in_(("active", "shadow")),
                )
                .order_by(models.ProgrammeRule.sort_order, models.ProgrammeRule.id)
            ).scalars()
        ),
        programme_keywords={s.code: tuple(s.keywords) for s in catalog.load_scopes(session)},
        artifact_context={
            artifact.key: artifact.ai_context
            for artifact in catalog.load_artifacts(session)
            if artifact.ai_context.strip()
        },
        validation_guides=tuple(
            guide_lines(
                artifact.label,
                [GuideEntry.model_validate(entry) for entry in artifact.guide_entries],
            )
            for artifact in catalog.load_artifacts(session)
            if artifact.guide_entries
        )
        + tuple(
            block
            for block in (
                meaning_lines(
                    effective_entries(session, run.scope or ""),
                    scope.label if scope is not None else "",
                ),
            )
            if block
        ),
    )


def _parts(session: Session, run: models.Run, data_dir: Path) -> dict[str, list[ReportPart]]:
    """Group a run's uploaded report files by kind, in upload order.

    Args:
        session: An open session; unused, kept so the helper reads beside the others.
        run: The run row, whose files are already loaded.
        data_dir: The shared volume.

    Returns:
        Report kind to its parts. The ordinary case is one part per kind; a campaign
        that delivers several files of one type gets one entry each, labelled
        (ADR-021).
    """
    del session
    grouped: dict[str, list[ReportPart]] = {}
    for file in sorted(run.files, key=lambda f: (f.kind, f.part, f.id)):
        if file.kind in _NON_REPORT_KINDS:
            continue
        grouped.setdefault(file.kind, []).append(
            ReportPart(
                label=file.part_label,
                ordinal=file.part,
                path=data_dir / file.storage_key,
            )
        )
    return grouped


def build_context(
    session: Session,
    run: models.Run,
    data_dir: Path,
    llm_settings: LLMSettings,
    factory: sessionmaker[Session],
    call_log: CallLog | None = None,
) -> RunContext:
    """Assemble a pipeline context for a stored run.

    Args:
        session: An open session.
        run: The run row.
        data_dir: The shared volume.
        llm_settings: Adapter settings.
        factory: The session factory, for the database-backed cache.
        call_log: Where call statistics accumulate.

    Returns:
        The context, with previously completed stages marked done so a resumed run skips
        them.

    Raises:
        ValueError: When the run is missing its OSL or config, which means the upload
            was accepted without them and is a programming error rather than bad input.
    """
    paths = {file.kind: data_dir / file.storage_key for file in run.files}
    if "osl" not in paths or "config" not in paths:
        raise ValueError(f"run {run.id} is missing its OSL or config file")

    cache = LLMCache(
        backend=DbCache(factory),
        model=llm_settings.model,
        prompt_version=llm_settings.prompt_version,
    )
    log = call_log or CallLog()
    client = build_client(llm_settings, cache=cache, call_log=log)

    context = RunContext(
        run_id=str(run.id),
        osl_path=paths["osl"],
        config_path=paths["config"],
        report_paths={k: v for k, v in paths.items() if k not in _NON_REPORT_KINDS},
        report_parts=_parts(session, run, data_dir),
        client=client,
        customer=run.customer_name,
        admin=repository.load_admin_config(
            session, run.customer_name, run.configuration_id, run.scope or ""
        ),
        guidance=build_guidance(session, run),
        aliases=repository.load_aliases(session, run.customer_name),
        masked_columns=repository.load_masked_columns(session),
        rules_version=run.rules_version,
        verify_lenses=llm_settings.verify_lenses,
        max_lens_calls=llm_settings.max_lens_calls_per_run,
    )

    for row in session.execute(
        sa.select(models.RunStage).where(models.RunStage.run_id == run.id)
    ).scalars():
        context.stages[row.stage] = StageRecord(  # type: ignore[index]
            stage=row.stage,  # type: ignore[arg-type]
            status=row.status,  # type: ignore[arg-type]
            duration_ms=row.duration_ms,
            llm_calls=row.llm_calls,
            cache_hits=row.cache_hits,
            tokens=row.tokens,
            error=row.error,
        )
    return context


def execute_run(
    factory: sessionmaker[Session],
    run_id: int,
    data_dir: Path,
    llm_settings: LLMSettings | None = None,
) -> str:
    """Run the pipeline for one stored run.

    Args:
        factory: The session factory.
        run_id: Which run.
        data_dir: The shared volume.
        llm_settings: Adapter settings; read from the environment when omitted.

    Returns:
        The run's status afterwards: ``"needs_review"`` or ``"failed"``.

    Raises:
        PipelineError: When a stage fails. The run is marked failed and the error stored
            before this propagates, so the queue can decide about a retry while the UI
            already shows what happened.
    """
    settings = llm_settings or LLMSettings.from_env()
    call_log = CallLog()

    with session_scope(factory) as session:
        run = session.get(models.Run, run_id)
        if run is None:
            raise ValueError(f"run {run_id} does not exist")
        run.status = "running"
        run.started_at = run.started_at or utcnow()
        run.error = ""
        run.model_used = settings.model
        run.prompt_version = settings.prompt_version
        run.definition_versions = versions.current_versions(session)
        context = build_context(session, run, data_dir, settings, factory, call_log)
        resume_from = context.resume_from()

    _LOG.info("run %d: executing from stage %s", run_id, resume_from)

    failure: PipelineError | None = None
    try:
        run_pipeline(context, stages=STAGE_ORDER, resume=True)
    except PipelineError as exc:
        failure = exc

    with session_scope(factory) as session:
        run = session.get(models.Run, run_id)
        if run is None:  # pragma: no cover - the run cannot vanish mid-flight
            raise ValueError(f"run {run_id} disappeared while running")
        repository.save_context(session, run, context)
        record_calls(session, call_log, run.id)

        if failure is None:
            run.status = "needs_review"
            run.current_stage = STAGE_ORDER[-1]
            run.finished_at = utcnow()
            repository.audit(session, "run.completed", run.id, f"{len(context.findings)} findings")
        else:
            run.status = "failed"
            run.current_stage = failure.stage
            run.error = failure.reason[:2000]
            repository.audit(session, "run.failed", run.id, failure.stage)
        status = run.status

    if failure is not None:
        raise failure
    return status


def recheck_run(
    factory: sessionmaker[Session],
    run_id: int,
    data_dir: Path,
    llm_settings: LLMSettings | None = None,
) -> int:
    """Rebuild findings after a user edited a rule or a trace.

    Only stages 5 to 7 run and none of them calls a model, so this takes seconds and
    costs nothing (``docs/design.md`` "Re-check path").

    Args:
        factory: The session factory.
        run_id: Which run.
        data_dir: The shared volume.
        llm_settings: Adapter settings; read from the environment when omitted.

    Returns:
        How many findings the run has afterwards.

    Raises:
        PipelineError: When a re-check stage fails.
    """
    settings = llm_settings or LLMSettings.from_env()
    call_log = CallLog()

    with session_scope(factory) as session:
        run = session.get(models.Run, run_id)
        if run is None:
            raise ValueError(f"run {run_id} does not exist")

        context = build_context(session, run, data_dir, settings, factory, call_log)
        # Stages 1 to 4 are not re-run, so their outputs come from the database.
        context.rules = repository.load_rules(session, run_id)
        context.elements = repository.load_elements(session, run_id)
        context.traces = repository.load_traces(session, run_id)
        context.findings = [
            f for f in repository.load_findings(session, run_id) if f.review_status != "undecided"
        ]
        context.rules_version = run.rules_version + 1
        for name in RECHECK_STAGES:
            context.record(name).status = "pending"
        parsed_needed = True

    if parsed_needed:
        run_pipeline(context, stages=("s1_parse",), resume=False)
    run_pipeline(context, stages=RECHECK_STAGES, resume=False)

    if call_log.records:  # pragma: no cover - a guard against a future stage adding a call
        _LOG.warning("re-check made %d LLM call(s); it must make none", len(call_log.records))

    with session_scope(factory) as session:
        run = session.get(models.Run, run_id)
        if run is None:  # pragma: no cover
            raise ValueError(f"run {run_id} disappeared during re-check")
        run.rules_version = context.rules_version
        repository.save_context(session, run, context)
        repository.audit(session, "run.rechecked", run.id, f"v{context.rules_version}")
        count = len(context.findings)
    return count
