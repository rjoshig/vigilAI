"""Moving a run between the database and the pipeline's in-memory context.

The pipeline knows nothing about the database (``docs/architecture.md``: dependencies
point down). This module is the only place that converts between the two, which keeps
the stage code identical whether it runs from the CLI or from a worker.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
from pathlib import Path
from typing import Any, Final, Iterable, Mapping, Sequence

import sqlalchemy as sa
from sqlalchemy.orm import Session

from vigilai.checks.field_constraints import FieldConstraintSpec
from vigilai.training.lifecycle import RUNNING_STATES
from vigilai.checks.definitions import (
    DEFAULT_CATEGORIES,
    AdminConfig,
    CheckDefinition,
    ComplianceRule,
    ReversePassCategory,
)
from vigilai.checks.named_values import NamedValue
from vigilai.db import models
from vigilai.db.types import utcnow
from vigilai.parsers.masking import DEFAULT_MASKED_COLUMNS
from vigilai.pipeline.context import STAGE_ORDER, RunContext, StageRecord
from vigilai.rules.normalize import AliasTable
from vigilai.rules.schema import ConfigElement, Evidence, Finding, Rule, Trace

__all__ = [
    "load_admin_config",
    "load_aliases",
    "load_masked_columns",
    "save_context",
    "load_findings",
    "fingerprint",
    "file_sha256",
    "capture_config",
    "audit",
]

_LOG: Final = logging.getLogger(__name__)

#: Read in 1 MiB blocks: report workbooks run to tens of megabytes and hashing one
#: should not hold it all in memory.
_HASH_BLOCK: Final[int] = 1024 * 1024


def file_sha256(path: Path) -> str:
    """Hash a file.

    Args:
        path: The file to hash.

    Returns:
        The hex digest.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(_HASH_BLOCK), b""):
            digest.update(block)
    return digest.hexdigest()


def fingerprint(file_hashes: Iterable[str], check_versions: Iterable[str] = ()) -> str:
    """Compute a run's input fingerprint.

    The active check versions are part of it, so adding or editing a check invalidates
    the duplicate shortcut: the same files really do deserve a fresh run once the rules
    applied to them have changed (``docs/design.md`` "LLM cost controls").

    Args:
        file_hashes: The sha256 of every input file.
        check_versions: ``"name:version"`` for each active check.

    Returns:
        The hex digest. Order-independent, so re-uploading the same files in a different
        order is still recognised as a duplicate.
    """
    parts = sorted(file_hashes) + sorted(check_versions)
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------------------
# Admin-maintained data
# --------------------------------------------------------------------------------------


def load_admin_config(session: Session, customer: str = "") -> AdminConfig:
    """Load what the admin-ui contributes to a run.

    Args:
        session: An open session.
        customer: The run's customer, used to scope checks and compliance rules.

    Returns:
        The admin configuration. Falls back to the shipped reverse-pass categories when
        the table is empty, so a fresh install behaves sensibly rather than checking
        nothing.
    """
    checks = tuple(
        CheckDefinition(
            name=row.name,
            version=row.version,
            kind=row.kind,  # type: ignore[arg-type]
            expression=row.expression,
            instruction=row.instruction,
            reasoning=row.reasoning,
            severity=row.severity,  # type: ignore[arg-type]
            scope=row.scope,
            is_active=row.is_active,
        )
        for row in session.execute(
            # A rule runs when it is switched on, or when it is shadowed: shadow
            # findings are recorded and counted and shown to nobody (ADR-021). Both
            # columns are consulted because a row can be written directly, and
            # ``is_active`` is the one every older query already reads.
            sa.select(models.CheckDefinitionRow).where(
                models.CheckDefinitionRow.state != "deleted",
                sa.or_(
                    models.CheckDefinitionRow.is_active,
                    models.CheckDefinitionRow.state == "shadow",
                ),
            )
        ).scalars()
    )

    compliance = tuple(
        ComplianceRule(
            name=row.name,
            json_path_contains=str((row.requirement or {}).get("json_path_contains", "")),
            expected_value=(row.requirement or {}).get("expected_value", True),
            scope=row.scope,
            reasoning=row.reasoning,
            is_active=row.is_active,
        )
        for row in session.execute(
            sa.select(models.ComplianceRuleRow).where(
                models.ComplianceRuleRow.state != "deleted",
                sa.or_(
                    models.ComplianceRuleRow.is_active,
                    models.ComplianceRuleRow.state == "shadow",
                ),
            )
        ).scalars()
    )

    category_rows = list(session.execute(sa.select(models.ReversePassCategoryRow)).scalars())
    categories = (
        tuple(
            ReversePassCategory(name=row.name, kinds=tuple(row.kinds or []), checked=row.checked)
            for row in category_rows
        )
        if category_rows
        else tuple(DEFAULT_CATEGORIES)
    )

    named_values = tuple(
        NamedValue(
            name=row.name,
            report_kind=row.report_type,
            sheet=row.sheet,
            kind=(row.locator or {}).get("kind", "label"),
            cell=(row.locator or {}).get("cell", ""),
            label=(row.locator or {}).get("label", ""),
            label_column=(row.locator or {}).get("label_column", 0),
            value_column=(row.locator or {}).get("value_column", 1),
            description=row.description,
        )
        for row in session.execute(sa.select(models.NamedValueRow)).scalars()
    )

    # A rule in scope for this customer, whatever its origin. Scope is "all", the
    # customer's name, or "programme:CODE"; the narrowest that fits is what a learned
    # rule gets by default (ADR-021).
    constraint_rows = list(
        session.execute(
            sa.select(models.FieldConstraint).where(
                models.FieldConstraint.state.in_(RUNNING_STATES)
            )
        ).scalars()
    )
    field_constraints = tuple(
        FieldConstraintSpec(
            id=row.id,
            field=row.field,
            constraint=row.constraint,
            value=row.value,
            report_kinds=tuple(row.report_kinds or ()),
            severity=row.severity,
            reasoning=row.reasoning,
        )
        for row in constraint_rows
        if row.scope in ("all", customer)
    )

    # Shadow rules run and are counted; their findings are shown to nobody, so the
    # pipeline has to know which they are (ADR-021).
    shadow_refs = {f"field_constraint:{row.id}" for row in constraint_rows if row.state == "shadow"}
    shadow_refs |= {
        f"check:{row.id}"
        for row in session.execute(
            sa.select(models.CheckDefinitionRow).where(models.CheckDefinitionRow.state == "shadow")
        ).scalars()
    }

    return AdminConfig(
        checks=checks,
        compliance_rules=compliance,
        categories=categories,
        named_values=named_values,
        field_constraints=field_constraints,
        shadow_rule_refs=frozenset(shadow_refs),
    )


def active_check_versions(session: Session) -> list[str]:
    """List the active checks as ``name:version``, for the run fingerprint.

    Args:
        session: An open session.

    Returns:
        One entry per active check.
    """
    rows = session.execute(
        sa.select(models.CheckDefinitionRow.name, models.CheckDefinitionRow.version).where(
            models.CheckDefinitionRow.is_active
        )
    ).all()
    return [f"{name}:{version}" for name, version in rows]


def load_aliases(session: Session, customer: str = "") -> AliasTable:
    """Build the attribute alias table.

    Args:
        session: An open session.
        customer: Rows scoped to this customer are included alongside global ones.

    Returns:
        The alias table.
    """
    rows = session.execute(
        sa.select(models.AttributeAlias).where(
            sa.or_(
                models.AttributeAlias.customer_name.is_(None),
                models.AttributeAlias.customer_name == customer,
            )
        )
    ).scalars()
    mapping: dict[str, list[str]] = {}
    for row in rows:
        mapping.setdefault(row.canonical_name, []).append(row.alias)
    return AliasTable.from_mapping(mapping)


def load_masked_columns(session: Session) -> tuple[str, ...]:
    """Load the masked-column patterns.

    Args:
        session: An open session.

    Returns:
        The configured patterns, or the shipped defaults when none are configured. An
        empty table must never mean "mask nothing" (ADR-003).
    """
    patterns = tuple(session.execute(sa.select(models.MaskedColumn.pattern)).scalars())
    return patterns or DEFAULT_MASKED_COLUMNS


# --------------------------------------------------------------------------------------
# Persisting a run
# --------------------------------------------------------------------------------------


def save_context(session: Session, run: models.Run, context: RunContext) -> None:
    """Write a completed pipeline run into the database.

    Rules, elements, traces, and findings are replaced wholesale. A re-check rebuilds
    them from the same inputs, and keeping the old rows would leave the review screen
    showing findings that no longer follow from the current rules.

    Args:
        session: An open session.
        run: The run row.
        context: The finished pipeline context.
    """
    _replace_rules(session, run, context.rules)
    _replace_elements(session, run, context.elements)
    _replace_traces(session, run, context.traces)
    _replace_findings(session, run, context.findings)
    _save_stages(session, run, context)

    run.rules_version = context.rules_version
    run.summary = context.summary
    run.top_issues = list(context.top_issues)


def _replace_rules(session: Session, run: models.Run, rules: Sequence[Rule]) -> None:
    """Replace the run's rules.

    Args:
        session: An open session.
        run: The run row.
        rules: The canonical rules.
    """
    session.execute(sa.delete(models.Rule).where(models.Rule.run_id == run.id))
    for rule in rules:
        session.add(
            models.Rule(
                run_id=run.id,
                rule_id=rule.rule_id,
                version=run.rules_version,
                source=rule.source,
                rule=rule.model_dump(mode="json"),
                confidence=rule.confidence,
            )
        )


def _replace_elements(session: Session, run: models.Run, elements: Sequence[ConfigElement]) -> None:
    """Replace the run's config elements.

    Args:
        session: An open session.
        run: The run row.
        elements: The described elements.
    """
    session.execute(sa.delete(models.ConfigElement).where(models.ConfigElement.run_id == run.id))
    for element in elements:
        session.add(
            models.ConfigElement(
                run_id=run.id,
                element_id=element.element_id,
                json_path=element.json_path,
                req_type=element.rule.req_type if element.rule else "",
                element=element.model_dump(mode="json"),
                is_technical=element.is_technical,
            )
        )


def _replace_traces(session: Session, run: models.Run, traces: Sequence[Trace]) -> None:
    """Replace the run's traces.

    Args:
        session: An open session.
        run: The run row.
        traces: The links.
    """
    session.execute(sa.delete(models.Trace).where(models.Trace.run_id == run.id))
    for trace in traces:
        session.add(
            models.Trace(
                run_id=run.id,
                rule_id=trace.rule_id,
                element_id=trace.element_id,
                verdict=trace.verdict,
                reason=trace.reason,
                confidence=trace.confidence,
                by_code=trace.by_code,
                edited_by=trace.edited_by or "",
            )
        )


def _replace_findings(session: Session, run: models.Run, findings: Sequence[Finding]) -> None:
    """Replace the run's findings, keeping decisions already made.

    A re-check must not silently discard a reviewer's work, so a decision is carried
    across to the rebuilt finding when the same issue is raised again.

    Args:
        session: An open session.
        run: The run row.
        findings: The findings the pipeline produced.
    """
    previous = {
        (row.type, row.title): (row.review_status, row.review_note, row.reviewed_at)
        for row in session.execute(
            sa.select(models.Finding).where(models.Finding.run_id == run.id)
        ).scalars()
    }
    session.execute(sa.delete(models.Finding).where(models.Finding.run_id == run.id))

    for finding in findings:
        status, note, reviewed_at = previous.get(
            (finding.type, finding.title), (finding.review_status, finding.review_note, None)
        )
        session.add(
            models.Finding(
                run_id=run.id,
                finding_id=finding.finding_id,
                type=finding.type,
                severity=finding.severity,
                title=finding.title,
                detail=finding.detail,
                leg=finding.leg,
                # A learned rule sets ``rule_ref`` directly so its findings can be
                # counted against it; everything else refers to the OSL rule it came
                # from, which is what the review screen has always shown.
                rule_ref=finding.rule_ref or finding.rule_id or "",
                element_ref=finding.element_id or "",
                evidence=finding.evidence.model_dump(mode="json"),
                rules_version=finding.rules_version,
                review_status=status,
                review_note=note,
                reviewed_at=reviewed_at,
                shadow=finding.shadow,
                verified=finding.verified,
                verify_agreed=finding.verify_agreed,
            )
        )


def _save_stages(session: Session, run: models.Run, context: RunContext) -> None:
    """Write per-stage status and timing.

    Args:
        session: An open session.
        run: The run row.
        context: The finished pipeline context.
    """
    existing = {
        row.stage: row
        for row in session.execute(
            sa.select(models.RunStage).where(models.RunStage.run_id == run.id)
        ).scalars()
    }
    for name in STAGE_ORDER:
        record = context.stages.get(name, StageRecord(stage=name))
        row = existing.get(name)
        if row is None:
            row = models.RunStage(run_id=run.id, stage=name)
            session.add(row)
        row.status = record.status
        row.duration_ms = record.duration_ms
        row.llm_calls = record.llm_calls
        row.cache_hits = record.cache_hits
        row.tokens = record.tokens
        row.error = record.error


def load_findings(session: Session, run_id: int) -> list[Finding]:
    """Read a run's findings back as domain objects.

    Args:
        session: An open session.
        run_id: The run.

    Returns:
        The findings, ordered worst first so the review screen needs no sorting.
    """
    order = sa.case(
        {"high": 0, "medium": 1, "low": 2, "review": 3},
        value=models.Finding.severity,
        else_=9,
    )
    rows = session.execute(
        sa.select(models.Finding)
        .where(models.Finding.run_id == run_id)
        .order_by(order, models.Finding.id)
    ).scalars()
    return [
        Finding(
            finding_id=row.finding_id,
            type=row.type,  # type: ignore[arg-type]
            severity=row.severity,  # type: ignore[arg-type]
            title=row.title,
            detail=row.detail,
            leg=row.leg,  # type: ignore[arg-type]
            rule_id=row.rule_ref or None,
            element_id=row.element_ref or None,
            evidence=Evidence(**(row.evidence or {})),
            rules_version=row.rules_version,
            review_status=row.review_status,  # type: ignore[arg-type]
            review_note=row.review_note,
            verified=row.verified,
            verify_agreed=row.verify_agreed,
        )
        for row in rows
    ]


def load_rules(session: Session, run_id: int) -> list[Rule]:
    """Read a run's rules back as domain objects.

    Args:
        session: An open session.
        run_id: The run.

    Returns:
        The rules in id order.
    """
    rows = session.execute(
        sa.select(models.Rule).where(models.Rule.run_id == run_id).order_by(models.Rule.id)
    ).scalars()
    return [Rule(**row.rule) for row in rows]


def load_traces(session: Session, run_id: int) -> list[Trace]:
    """Read a run's traces back as domain objects.

    Args:
        session: An open session.
        run_id: The run.

    Returns:
        The traces in id order.
    """
    rows = session.execute(
        sa.select(models.Trace).where(models.Trace.run_id == run_id).order_by(models.Trace.id)
    ).scalars()
    return [
        Trace(
            rule_id=row.rule_id,
            element_id=row.element_id,
            verdict=row.verdict,  # type: ignore[arg-type]
            reason=row.reason,
            confidence=row.confidence,
            by_code=row.by_code,
            edited_by=row.edited_by or None,
        )
        for row in rows
    ]


def load_elements(session: Session, run_id: int) -> list[ConfigElement]:
    """Read a run's config elements back as domain objects.

    Args:
        session: An open session.
        run_id: The run.

    Returns:
        The elements in id order.
    """
    rows = session.execute(
        sa.select(models.ConfigElement)
        .where(models.ConfigElement.run_id == run_id)
        .order_by(models.ConfigElement.id)
    ).scalars()
    return [ConfigElement(**row.element) for row in rows]


def capture_config(
    session: Session,
    configuration_id: str,
    customer: str,
    content: Mapping[str, Any],
    sha: str,
    created_by: int | None = None,
    created_by_name: str = "",
) -> models.Config:
    """Record a config, versioning it only when the content actually changed.

    Args:
        session: An open session.
        configuration_id: The config's own identifier.
        customer: The customer.
        content: The decoded config.
        sha: The file hash.
        created_by: Who submitted the run that carried it (ADR-022).
        created_by_name: Their display name, kept beside the id so the config history
            still reads after an account is renamed.

    Returns:
        The existing row when the content is unchanged, otherwise a new version.
    """
    existing = session.execute(
        sa.select(models.Config)
        .where(models.Config.configuration_id == configuration_id, models.Config.sha256 == sha)
        .limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    highest = session.execute(
        sa.select(sa.func.max(models.Config.version)).where(
            models.Config.configuration_id == configuration_id
        )
    ).scalar_one()
    row = models.Config(
        configuration_id=configuration_id,
        version=(highest or 0) + 1,
        customer_name=customer,
        content=dict(content),
        sha256=sha,
        last_modified=str(content.get("last_modified", "")),
        created_by=created_by_name,
        created_by_user_id=created_by,
    )
    session.add(row)
    session.flush()
    _LOG.info("captured config %s v%d", configuration_id, row.version)
    return row


def audit(
    session: Session,
    action: str,
    run_id: int | None = None,
    detail: str = "",
    user_id: int | None = None,
    actor: str = "",
) -> None:
    """Record who did what.

    Args:
        session: An open session.
        action: The action name, e.g. ``"run.view"``.
        run_id: The run involved.
        detail: Extra context. Ids and counts only, never file content (ADR-003).
        user_id: The account behind the action (ADR-022).
        actor: Their display name, kept beside the id so the entry still reads after
            an account is renamed.
    """
    session.add(
        models.AuditLog(
            action=action,
            run_id=run_id,
            detail=detail[:2000],
            user_id=user_id,
            actor=actor[:200],
        )
    )


def expiry_from(created: dt.datetime, days: int = models.RETENTION_DAYS) -> dt.datetime:
    """Compute a run's expiry.

    Args:
        created: When the run was created.
        days: The retention window.

    Returns:
        When the purge job may delete the run and its files.
    """
    return created + dt.timedelta(days=days)


def purge_expired(session: Session, data_dir: Path) -> int:
    """Delete runs past their expiry, with their files.

    Args:
        session: An open session.
        data_dir: The shared volume.

    Returns:
        How many runs were purged. Aggregated usage statistics survive, because
        ``llm_calls`` rows are kept when their run is gone.
    """
    now = utcnow()
    expired = list(
        session.execute(
            sa.select(models.Run).where(
                models.Run.expires_at.is_not(None), models.Run.expires_at < now
            )
        ).scalars()
    )
    for run in expired:
        for file_row in run.files:
            candidate = data_dir / file_row.storage_key
            if candidate.exists():
                candidate.unlink()
        session.execute(
            sa.update(models.LlmCall).where(models.LlmCall.run_id == run.id).values(run_id=None)
        )
        session.delete(run)
    if expired:
        _LOG.info("purged %d expired run(s)", len(expired))
    return len(expired)
