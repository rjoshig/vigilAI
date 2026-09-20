"""The finalize gate, and the attestation the person confirms (Phase 6.11d, ADR-035).

Until this phase the gate asked one question: has every high-severity finding been
decided (ADR-015)? That reads the absence of a finding as a pass. It says nothing about
a ``review``-severity finding, which is the one the model was unsure about; nothing
about a requirement no report could evidence; nothing about a check that could not be
evaluated; and nothing about a verification that never ran.

The gate now fails closed. Everything it asks for is either a decision a person made or
an acknowledgement that they saw a gap. Nothing here decides anything on their behalf,
and nothing here is advisory: a blocker is a blocker, refused in the API and not only
greyed out in the UI.

The attestation is the same information rendered once, for the confirmation dialog and
for the frozen report, because a report that is evidence of a review should say what
the reviewer was shown.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final, Sequence

import sqlalchemy as sa
from sqlalchemy.orm import Session

from greenlight_ai.db import models
from greenlight_ai.pipeline import coverage as coverage_module
from greenlight_ai.pipeline.coverage import Coverage

__all__ = [
    "GateState",
    "acknowledged_targets",
    "attestation",
    "gate_state",
    "run_coverage",
    "summarise",
]

_LOG: Final = logging.getLogger(__name__)

#: Severities whose findings must be decided before a run can be frozen. ``review`` is
#: here because it means the checks produced something nobody could settle: leaving it
#: undecided is exactly the slip this phase exists to stop.
DECISION_REQUIRED: Final[tuple[str, ...]] = ("high", "review")

#: The finding type that says a check was defined and could not be run. It is never a
#: pass, so it needs an acknowledgement even though it is not a disagreement.
_UNEVALUATED_TYPE: Final[str] = "could_not_evaluate"


@dataclass(frozen=True, slots=True)
class GateState:
    """Whether a run can be frozen, and what stands in the way.

    Attributes:
        undecided_findings: Ids of findings at a decision-required severity that have
            no decision.
        unacknowledged_requirements: Requirement ids no report evidenced that nobody
            has acknowledged.
        unacknowledged_findings: Ids of could-not-evaluate findings nobody has
            acknowledged.
    """

    undecided_findings: tuple[str, ...] = ()
    unacknowledged_requirements: tuple[str, ...] = ()
    unacknowledged_findings: tuple[str, ...] = ()

    @property
    def can_finalize(self) -> bool:
        """Whether the gate is satisfied.

        Returns:
            ``True`` when nothing is outstanding.
        """
        return not (
            self.undecided_findings
            or self.unacknowledged_requirements
            or self.unacknowledged_findings
        )

    @property
    def reason(self) -> str:
        """Why the run cannot be frozen, for the API's refusal and the UI's hint.

        Returns:
            One sentence naming every outstanding class, or ``""`` when the gate is
            satisfied. It names counts rather than listing ids, because the screen
            beside it lists them.
        """
        parts: list[str] = []
        if self.undecided_findings:
            parts.append(f"{len(self.undecided_findings)} finding(s) still need a decision")
        if self.unacknowledged_requirements:
            parts.append(
                f"{len(self.unacknowledged_requirements)} requirement(s) that no report "
                "evidenced have not been acknowledged"
            )
        if self.unacknowledged_findings:
            parts.append(
                f"{len(self.unacknowledged_findings)} check(s) that could not be evaluated "
                "have not been acknowledged"
            )
        if not parts:
            return ""
        return "; ".join(parts) + "."


def run_coverage(run: models.Run) -> Coverage:
    """Read back the coverage stored on a run.

    Args:
        run: The run row.

    Returns:
        The coverage, empty for a run processed before this phase existed, which reads
        as "nothing to acknowledge" and leaves such a run's gate exactly as it was.
    """
    return coverage_module.from_rows(
        list(run.coverage or []),
        list(run.report_coverage or []),
        [str(notice) for notice in (run.notices or [])],
    )


def acknowledged_targets(session: Session, run_id: int) -> set[str]:
    """Which coverage gaps someone has already acknowledged.

    Args:
        session: An open session.
        run_id: The run.

    Returns:
        The acknowledged requirement ids and finding ids, in one set: a target id is
        unique within a run whichever kind it is.
    """
    rows = session.execute(
        sa.select(models.CoverageAcknowledgement.target).where(
            models.CoverageAcknowledgement.run_id == run_id
        )
    ).scalars()
    return set(rows)


def _unevaluated_finding_ids(session: Session, run_id: int) -> list[str]:
    """The could-not-evaluate findings a person must see before freezing.

    Args:
        session: An open session.
        run_id: The run.

    Returns:
        Their ids. Shadow findings are excluded: they are shown to nobody, so nobody
        can acknowledge them (ADR-021).
    """
    rows = session.execute(
        sa.select(models.Finding.finding_id)
        .where(
            models.Finding.run_id == run_id,
            models.Finding.type == _UNEVALUATED_TYPE,
            models.Finding.shadow.is_(False),
        )
        .order_by(models.Finding.id)
    ).scalars()
    return list(rows)


def gate_state(session: Session, run: models.Run) -> GateState:
    """Work out whether a run can be frozen.

    Args:
        session: An open session.
        run: The run row.

    Returns:
        What is outstanding.
    """
    undecided = session.execute(
        sa.select(models.Finding.finding_id)
        .where(
            models.Finding.run_id == run.id,
            models.Finding.severity.in_(DECISION_REQUIRED),
            models.Finding.review_status == "undecided",
            models.Finding.shadow.is_(False),
        )
        .order_by(models.Finding.id)
    ).scalars()

    acknowledged = acknowledged_targets(session, run.id)
    coverage = run_coverage(run)
    return GateState(
        undecided_findings=tuple(undecided),
        unacknowledged_requirements=tuple(
            entry.rule_id for entry in coverage.unresolved if entry.rule_id not in acknowledged
        ),
        unacknowledged_findings=tuple(
            finding_id
            for finding_id in _unevaluated_finding_ids(session, run.id)
            if finding_id not in acknowledged
        ),
    )


def attestation(session: Session, run: models.Run) -> dict[str, Any]:
    """What the person is confirming when they freeze the report.

    Args:
        session: An open session.
        run: The run row.

    Returns:
        A plain dictionary: the coverage counts, the requirements nothing evidenced,
        the checks that could not be evaluated, how many rules were in shadow, which
        definition versions applied, and the run's notices. It is stored on the final
        report and rendered in it.
    """
    coverage = run_coverage(run)
    counts = coverage.counts
    unevaluated = _unevaluated_finding_ids(session, run.id)
    shadow = session.execute(
        sa.select(sa.func.count())
        .select_from(models.Finding)
        .where(models.Finding.run_id == run.id, models.Finding.shadow.is_(True))
    ).scalar_one()

    return {
        "coverage": counts,
        "requirements_total": sum(counts.values()),
        "unevidenced": [
            {"rule_id": entry.rule_id, "state": entry.state, "osl_ref": entry.osl_ref}
            for entry in coverage.unresolved
        ],
        "unevaluated_checks": unevaluated,
        "reports_without_checks": list(coverage.unchecked_reports),
        "shadow_findings": int(shadow),
        "definition_versions": dict(run.definition_versions or {}),
        "notices": list(coverage.notices),
    }


def summarise(counts: dict[str, int], unevaluated: Sequence[str]) -> str:
    """One line of attestation, for a log or a narrow screen.

    Args:
        counts: The coverage counts.
        unevaluated: The checks that could not be evaluated.

    Returns:
        A sentence.
    """
    total = sum(counts.values())
    return (
        f"{counts.get('checked', 0)} of {total} requirements checked, "
        f"{counts.get('traced_unchecked', 0)} traced but unchecked, "
        f"{counts.get('untraced', 0)} untraced, {counts.get('manual', 0)} manual, "
        f"{len(unevaluated)} check(s) could not be evaluated."
    )
