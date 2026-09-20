"""Exploring the samples, from the user app (Phase 6.1e).

An observation is worth far more when it is anchored to the thing the person means —
this cell, this OSL section, this configuration path — than when it is prose alone. Up
to now a reviewer could only anchor from a finding, which limited them to what the tool
had already noticed. The most valuable thing a person knows is usually about something
the tool said nothing about.

So this serves the stored samples read-only: the workbooks cell by cell with the label
beside each one, an OSL by section, a configuration by JSON path. Nothing here changes
anything, and values pass through the same masking as a real upload, because a sample
is a file that may hold customer data (ADR-003).

The preview itself is the admin console's, reused rather than reimplemented: two
renderings of the same workbook that could disagree would be worse than one.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Final

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from greenlight_ai.api import schemas, schemas_admin as wire
from greenlight_ai.api.deps import CurrentUser, current_user, get_data_dir, get_session
from greenlight_ai.api.routers.admin import (
    HTTP_422,
    _config_preview,
    _osl_preview,
    _sheet_preview,
)
from greenlight_ai.db import models, repository
from greenlight_ai.parsers.base import ParseError
from greenlight_ai.parsers.reports.xlsx import parser_for

__all__ = ["router"]

_LOG: Final = logging.getLogger(__name__)

router = APIRouter(tags=["explore"])


@router.get("/samples", response_model=list[schemas.ExploreArtifactOut])
def list_samples(
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(current_user),
) -> list[schemas.ExploreArtifactOut]:
    """The samples a reviewer can look at, grouped by artifact type.

    Args:
        session: The request's session.
        _user: The caller.

    Returns:
        One entry per active artifact type that has samples, with each sample's label,
        filename and scope. Read-only: this is for finding something to point at.
    """
    types = (
        session.execute(
            sa.select(models.ArtifactType)
            .where(models.ArtifactType.is_active.is_(True))
            .order_by(models.ArtifactType.sort_order, models.ArtifactType.key)
        )
        .scalars()
        .all()
    )

    out: list[schemas.ExploreArtifactOut] = []
    for artifact in types:
        samples = [
            schemas.ExploreSampleOut(
                id=sample.id,
                label=sample.label,
                filename=sample.filename,
                sheets=list(sample.sheets or []),
                notes=sample.notes,
                scope_code=sample.scope_code,
            )
            for sample in artifact.samples
        ]
        if samples:
            out.append(
                schemas.ExploreArtifactOut(
                    key=artifact.key,
                    label=artifact.label,
                    kind=artifact.kind,
                    samples=samples,
                )
            )
    return out


@router.get("/samples/{sample_id}/preview", response_model=wire.SamplePreviewOut)
def preview(
    sample_id: int,
    session: Session = Depends(get_session),
    data_dir: Path = Depends(get_data_dir),
    _user: CurrentUser = Depends(current_user),
) -> wire.SamplePreviewOut:
    """Show what one sample contains, so a reviewer can point at part of it.

    Args:
        sample_id: The sample.
        session: The request's session.
        data_dir: The shared volume.
        _user: The caller.

    Returns:
        Each sheet with its populated cells, their addresses, and the label to the left
        of each one. An OSL comes back by section and a configuration by JSON path, so
        every artifact is something a person can point at.

    Raises:
        HTTPException: 404 when the sample or its file is missing, 422 when it cannot
            be parsed.
    """
    sample = session.get(models.ArtifactSample, sample_id)
    if sample is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such sample")

    path = data_dir / sample.storage_path
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "the stored file is missing")

    kind = sample.artifact_type.kind
    try:
        if kind == "osl":
            sheets = _osl_preview(path)
        elif kind == "config":
            sheets = _config_preview(path)
        else:
            masked = repository.load_masked_columns(session)
            sheets = [
                _sheet_preview(sheet, masked)
                for sheet in parser_for(sample.artifact_type.key).parse(path).sheets
            ]
    except ParseError as exc:
        raise HTTPException(HTTP_422, f"the sample could not be read: {exc}") from exc

    return wire.SamplePreviewOut(sample_id=sample.id, filename=sample.filename, sheets=sheets)
