"""Runtime settings, editable by an administrator (ADR-023).

Everything here is admin-only and audited. Two behaviours are worth knowing before
reading the code: a value the console has never set is not stored at all, so it keeps
following the environment, and a secret only ever travels inward.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from typing import Final

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from greenlight_ai.api.deps import CurrentUser, get_session, require_settings
from greenlight_ai.api.schemas_config import (
    ConfigChangeOut,
    ProviderTestResult,
    SettingGroupOut,
    SettingIn,
    SettingOut,
)
from greenlight_ai.chat.answer import STAGE as CHAT_STAGE
from greenlight_ai.config import registry, secrets
from greenlight_ai.config.registry import GROUPS, SETTINGS_BY_KEY
from greenlight_ai.config.store import Resolved, clear_setting, fallback, resolve, write_setting
from greenlight_ai.db import models, repository
from greenlight_ai.db.types import utcnow
from greenlight_ai.llm.factory import build_client
from greenlight_ai.llm.settings import resolved_llm_settings

__all__ = ["router"]

_LOG: Final = logging.getLogger(__name__)

#: Starlette deprecated its 422 constant; the number is stable and the import is not.
HTTP_422: Final[int] = 422

# Settings decide what the tool sends to a model, so this is the administrator's
# alone: a reviewer who could edit them could widen what leaves the deployment.
router = APIRouter(
    prefix="/admin/settings", tags=["admin"], dependencies=[Depends(require_settings)]
)


def _out(session: Session, resolved: Resolved) -> SettingOut:
    """Render one setting for the console.

    Args:
        session: The request's session.
        resolved: The effective value and its layer.

    Returns:
        The wire model, including what the value would fall back to if the override
        were removed, so the console's revert action can say what it will do.
    """
    spec = resolved.spec
    beneath = fallback(spec.key)
    return SettingOut(
        key=spec.key,
        label=spec.label,
        group=spec.group,
        kind=spec.kind,
        help=spec.help,
        source=resolved.source,
        value=None if spec.kind == "secret" else resolved.value,
        editable=spec.editable,
        restart=spec.restart,
        choices=list(spec.choices),
        minimum=spec.minimum,
        maximum=spec.maximum,
        is_set=resolved.is_set,
        last4=resolved.last4,
        fallback=None if spec.kind == "secret" else beneath.value,
        fallback_source=beneath.source,
    )


@router.get("", response_model=list[SettingGroupOut])
def list_settings(
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(require_settings),
) -> list[SettingGroupOut]:
    """Every setting, grouped, with its effective value and source.

    Args:
        session: The request's session.
        _user: The calling administrator.

    Returns:
        The sections in display order.
    """
    return [
        SettingGroupOut(
            name=group,
            settings=[
                _out(session, resolve(session, spec.key)) for spec in registry.group_of(group)
            ],
            note=_group_note(session, group),
        )
        for group in GROUPS
    ]


def _group_note(session: Session, group: str) -> str:
    """One line a section says about itself, when it has one.

    Only **Chat** does. A feature whose cost is invisible is a feature nobody can
    decide to keep, and the caps above this line mean little without the number that
    is running towards them (Phase 8f).

    Args:
        session: The request's session.
        group: The section being rendered.

    Returns:
        The line, or empty for every other section.
    """
    if group != "Chat":
        return ""
    since = utcnow() - dt.timedelta(days=30)
    asked = int(
        session.execute(
            sa.select(sa.func.count())
            .select_from(models.LlmCall)
            .where(models.LlmCall.stage == CHAT_STAGE, models.LlmCall.created_at >= since)
        ).scalar_one()
    )
    people = int(
        session.execute(
            sa.select(sa.func.count(sa.distinct(models.LlmCall.user_id))).where(
                models.LlmCall.stage == CHAT_STAGE,
                models.LlmCall.created_at >= since,
                models.LlmCall.user_id.is_not(None),
            )
        ).scalar_one()
    )
    if asked == 0:
        return "No questions have been asked in the last 30 days."
    return (
        f"{asked} question{'s' if asked != 1 else ''} asked in the last 30 days, "
        f"by {people} {'person' if people == 1 else 'people'}. Every one is counted in "
        "the usage figures like any other model call."
    )


@router.post("", response_model=SettingOut)
def save_setting(
    payload: SettingIn,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(require_settings),
) -> SettingOut:
    """Set one override, effective on the next request or job.

    Args:
        payload: The key and its new value.
        session: The request's session.
        user: The calling administrator.

    Returns:
        The setting as it now resolves.

    Raises:
        HTTPException: 404 for an unknown key, 422 when the setting is read-only or
            the value is not valid for its type, and 409 when a secret is offered
            with no master key configured.
    """
    if payload.key not in SETTINGS_BY_KEY:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{payload.key!r} is not a setting")

    try:
        resolved = write_setting(
            session, payload.key, payload.value, user_id=user.id, actor=user.name
        )
    except secrets.SecretsUnavailable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(HTTP_422, str(exc)) from exc

    repository.audit(
        session, "admin.setting_changed", detail=payload.key, user_id=user.id, actor=user.name
    )
    return _out(session, resolved)


@router.delete("/{key:path}", response_model=SettingOut)
def revert_setting(
    key: str,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(require_settings),
) -> SettingOut:
    """Remove an override so the setting follows the environment again.

    Args:
        key: The setting key.
        session: The request's session.
        user: The calling administrator.

    Returns:
        The setting as it now resolves, which is the layer beneath.

    Raises:
        HTTPException: 404 for an unknown key.
    """
    if key not in SETTINGS_BY_KEY:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{key!r} is not a setting")
    resolved = clear_setting(session, key, user_id=user.id, actor=user.name)
    repository.audit(
        session, "admin.setting_reverted", detail=key, user_id=user.id, actor=user.name
    )
    return _out(session, resolved)


@router.get("/history", response_model=list[ConfigChangeOut])
def change_history(
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(require_settings),
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[ConfigChangeOut]:
    """Who changed which setting, when, and from what.

    Args:
        session: The request's session.
        _user: The calling administrator.
        limit: How many entries to return, newest first.

    Returns:
        The change log. A secret's values read as ``(secret)``: the record is that it
        changed and who changed it, never what it was.
    """
    rows = session.execute(
        sa.select(models.ConfigChange).order_by(models.ConfigChange.changed_at.desc()).limit(limit)
    ).scalars()
    return [
        ConfigChangeOut(
            id=row.id,
            key=row.key,
            old_value=row.old_value,
            new_value=row.new_value,
            changed_by=row.changed_by,
            changed_at=row.changed_at,
        )
        for row in rows
    ]


@router.post("/test-model", response_model=ProviderTestResult)
def test_model(
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(require_settings),
) -> ProviderTestResult:
    """Make one cheap call with the settings as they currently resolve.

    Answering "did I type the key correctly" before a run fails at stage two is worth
    far more than the call costs.

    Args:
        session: The request's session.
        user: The calling administrator.

    Returns:
        Whether the provider answered, and how long it took.
    """
    settings = resolved_llm_settings(session)
    started = time.monotonic()
    try:
        client = build_client(settings)
        client.complete(
            "You are a connection test. Reply with the single word ok.",
            "Reply with: ok",
            stage="admin.test",
            prompt_version="test-1",
        )
    except Exception as exc:  # noqa: BLE001 - any failure is the answer the admin wants
        detail = f"{type(exc).__name__}: {exc}"
        _LOG.warning("model connection test failed: %s", detail)
        repository.audit(
            session, "admin.model_test", detail="failed", user_id=user.id, actor=user.name
        )
        return ProviderTestResult(
            ok=False, provider=settings.provider, model=settings.model, detail=detail[:500]
        )

    elapsed = int((time.monotonic() - started) * 1000)
    repository.audit(session, "admin.model_test", detail="ok", user_id=user.id, actor=user.name)
    return ProviderTestResult(
        ok=True,
        provider=settings.provider,
        model=settings.model,
        detail="the provider answered",
        latency_ms=elapsed,
    )
