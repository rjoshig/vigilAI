"""The catalog: which artifacts the tool accepts, and which programmes runs belong to.

Both are data an administrator edits, not code (ADR-020). This module holds the shipped
defaults, seeds them into an empty database, and reads them back for the API, the
upload form, and the pipeline.

Two rules shape it:

- **An empty table means "use the defaults", never "accept nothing".** A fresh install
  behaves exactly as it did before any of this was configurable.
- **Guidance is additive.** A type with no ``ai_context`` produces the same prompt the
  pipeline sent before this existed, so configuring nothing changes nothing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final

import sqlalchemy as sa
from sqlalchemy.orm import Session

from vigilai.db import models
from vigilai.parsers.base import CONFIG_KIND, OSL_KIND

__all__ = [
    "ArtifactSpec",
    "ScopeSpec",
    "DEFAULT_ARTIFACTS",
    "DEFAULT_SCOPES",
    "seed_defaults",
    "load_artifacts",
    "load_scopes",
    "active_report_keys",
]

_LOG: Final = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ArtifactSpec:
    """One input the tool accepts.

    Attributes:
        key: Stable identifier; the multipart field name and the storage key.
        label: What a person calls it.
        kind: ``"osl"``, ``"config"``, or ``"report"``.
        description: What it is, in a sentence, for whoever uploads it.
        ai_context: What the model should pay attention to. Empty means no change to
            the prompts.
        is_active: Whether the upload slot appears.
        is_required: Whether a run may be submitted without it.
        is_builtin: Whether it ships with the tool. A built-in may be disabled but not
            deleted, because the fixed report checks look for its key.
        sort_order: Display order on the form.
        has_sample: Whether a sample workbook has been uploaded.
    """

    key: str
    label: str
    kind: str = "report"
    description: str = ""
    ai_context: str = ""
    is_active: bool = True
    is_required: bool = False
    is_builtin: bool = False
    sort_order: int = 100
    has_sample: bool = False


@dataclass(frozen=True, slots=True)
class ScopeSpec:
    """A delivery programme and the instructions standing behind it.

    Attributes:
        code: Short code stored on the run.
        label: What a person calls it.
        description: What the programme is.
        standing_instructions: Compliance expectations true of every run in it.
        is_active: Whether it is offered on the new-run form.
        sort_order: Display order.
    """

    code: str
    label: str
    description: str = ""
    standing_instructions: str = ""
    is_active: bool = True
    sort_order: int = 100


#: What ships. The two inputs that are not reports come first, then the report types
#: the fixed checks in :mod:`vigilai.checks.reports` know how to interpret.
DEFAULT_ARTIFACTS: Final[tuple[ArtifactSpec, ...]] = (
    ArtifactSpec(
        key=OSL_KIND,
        label="OSL — requirement spec",
        kind="osl",
        description="The Order Specification Letter. The source of truth for what the "
        "delivery must contain.",
        is_active=True,
        is_required=True,
        is_builtin=True,
        sort_order=10,
    ),
    ArtifactSpec(
        key=CONFIG_KIND,
        label="ETL configuration",
        kind="config",
        description="The JSON configuration the extract ran with.",
        is_active=True,
        is_required=True,
        is_builtin=True,
        sort_order=20,
    ),
    ArtifactSpec(
        key="dirt",
        label="DIRT",
        description="The data integrity report: per-attribute statistics and a masked "
        "sample tab.",
        is_builtin=True,
        sort_order=30,
    ),
    ArtifactSpec(
        key="state_distribution",
        label="State distribution",
        description="Record counts per state code.",
        is_builtin=True,
        sort_order=40,
    ),
    ArtifactSpec(
        key="field_distribution",
        label="Field distribution",
        description="Per-field value distributions and null rates.",
        is_builtin=True,
        sort_order=50,
    ),
    ArtifactSpec(
        key="counts",
        label="Counts / number flow",
        description="Record counts at each step of the waterfall.",
        is_builtin=True,
        sort_order=60,
    ),
    ArtifactSpec(
        key="billing",
        label="Billing",
        description="Billed record counts.",
        is_builtin=True,
        sort_order=70,
    ),
    ArtifactSpec(
        key="score_distribution",
        label="Score distribution",
        description="Record counts per score band.",
        is_builtin=True,
        is_active=False,
        sort_order=80,
    ),
    ArtifactSpec(
        key="cross_tab",
        label="Cross tab",
        description="A two-dimensional breakdown, such as state by score band.",
        is_builtin=True,
        is_active=False,
        sort_order=90,
    ),
)

#: The programmes most customers fall into, plus a catch-all. The standing
#: instructions ship empty on purpose: they are the customer's compliance regime, and
#: inventing one would be worse than leaving the model to read the OSL alone.
DEFAULT_SCOPES: Final[tuple[ScopeSpec, ...]] = (
    ScopeSpec(
        code="AM",
        label="Account Monitoring",
        description="Ongoing review of an existing portfolio.",
        sort_order=10,
    ),
    ScopeSpec(
        code="AS",
        label="Account Solicitation",
        description="Prescreen and invitation-to-apply campaigns.",
        sort_order=20,
    ),
    ScopeSpec(
        code="ARCHIVE",
        label="Archives",
        description="Historical or archival extracts.",
        sort_order=30,
    ),
    ScopeSpec(
        code="OTHER",
        label="Other",
        description="Anything that does not fall into the three programmes above.",
        sort_order=40,
    ),
)


def seed_defaults(session: Session) -> int:
    """Load the shipped artifact types and scopes into an empty database.

    Idempotent: a key or code that already exists is left alone, so an upgrade adds
    what is new without overwriting anything an administrator changed.

    Args:
        session: An open session.

    Returns:
        How many rows were created.
    """
    created = 0

    existing_keys = set(session.execute(sa.select(models.ArtifactType.key)).scalars())
    for spec in DEFAULT_ARTIFACTS:
        if spec.key in existing_keys:
            continue
        session.add(
            models.ArtifactType(
                key=spec.key,
                label=spec.label,
                kind=spec.kind,
                description=spec.description,
                ai_context=spec.ai_context,
                is_active=spec.is_active,
                is_required=spec.is_required,
                is_builtin=True,
                sort_order=spec.sort_order,
            )
        )
        created += 1

    existing_codes = set(session.execute(sa.select(models.RunScope.code)).scalars())
    for scope in DEFAULT_SCOPES:
        if scope.code in existing_codes:
            continue
        session.add(
            models.RunScope(
                code=scope.code,
                label=scope.label,
                description=scope.description,
                standing_instructions=scope.standing_instructions,
                is_active=scope.is_active,
                sort_order=scope.sort_order,
            )
        )
        created += 1

    if created:
        session.flush()
        _LOG.info("seeded %d catalog row(s)", created)
    return created


def load_artifacts(session: Session, active_only: bool = False) -> list[ArtifactSpec]:
    """Read the artifact types.

    Args:
        session: An open session.
        active_only: Only those whose upload slot should appear.

    Returns:
        The types in display order. Falls back to the shipped defaults when the table
        is empty, so a fresh install accepts the same inputs it always did.
    """
    statement = sa.select(models.ArtifactType).order_by(
        models.ArtifactType.sort_order, models.ArtifactType.key
    )
    if active_only:
        statement = statement.where(models.ArtifactType.is_active)

    rows = list(session.execute(statement).scalars())
    if not rows:
        defaults = list(DEFAULT_ARTIFACTS)
        return [spec for spec in defaults if spec.is_active] if active_only else defaults

    return [
        ArtifactSpec(
            key=row.key,
            label=row.label,
            kind=row.kind,
            description=row.description,
            ai_context=row.ai_context,
            is_active=row.is_active,
            is_required=row.is_required,
            is_builtin=row.is_builtin,
            sort_order=row.sort_order,
            has_sample=bool(row.storage_path),
        )
        for row in rows
    ]


def load_scopes(session: Session, active_only: bool = False) -> list[ScopeSpec]:
    """Read the delivery programmes.

    Args:
        session: An open session.
        active_only: Only those offered on the new-run form.

    Returns:
        The scopes in display order, falling back to the shipped defaults.
    """
    statement = sa.select(models.RunScope).order_by(
        models.RunScope.sort_order, models.RunScope.code
    )
    if active_only:
        statement = statement.where(models.RunScope.is_active)

    rows = list(session.execute(statement).scalars())
    if not rows:
        defaults = list(DEFAULT_SCOPES)
        return [s for s in defaults if s.is_active] if active_only else defaults

    return [
        ScopeSpec(
            code=row.code,
            label=row.label,
            description=row.description,
            standing_instructions=row.standing_instructions,
            is_active=row.is_active,
            sort_order=row.sort_order,
        )
        for row in rows
    ]


def scope_for(session: Session, code: str) -> ScopeSpec | None:
    """Look up one programme.

    Args:
        session: An open session.
        code: The scope code stored on a run.

    Returns:
        The scope, or ``None`` when the run names none or names one that has since
        been deleted. A missing scope is not an error: it means no extra context.
    """
    if not code:
        return None
    return next((s for s in load_scopes(session) if s.code == code), None)


def active_report_keys(session: Session) -> list[str]:
    """The report types a new run may upload.

    Args:
        session: An open session.

    Returns:
        The keys, in display order.
    """
    return [a.key for a in load_artifacts(session, active_only=True) if a.kind == "report"]
