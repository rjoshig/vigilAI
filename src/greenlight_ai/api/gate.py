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
    "SERIOUS_TYPES",
    "second_approval_needed",
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

#: The findings a programme may treat as needing a second pair of eyes when the first
#: reviewer waves them through: a breach of a rule the programme calls `must`, and a
#: compliance rule the configuration does not implement (ADR-036). Both are things the
#: programme decided in advance are not one person's call.
SERIOUS_TYPES: Final[tuple[str, ...]] = (
    "programme_rule_violation",
    "rule_missing_in_config",
)

#: The decisions that count as waving something through.
_WAVED_THROUGH: Final[tuple[str, ...]] = ("false_positive", "accepted_risk")


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
    #: Serious findings the first reviewer marked OK on a programme that asks for a
    #: second approver, when nobody else has signed off yet (ADR-036).
    awaiting_second_approval: tuple[str, ...] = ()

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
            or self.awaiting_second_approval
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
        if self.awaiting_second_approval:
            parts.append(
                f"{len(self.awaiting_second_approval)} serious finding(s) were marked OK and "
                "this programme asks a second person to approve that"
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


def second_approval_needed(session: Session, run: models.Run, user_auth: bool = False) -> list[str]:
    """Which serious findings a second person has not yet approved (ADR-036).

    A programme decides in advance that some findings are not one reviewer's call: a
    breach of a rule it calls `must`, and a compliance rule the configuration does not
    implement. When the reviewer waves one of those through, someone else signs off
    before the run can be frozen.

    Off unless the programme asks for it, **and inert while login is off**: every action
    then belongs to the same placeholder account, so a second approver would be the same
    person and no run in the programme could ever be frozen. A gate nobody can pass is
    worse than no gate. With login on, the approver must be a different account from the
    reviewer, which is the whole of what this control asserts.

    Args:
        session: An open session.
        run: The run row.
        user_auth: Whether login is on for the user app. The caller passes the
            settings the app is actually running with, rather than this re-reading the
            environment: an app built with login on must not be told it is off.

    Returns:
        The finding ids awaiting a second approval, or an empty list when the
        programme does not ask, when login is off, when nothing serious was waved
        through, or when somebody has already signed.
    """
    if not run.scope:
        return []
    if not user_auth:
        # With login off every action belongs to the same placeholder account, so a
        # "second" approver is the same person. The control cannot be satisfied and
        # would make every affected run unfinalizable, which is worse than not having
        # it: a gate nobody can pass teaches people to look for a way round (ADR-022,
        # ADR-036). The admin console says so beside the switch.
        return []
    programme = session.execute(
        sa.select(models.RunScope).where(models.RunScope.code == run.scope)
    ).scalar_one_or_none()
    if programme is None or not programme.second_approver:
        return []

    waved = list(
        session.execute(
            sa.select(models.Finding)
            .where(
                models.Finding.run_id == run.id,
                models.Finding.type.in_(SERIOUS_TYPES),
                models.Finding.review_status.in_(_WAVED_THROUGH),
                models.Finding.shadow.is_(False),
            )
            .order_by(models.Finding.id)
        ).scalars()
    )
    if not waved:
        return []

    approval = session.execute(
        sa.select(models.SecondApproval).where(models.SecondApproval.run_id == run.id)
    ).scalar_one_or_none()
    if approval is not None:
        reviewers = {f.reviewed_by_user_id for f in waved if f.reviewed_by_user_id is not None}
        # A signature from the person who made the decision is not a second pair of
        # eyes. With login off everyone is the same placeholder, so this is exactly
        # where the control is worth nothing and says so (ADR-022).
        if approval.actor_user_id is not None and approval.actor_user_id in reviewers:
            _LOG.info(
                "run %s: the second approval is by the reviewer, so it does not count",
                run.id,
            )
        else:
            return []

    return [f.finding_id for f in waved]


def gate_state(session: Session, run: models.Run, user_auth: bool = False) -> GateState:
    """Work out whether a run can be frozen.

    Args:
        session: An open session.
        run: The run row.
        user_auth: Whether login is on, which decides whether the four-eyes rule can
            mean anything (ADR-036).

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
        awaiting_second_approval=tuple(second_approval_needed(session, run, user_auth)),
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
        "second_approval": _second_approval_record(session, run),
        "definition_versions": dict(run.definition_versions or {}),
        "notices": list(coverage.notices),
    }


def _second_approval_record(session: Session, run: models.Run) -> dict[str, Any]:
    """Who signed the four-eyes approval, for the attestation (ADR-036).

    Args:
        session: An open session.
        run: The run row.

    Returns:
        The approver, when and what they covered, or an empty mapping when this
        programme does not ask for one.
    """
    approval = session.execute(
        sa.select(models.SecondApproval).where(models.SecondApproval.run_id == run.id)
    ).scalar_one_or_none()
    if approval is None:
        return {}
    return {
        "approved_by": approval.actor,
        "approved_at": approval.created_at.isoformat() if approval.created_at else "",
        "covered": list(approval.covered or []),
        "note": approval.note,
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
