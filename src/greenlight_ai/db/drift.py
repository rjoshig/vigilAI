"""Delivery drift: what changed since the previous run of the same configuration.

A reviewer's first question on a repeat delivery is "what is different from last
time". This answers it from what is already stored: the previous **finalized** run of
the same configuration id for the same customer, its findings with their decisions,
its extracted requirements, and the configuration it carried. Everything here is a
comparison in code; no model is involved (ADR-001, ADR-030).

Four comparisons:

- **Findings** new since last time and findings that went away, matched on their
  type, leg, and title, which code generates and therefore keeps stable.
- **Not OK items carried over**: findings the previous reviewer marked Not OK that
  are back in this run, which is the case worth a warning.
- **Requirements** whose extracted value changed, matched on type and OSL reference.
- **The configuration**, as a diff by JSON path.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Final, Mapping, Sequence

import sqlalchemy as sa
from sqlalchemy.orm import Session

from greenlight_ai.db import models
from greenlight_ai.rules.schema import Rule

__all__ = [
    "diff_coverage",
    "ConfigChange",
    "Drift",
    "FindingRef",
    "RequirementChange",
    "compute_drift",
    "diff_config",
    "diff_findings",
    "diff_requirements",
    "flatten",
    "previous_finalized_run",
]

_LOG: Final = logging.getLogger(__name__)

#: How long a value is allowed to be on the drift panel; values are thresholds and
#: names, never rows, but a config list can be long (ADR-003).
_VALUE_CHARS: Final[int] = 120


@dataclass(frozen=True, slots=True)
class FindingRef:
    """One finding, as drift refers to it."""

    finding_id: str
    type: str
    severity: str
    title: str
    review_status: str = "undecided"


@dataclass(frozen=True, slots=True)
class RequirementChange:
    """One requirement whose extracted value differs, or that appeared or vanished."""

    rule_id: str
    req_type: str
    source_ref: str
    change: str  # added · removed · changed
    before: str = ""
    after: str = ""


@dataclass(frozen=True, slots=True)
class ConfigChange:
    """One JSON path whose value differs between the two configurations."""

    path: str
    change: str  # added · removed · changed
    before: str = ""
    after: str = ""


@dataclass(frozen=True, slots=True)
class Drift:
    """What changed since the previous finalized run of the same configuration."""

    previous_run_id: int | None = None
    previous_finished_at: str = ""
    previous_verdict: str = ""
    #: Why there is no comparison, when there is none.
    reason: str = ""
    new: tuple[FindingRef, ...] = ()
    resolved: tuple[FindingRef, ...] = ()
    carried_not_ok: tuple[FindingRef, ...] = ()
    requirements: tuple[RequirementChange, ...] = ()
    config: tuple[ConfigChange, ...] = ()
    #: Requirements a report check evidenced last time and does not this time
    #: (Phase 6.11c). Coverage going backwards is not a finding on its own, and it
    #: is exactly the thing nobody notices: the findings list looks the same.
    newly_unchecked: tuple[str, ...] = ()
    previous_config_version: int | None = None
    config_version: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def has_previous(self) -> bool:
        """Whether there was a run to compare with."""
        return self.previous_run_id is not None


# --- the previous run --------------------------------------------------------------------


def diff_coverage(run: models.Run, previous: models.Run) -> tuple[str, ...]:
    """Requirements a report evidenced last time and evidences no longer.

    Matched on the OSL reference rather than the requirement id, which is renumbered
    on every extraction. Pure code, like the rest of drift (ADR-030).

    Args:
        run: This run.
        previous: The previous finalized run of the same configuration.

    Returns:
        The OSL references that went from checked to unchecked, sorted. Empty when
        either run predates coverage, because "unknown" is not "worse".
    """

    def by_ref(rows: object) -> dict[str, str]:
        out: dict[str, str] = {}
        if not isinstance(rows, list):
            return out
        for row in rows:
            if not isinstance(row, dict):
                continue
            ref = str(row.get("osl_ref") or row.get("rule_id") or "")
            if ref:
                out[ref] = str(row.get("state", ""))
        return out

    before = by_ref(previous.coverage)
    after = by_ref(run.coverage)
    if not before or not after:
        return ()
    return tuple(
        sorted(
            ref
            for ref, state in after.items()
            if state != "checked" and before.get(ref) == "checked"
        )
    )


def previous_finalized_run(session: Session, run: models.Run) -> models.Run | None:
    """Find the run to compare with.

    Args:
        session: An open session.
        run: The current run.

    Returns:
        The latest finalized run of the same configuration id and customer that was
        submitted before this one, or ``None``. A run with no configuration id has
        nothing to be compared with, because the id is what says "the same order
        again".
    """
    if not run.configuration_id.strip():
        return None
    return session.execute(
        sa.select(models.Run)
        .where(
            models.Run.id != run.id,
            models.Run.configuration_id == run.configuration_id,
            models.Run.customer_name == run.customer_name,
            models.Run.status == "finalized",
            models.Run.created_at < run.created_at,
        )
        .order_by(models.Run.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


# --- comparisons -------------------------------------------------------------------------


def _key(finding: models.Finding) -> tuple[str, str, str]:
    return (finding.type, finding.leg, finding.title.strip())


def _ref(finding: models.Finding) -> FindingRef:
    return FindingRef(
        finding_id=finding.finding_id,
        type=finding.type,
        severity=finding.severity,
        title=finding.title,
        review_status=finding.review_status,
    )


def diff_findings(
    current: Sequence[models.Finding], previous: Sequence[models.Finding]
) -> tuple[tuple[FindingRef, ...], tuple[FindingRef, ...], tuple[FindingRef, ...]]:
    """Compare two runs' findings.

    Args:
        current: This run's findings.
        previous: The previous run's findings, with their decisions.

    Returns:
        New findings, resolved findings, and the previous run's Not OK findings that
        are back again. Shadow findings are left out on both sides: they were shown
        to nobody (ADR-021).
    """
    now = {_key(f): f for f in current if not f.shadow}
    then = {_key(f): f for f in previous if not f.shadow}
    new = tuple(_ref(f) for key, f in now.items() if key not in then)
    resolved = tuple(_ref(f) for key, f in then.items() if key not in now)
    carried = tuple(
        _ref(now[key]) for key, f in then.items() if key in now and f.review_status == "confirmed"
    )
    return new, resolved, carried


def describe_value(rule: Rule) -> str:
    """What a requirement asks for, in one short string carrying no sample data.

    Args:
        rule: The requirement.

    Returns:
        Its values, steps, quantity, or conditions.
    """
    if rule.values:
        return ", ".join(sorted(rule.values))
    if rule.steps:
        return " → ".join(rule.steps)
    if rule.quantity is not None:
        return f"{rule.quantity:g}"
    if rule.conditions:
        return " AND ".join(f"{c.field_name} {c.operator} {c.value}" for c in rule.conditions)
    return ""


def diff_requirements(
    current: Sequence[Rule], previous: Sequence[Rule]
) -> tuple[RequirementChange, ...]:
    """Compare two runs' extracted requirements.

    Matched on type and OSL reference rather than on ``R-nnn``, which is renumbered
    on every extraction.

    Args:
        current: This run's requirements.
        previous: The previous run's requirements.

    Returns:
        The requirements that appeared, vanished, or changed value.
    """

    def index(rules: Sequence[Rule]) -> dict[tuple[str, str], Rule]:
        return {(r.req_type, r.source_ref.strip()): r for r in rules}

    now = index(current)
    then = index(previous)
    changes: list[RequirementChange] = []
    for key, rule in now.items():
        before = then.get(key)
        if before is None:
            changes.append(
                RequirementChange(
                    rule.rule_id, rule.req_type, rule.source_ref, "added", "", describe_value(rule)
                )
            )
        elif describe_value(before) != describe_value(rule):
            changes.append(
                RequirementChange(
                    rule.rule_id,
                    rule.req_type,
                    rule.source_ref,
                    "changed",
                    describe_value(before),
                    describe_value(rule),
                )
            )
    for key, rule in then.items():
        if key not in now:
            changes.append(
                RequirementChange(
                    rule.rule_id,
                    rule.req_type,
                    rule.source_ref,
                    "removed",
                    describe_value(rule),
                    "",
                )
            )
    return tuple(changes)


def flatten(value: object, prefix: str = "") -> dict[str, object]:
    """Flatten decoded JSON into ``path -> scalar``.

    Args:
        value: The decoded document.
        prefix: The path so far.

    Returns:
        Every leaf keyed by a dotted path with ``[n]`` list indexes.
    """
    if isinstance(value, Mapping):
        out: dict[str, object] = {}
        for key, inner in value.items():
            out.update(flatten(inner, f"{prefix}.{key}" if prefix else str(key)))
        return out
    if isinstance(value, list):
        out = {}
        for index, inner in enumerate(value):
            out.update(flatten(inner, f"{prefix}[{index}]"))
        return out
    return {prefix: value}


def _shown(value: object) -> str:
    text = "null" if value is None else str(value)
    return text if len(text) <= _VALUE_CHARS else text[: _VALUE_CHARS - 1] + "…"


def diff_config(
    current: Mapping[str, Any] | None, previous: Mapping[str, Any] | None
) -> tuple[ConfigChange, ...]:
    """Diff two configurations by JSON path.

    Args:
        current: This run's decoded configuration.
        previous: The previous run's.

    Returns:
        Every path that was added, removed, or changed, in path order. The
        ``last_modified`` stamp is left out: it changes on every save and says
        nothing about the delivery.
    """
    if current is None or previous is None:
        return ()
    now = flatten(current)
    then = flatten(previous)
    changes: list[ConfigChange] = []
    for path in sorted(set(now) | set(then)):
        if path == "last_modified":
            continue
        if path not in then:
            changes.append(ConfigChange(path, "added", "", _shown(now[path])))
        elif path not in now:
            changes.append(ConfigChange(path, "removed", _shown(then[path]), ""))
        elif now[path] != then[path]:
            changes.append(ConfigChange(path, "changed", _shown(then[path]), _shown(now[path])))
    return tuple(changes)


# --- putting it together ---------------------------------------------------------------


def _config_for(session: Session, run: models.Run) -> models.Config | None:
    """The captured configuration a run carried, by the file's hash."""
    sha = next((f.sha256 for f in run.files if f.kind == "config"), "")
    if not sha:
        return None
    return session.execute(
        sa.select(models.Config)
        .where(models.Config.configuration_id == run.configuration_id, models.Config.sha256 == sha)
        .limit(1)
    ).scalar_one_or_none()


def _findings(session: Session, run_id: int) -> list[models.Finding]:
    return list(
        session.execute(
            sa.select(models.Finding)
            .where(models.Finding.run_id == run_id)
            .order_by(models.Finding.id)
        ).scalars()
    )


def _rules(session: Session, run_id: int) -> list[Rule]:
    rows = session.execute(
        sa.select(models.Rule).where(models.Rule.run_id == run_id).order_by(models.Rule.id)
    ).scalars()
    return [Rule(**row.rule) for row in rows]


def compute_drift(session: Session, run: models.Run) -> Drift:
    """Compare a run with the previous finalized run of its configuration.

    Args:
        session: An open session.
        run: The current run.

    Returns:
        The drift, or a ``Drift`` with a ``reason`` when there is nothing to compare
        with.
    """
    if not run.configuration_id.strip():
        return Drift(
            reason="This run has no configuration id, so there is no previous run to compare with."
        )
    previous = previous_finalized_run(session, run)
    if previous is None:
        return Drift(
            reason=(
                f"No earlier finalized run of configuration {run.configuration_id} for "
                f"{run.customer_name}."
            )
        )

    new, resolved, carried = diff_findings(
        _findings(session, run.id), _findings(session, previous.id)
    )
    requirements = diff_requirements(_rules(session, run.id), _rules(session, previous.id))
    current_config = _config_for(session, run)
    previous_config = _config_for(session, previous)
    config = diff_config(
        current_config.content if current_config else None,
        previous_config.content if previous_config else None,
    )
    newly_unchecked = diff_coverage(run, previous)
    verdict = ""
    report = session.execute(
        sa.select(models.FinalReport.verdict)
        .where(models.FinalReport.run_id == previous.id)
        .limit(1)
    ).scalar_one_or_none()
    if report:
        verdict = str(report)
    _LOG.info(
        "run %d drift against run %d: %d new, %d resolved, %d carried, "
        "%d requirement(s), %d config path(s)",
        run.id,
        previous.id,
        len(new),
        len(resolved),
        len(carried),
        len(requirements),
        len(config),
    )
    return Drift(
        previous_run_id=previous.id,
        previous_finished_at=previous.finished_at.isoformat() if previous.finished_at else "",
        previous_verdict=verdict,
        new=new,
        resolved=resolved,
        carried_not_ok=carried,
        requirements=requirements,
        config=config,
        previous_config_version=previous_config.version if previous_config else None,
        config_version=current_config.version if current_config else None,
        newly_unchecked=newly_unchecked,
    )
