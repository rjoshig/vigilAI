"""Which samples a scope reads: the programme's own, else the global ones."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Session

from greenlight_ai.db import models

__all__ = ["samples_in_scope"]


def samples_in_scope(session: Session, scope_code: str) -> dict[str, list[models.ArtifactSample]]:
    """The samples the interview and the compiler read for a scope.

    Args:
        session: An open session.
        scope_code: ``""`` for global, else a programme code.

    Returns:
        Artifact key to samples. For each key the programme's own samples win when it
        has any; otherwise the global samples. Types with no sample are absent.
    """
    scope = scope_code.strip().upper()
    rows = session.execute(
        sa.select(models.ArtifactSample)
        .join(models.ArtifactType)
        .where(models.ArtifactSample.scope_code.in_([scope, ""] if scope else [""]))
        .order_by(models.ArtifactSample.id)
    ).scalars()
    by_key: dict[str, dict[str, list[models.ArtifactSample]]] = {}
    for sample in rows:
        by_key.setdefault(sample.artifact_type.key, {}).setdefault(
            sample.scope_code or "", []
        ).append(sample)
    chosen: dict[str, list[models.ArtifactSample]] = {}
    for key, per_scope in by_key.items():
        chosen[key] = per_scope.get(scope) or per_scope.get("") or []
    return {key: samples for key, samples in chosen.items() if samples}
