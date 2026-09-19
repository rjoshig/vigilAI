"""Config history: browse captured configs and copy one into a new run."""

from __future__ import annotations

from typing import Final

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from vigilai.api import schemas
from vigilai.api.deps import CurrentUser, current_user, get_session
from vigilai.db import models

__all__ = ["router"]

router: Final = APIRouter(prefix="/configs", tags=["configs"])


def _run_counts(session: Session, configuration_ids: list[str]) -> dict[str, int]:
    """Count runs per configuration id.

    Args:
        session: An open session.
        configuration_ids: The ids to count.

    Returns:
        Configuration id to run count.
    """
    if not configuration_ids:
        return {}
    rows = session.execute(
        sa.select(models.Run.configuration_id, sa.func.count())
        .where(models.Run.configuration_id.in_(configuration_ids))
        .group_by(models.Run.configuration_id)
    ).all()
    return {str(key): int(count) for key, count in rows}


@router.get("", response_model=list[schemas.ConfigSummary])
def list_configs(
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(current_user),
    customer: str | None = Query(default=None),
    latest_only: bool = Query(default=False),
) -> list[schemas.ConfigSummary]:
    """List captured configs, newest first.

    Configs are kept separately from runs so they can outlive the retention window
    (``docs/design.md`` "Data model").

    Args:
        session: The request's session.
        _user: The caller.
        customer: Filter by customer.
        latest_only: Only the highest version of each configuration id.

    Returns:
        The configs.
    """
    statement = sa.select(models.Config).order_by(
        models.Config.configuration_id, models.Config.version.desc()
    )
    if customer:
        statement = statement.where(models.Config.customer_name == customer)

    rows = list(session.execute(statement).scalars())
    if latest_only:
        seen: set[str] = set()
        latest = []
        for row in rows:
            if row.configuration_id not in seen:
                seen.add(row.configuration_id)
                latest.append(row)
        rows = latest

    counts = _run_counts(session, [r.configuration_id for r in rows])
    return [
        schemas.ConfigSummary(
            id=row.id,
            configuration_id=row.configuration_id,
            version=row.version,
            customer_name=row.customer_name,
            sha256=row.sha256,
            last_modified=row.last_modified,
            created_at=row.created_at,
            run_count=counts.get(row.configuration_id, 0),
            created_by=row.created_by,
        )
        for row in rows
    ]


@router.get("/{config_id}", response_model=schemas.ConfigDetail)
def get_config(
    config_id: int,
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(current_user),
) -> schemas.ConfigDetail:
    """Read one captured config, with its content.

    Args:
        config_id: The config row id.
        session: The request's session.
        _user: The caller.

    Returns:
        The config.

    Raises:
        HTTPException: 404 when it does not exist.
    """
    row = session.get(models.Config, config_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"config {config_id} not found")
    counts = _run_counts(session, [row.configuration_id])
    return schemas.ConfigDetail(
        id=row.id,
        configuration_id=row.configuration_id,
        version=row.version,
        customer_name=row.customer_name,
        sha256=row.sha256,
        last_modified=row.last_modified,
        created_at=row.created_at,
        run_count=counts.get(row.configuration_id, 0),
        content=dict(row.content or {}),
    )
