"""Meaning: requirement mappings per scope, proposed by the model and confirmed here.

Phase 6.10, ADR-033. The model proposes, a person confirms, code compiles.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Final

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from greenlight_ai.api import schemas_meaning as wire
from greenlight_ai.api.deps import (
    DELETE_WORD,
    CurrentUser,
    get_data_dir,
    get_session,
    require_admin,
)
from greenlight_ai.db import catalog, models, repository, versions
from greenlight_ai.db.types import utcnow
from greenlight_ai.llm.cache import LLMCache
from greenlight_ai.llm.client import LLMError
from greenlight_ai.llm.factory import build_client
from greenlight_ai.meaning import compile as compiler
from greenlight_ai.meaning import interview, samples as scoped

__all__ = ["router"]

_LOG: Final = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/meaning", tags=["admin"], dependencies=[Depends(require_admin)])


def _scope(session: Session, code: str) -> str:
    scope = code.strip().upper()
    if scope and catalog.scope_for(session, scope) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no programme {scope!r}")
    return scope


def _compiled(session: Session, entry: models.MeaningEntry) -> tuple[bool, bool]:
    name = compiler.check_name(entry)
    check = session.execute(
        sa.select(models.CheckDefinitionRow.state).where(
            models.CheckDefinitionRow.name == name,
            models.CheckDefinitionRow.origin == compiler.MEANING_ORIGIN,
        )
    ).scalar_one_or_none()
    rule = session.execute(
        sa.select(models.ComplianceRuleRow.state).where(
            models.ComplianceRuleRow.name == name,
            models.ComplianceRuleRow.origin == compiler.MEANING_ORIGIN,
        )
    ).scalar_one_or_none()
    return (check is not None and check != "deleted", rule is not None and rule != "deleted")


def _out(session: Session, row: models.MeaningEntry) -> wire.MeaningEntryOut:
    check, rule = _compiled(session, row)
    return wire.MeaningEntryOut(
        id=row.id,
        scope_code=row.scope_code or "",
        key=row.key,
        osl_section=row.osl_section,
        osl_phrase=row.osl_phrase,
        requirement_text=row.requirement_text,
        config_path=row.config_path,
        report_cells=list(row.report_cells or []),
        meaning=row.meaning,
        validate=row.validate,
        comparison=row.comparison,
        tolerance=row.tolerance,
        examples=list(row.examples or []),
        compliance_suggestion=row.compliance_suggestion,
        status=row.status,
        question=row.question,
        note=row.note,
        confidence=row.confidence,
        proposed_by=row.proposed_by,
        confirmed_by=row.confirmed_by,
        confirmed_at=row.confirmed_at,
        updated_at=row.updated_at,
        compiled_check=check,
        compiled_compliance=rule,
    )


def _snapshot(session: Session, scope: str, actor: str, summary: str) -> None:
    rows = session.execute(
        sa.select(models.MeaningEntry)
        .where(models.MeaningEntry.scope_code == scope)
        .order_by(models.MeaningEntry.id)
    ).scalars()
    snapshot = {
        "scope": scope,
        "entries": [
            {
                "id": r.id,
                "key": r.key,
                "status": r.status,
                "config_path": r.config_path,
                "report_cells": r.report_cells,
                "requirement_text": r.requirement_text,
                "validate": r.validate,
                "comparison": r.comparison,
                "note": r.note,
            }
            for r in rows
        ],
    }
    versions.record_meaning_version(session, scope or "global", snapshot, actor, summary)


@router.get("", response_model=list[wire.MeaningEntryOut])
def list_entries(
    scope_code: str = Query(default=""),
    session: Session = Depends(get_session),
) -> list[wire.MeaningEntryOut]:
    """Every entry of one scope, in OSL order.

    Args:
        scope_code: ``""`` for global, else a programme code.
        session: The request's session.

    Returns:
        The entries.
    """
    scope = _scope(session, scope_code)
    rows = session.execute(
        sa.select(models.MeaningEntry)
        .where(models.MeaningEntry.scope_code == scope)
        .order_by(models.MeaningEntry.osl_section, models.MeaningEntry.id)
    ).scalars()
    return [_out(session, row) for row in rows]


@router.get("/samples", response_model=wire.MeaningSamplesOut)
def samples_for_scope(
    scope_code: str = Query(default=""),
    session: Session = Depends(get_session),
) -> wire.MeaningSamplesOut:
    """Which samples an interview on this scope would read, and what is missing.

    Args:
        scope_code: ``""`` for global, else a programme code.
        session: The request's session.

    Returns:
        The samples (the programme's own where it has any, else global) and the
        required artifact keys with none.
    """
    scope = _scope(session, scope_code)
    chosen = scoped.samples_in_scope(session, scope)
    out = [
        wire.MeaningSampleOut(
            artifact_key=key,
            label=sample.label,
            sample_id=sample.id,
            scope_code=sample.scope_code or "",
            filename=sample.filename,
        )
        for key, samples in sorted(chosen.items())
        for sample in samples
    ]
    missing = [key for key in ("osl", "config") if key not in chosen]
    return wire.MeaningSamplesOut(samples=out, missing=missing)


@router.post("/propose", response_model=wire.ProposeOut)
def propose_entries(
    payload: wire.ProposeIn,
    request: Request,
    session: Session = Depends(get_session),
    data_dir: Path = Depends(get_data_dir),
    user: CurrentUser = Depends(require_admin),
) -> wire.ProposeOut:
    """Run the mapping interview for one scope (one cached model call per OSL section).

    Args:
        payload: The scope.
        request: The incoming request, for the model settings and the cache.
        session: The request's session.
        data_dir: The shared volume.
        user: The calling administrator.

    Returns:
        Counts of what was proposed.

    Raises:
        HTTPException: 409 when a sample in scope is missing, 502 when the model fails.
    """
    scope = _scope(session, payload.scope_code)
    settings = request.app.state.llm_settings
    client = build_client(
        settings,
        cache=LLMCache(
            backend=request.app.state.llm_cache_backend,
            model=settings.model,
            prompt_version=settings.prompt_version,
        ),
    )
    try:
        result = interview.propose(session, scope, client, data_dir)
    except interview.InterviewError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"the model could not map this scope: {exc}"
        ) from exc
    repository.audit(
        session,
        "admin.meaning_proposed",
        detail=f"{scope or 'global'}: {result.proposed} proposed, {result.open} open",
        user_id=user.id,
        actor=user.name,
    )
    return wire.ProposeOut(**result.as_dict())


@router.post("", response_model=wire.MeaningEntryOut, status_code=status.HTTP_201_CREATED)
def create_entry(
    payload: wire.MeaningEntryIn,
    session: Session = Depends(get_session),
    data_dir: Path = Depends(get_data_dir),
    user: CurrentUser = Depends(require_admin),
) -> wire.MeaningEntryOut:
    """Write a requirement mapping by hand; it starts confirmed and compiles at once.

    Args:
        payload: The entry.
        session: The request's session.
        data_dir: The shared volume.
        user: The calling administrator.

    Returns:
        The stored entry.

    Raises:
        HTTPException: 409 when the key exists in this scope.
    """
    scope = _scope(session, payload.scope_code)
    key = payload.key.strip().lower()
    if session.execute(
        sa.select(models.MeaningEntry.id).where(
            models.MeaningEntry.scope_code == scope, models.MeaningEntry.key == key
        )
    ).scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, f"{key!r} already exists in this scope")
    row = models.MeaningEntry(
        scope_code=scope,
        key=key,
        osl_section=payload.osl_section,
        osl_phrase=payload.osl_phrase,
        requirement_text=payload.requirement_text,
        config_path=payload.config_path.strip(),
        report_cells=[cell.model_dump() for cell in payload.report_cells],
        meaning=payload.meaning,
        validate=payload.validate_text,
        comparison=payload.comparison,
        tolerance=payload.tolerance,
        note=payload.note,
        compliance_suggestion=payload.compliance_suggestion,
        status="confirmed",
        proposed_by="admin",
        confirmed_by=user.name,
        confirmed_at=utcnow(),
    )
    session.add(row)
    session.flush()
    compiler.compile_entry(session, row, data_dir)
    repository.audit(
        session, "admin.meaning_created", detail=f"{scope}:{key}", user_id=user.id, actor=user.name
    )
    _snapshot(session, scope, user.name, f"entry added: {key}")
    return _out(session, row)


def _apply(row: models.MeaningEntry, payload: wire.MeaningEntryPatch) -> None:
    for field in (
        "osl_section",
        "osl_phrase",
        "requirement_text",
        "config_path",
        "meaning",
        "comparison",
        "tolerance",
        "note",
    ):
        value = getattr(payload, field)
        if value is not None:
            setattr(row, field, value.strip() if isinstance(value, str) else value)
    if payload.validate_text is not None:
        row.validate = payload.validate_text
    if payload.report_cells is not None:
        row.report_cells = [cell.model_dump() for cell in payload.report_cells]
    if payload.drop_compliance_suggestion:
        row.compliance_suggestion = None
    elif payload.compliance_suggestion is not None:
        row.compliance_suggestion = payload.compliance_suggestion


def _decide(
    session: Session, row: models.MeaningEntry, to_status: str, user: CurrentUser, data_dir: Path
) -> None:
    row.status = to_status
    if to_status == "confirmed":
        row.confirmed_by = user.name
        row.confirmed_at = utcnow()
        row.question = ""
        compiler.compile_entry(session, row, data_dir)
    elif to_status == "rejected":
        compiler.retire_entry(session, row)
    row.updated_at = utcnow()


@router.patch("/{entry_id}", response_model=wire.MeaningEntryOut)
def edit_entry(
    entry_id: int,
    payload: wire.MeaningEntryPatch,
    session: Session = Depends(get_session),
    data_dir: Path = Depends(get_data_dir),
    user: CurrentUser = Depends(require_admin),
) -> wire.MeaningEntryOut:
    """Correct an entry, decide it, or both. Confirming compiles; rejecting retires.

    Args:
        entry_id: The entry.
        payload: What changes.
        session: The request's session.
        data_dir: The shared volume.
        user: The calling administrator.

    Returns:
        The entry after the change.

    Raises:
        HTTPException: 404 when it does not exist.
    """
    row = session.get(models.MeaningEntry, entry_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no meaning entry {entry_id}")
    _apply(row, payload)
    if payload.status is not None:
        _decide(session, row, payload.status, user, data_dir)
    elif row.status == "confirmed":
        compiler.compile_entry(session, row, data_dir)
    row.updated_at = utcnow()
    session.flush()
    repository.audit(
        session,
        "admin.meaning_edited",
        detail=f"{row.id}:{row.status}",
        user_id=user.id,
        actor=user.name,
    )
    _snapshot(session, row.scope_code or "", user.name, f"{row.key}: {payload.status or 'edited'}")
    return _out(session, row)


@router.post("/bulk", response_model=dict[str, Any])
def bulk(
    payload: wire.MeaningBulkIn,
    session: Session = Depends(get_session),
    data_dir: Path = Depends(get_data_dir),
    user: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    """Confirm, reject, or delete several entries; delete needs the typed word.

    Args:
        payload: The ids, the action, and the word.
        session: The request's session.
        data_dir: The shared volume.
        user: The calling administrator.

    Returns:
        ``{"changed": n, "missing": [ids]}``.

    Raises:
        HTTPException: 400 when a delete lacks the word.
    """
    if payload.action == "delete" and payload.confirm.strip().lower() != DELETE_WORD:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"type {DELETE_WORD!r} to confirm")
    changed = 0
    missing: list[int] = []
    scopes: set[str] = set()
    for entry_id in payload.ids:
        row = session.get(models.MeaningEntry, entry_id)
        if row is None:
            missing.append(entry_id)
            continue
        scopes.add(row.scope_code or "")
        if payload.action == "delete":
            compiler.retire_entry(session, row)
            session.delete(row)
        else:
            _decide(
                session,
                row,
                "confirmed" if payload.action == "confirm" else "rejected",
                user,
                data_dir,
            )
        changed += 1
    session.flush()
    repository.audit(
        session,
        f"admin.meaning_bulk_{payload.action}",
        detail=f"{changed} of {len(payload.ids)}",
        user_id=user.id,
        actor=user.name,
    )
    for scope in scopes:
        _snapshot(session, scope, user.name, f"bulk {payload.action}: {changed}")
    return {"changed": changed, "missing": missing}
