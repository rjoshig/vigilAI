"""What the run actually checked, and what it did not (Phase 6.11c).

The tool's findings say what disagreed. On their own they say nothing about what was
never compared, and a reviewer reading a short findings list cannot tell a clean
delivery from an unexamined one. Coverage is the other half of that sentence: for every
requirement, whether a report check reached it, and for every report, how many checks
touched it.

Pure code. Stage 7 records what it evaluated as it goes, and this module reads those
records; nothing here re-runs a check, and no model is asked (ADR-001). The
:mod:`greenlight_ai.pipeline.s7_reports` stage is the only writer of the inputs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final, Literal, Sequence

from greenlight_ai.pipeline.context import CoverageRecord, RunContext
from greenlight_ai.rules.schema import Rule, Trace

__all__ = [
    "Coverage",
    "RequirementCoverage",
    "ReportCoverage",
    "RequirementState",
    "UNRESOLVED_STATES",
    "compute",
]

_LOG: Final = logging.getLogger(__name__)

RequirementState = Literal["checked", "traced_unchecked", "untraced", "manual"]

#: The states that leave a requirement unevidenced, and so need a person's
#: acknowledgement before the run can be finalized (Phase 6.11d).
UNRESOLVED_STATES: Final[frozenset[str]] = frozenset({"traced_unchecked", "manual"})

#: A free-text requirement can only be verified by reading it. The design doc marks
#: ``other`` "manual verify" and this is where that becomes visible rather than
#: implied (``docs/design.md`` "Canonical rule schema").
_MANUAL_REQ_TYPE: Final[str] = "other"


@dataclass(frozen=True, slots=True)
class RequirementCoverage:
    """How far one requirement got.

    Attributes:
        rule_id: The requirement's id within the run.
        req_type: Its family, which decides what a report check could have done.
        state: What happened to it.
        osl_ref: Where it came from, so a reviewer can go and read it.
        summary: A short rendering of the requirement, for the panel.
        reason: Why it has this state, in a sentence.
    """

    rule_id: str
    req_type: str
    state: RequirementState
    osl_ref: str = ""
    summary: str = ""
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ReportCoverage:
    """How many checks touched one uploaded report.

    Attributes:
        kind: The report kind, as the catalog names it.
        checks_applied: How many checks produced a verdict against it. Zero means the
            file was parsed and then nothing asked it anything, which is the silent
            case this exists to make loud.
    """

    kind: str
    checks_applied: int = 0


@dataclass(frozen=True, slots=True)
class Coverage:
    """The whole picture for one run.

    Attributes:
        requirements: One entry per requirement, in the order they were extracted.
        reports: One entry per uploaded report kind.
        notices: Run-level things the reviewer should know that are not findings: a
            verification that did not run, a stage that was skipped. A notice is
            never silent, and it reaches the attestation.
    """

    requirements: tuple[RequirementCoverage, ...] = ()
    reports: tuple[ReportCoverage, ...] = ()
    notices: tuple[str, ...] = ()

    @property
    def counts(self) -> dict[str, int]:
        """How many requirements are in each state.

        Returns:
            Every state as a key, zero included, so a caller never has to guard a
            missing one.
        """
        totals = {"checked": 0, "traced_unchecked": 0, "untraced": 0, "manual": 0}
        for entry in self.requirements:
            totals[entry.state] += 1
        return totals

    @property
    def unresolved(self) -> tuple[RequirementCoverage, ...]:
        """The requirements no report evidenced.

        Returns:
            The ``traced_unchecked`` and ``manual`` entries, which are the ones the
            finalize gate asks a person to acknowledge. An ``untraced`` requirement is
            already a high-severity finding of its own from stage 5, so asking for a
            second acknowledgement of the same fact would be noise.
        """
        return tuple(e for e in self.requirements if e.state in UNRESOLVED_STATES)

    @property
    def unchecked_reports(self) -> tuple[str, ...]:
        """Reports that arrived and were asked nothing.

        Returns:
            The kinds with no check applied.
        """
        return tuple(r.kind for r in self.reports if r.checks_applied == 0)


def _is_traced(trace: Trace | None) -> bool:
    """Whether a requirement reached the configuration.

    Args:
        trace: The requirement's trace, or ``None`` when stage 4 linked nothing.

    Returns:
        ``True`` when an element implements it. The three conditions match what the
        traceability matrix calls "missing", so the two views cannot disagree.
    """
    return trace is not None and trace.element_id is not None and trace.verdict != "not_related"


def _summary(rule: Rule) -> str:
    """A short rendering of a requirement for the coverage panel.

    Args:
        rule: The requirement.

    Returns:
        Its own text when the extraction kept it, otherwise its type and payload. Never
        a sample row: a requirement's text is OSL prose, which is allowed anywhere the
        OSL is (ADR-003).
    """
    if rule.source_text:
        return rule.source_text[:240]
    if rule.values:
        return f"{rule.req_type}: {', '.join(rule.values[:8])}"
    if rule.steps:
        return f"{rule.req_type}: {' → '.join(rule.steps[:8])}"
    if rule.conditions:
        parts = [f"{c.field_name} {c.operator} {c.value}" for c in rule.conditions[:4]]
        return f"{rule.req_type}: {'; '.join(parts)}"
    return rule.req_type


def _state_and_reason(
    rule: Rule, record: CoverageRecord, traced: bool
) -> tuple[RequirementState, str]:
    """Decide what happened to one requirement.

    The order matters. A requirement a check actually answered is covered whatever else
    is true of it. After that, a free-text requirement is manual by its nature, and a
    requirement whose only check could not be evaluated is manual in practice: a person
    has to go and look either way.

    Args:
        rule: The requirement.
        record: What stage 7 recorded.
        traced: Whether stage 4 linked it to a configuration element.

    Returns:
        The state and the sentence explaining it.
    """
    if rule.rule_id in record.checked_rule_ids:
        return "checked", "A report check compared this requirement against the delivery."
    if rule.req_type == _MANUAL_REQ_TYPE:
        return (
            "manual",
            "A free-text requirement: no check can express it, so it is verified by reading.",
        )
    if rule.rule_id in record.unevaluated_rule_ids:
        return (
            "manual",
            "A report check exists for this requirement but could not be evaluated, "
            "so nothing in the delivery was compared against it.",
        )
    if traced:
        return (
            "traced_unchecked",
            "Traced to the configuration, but no report check reached it: nothing in "
            "the delivered reports evidences that it was applied.",
        )
    return (
        "untraced",
        "No configuration element implements this requirement, which is a finding of " "its own.",
    )


def compute(context: RunContext) -> Coverage:
    """Work out what the run checked.

    Args:
        context: The run context, after stage 7.

    Returns:
        One entry per requirement and per uploaded report, plus the run's notices.
    """
    record = context.coverage_record
    requirements = tuple(
        RequirementCoverage(
            rule_id=rule.rule_id,
            req_type=rule.req_type,
            state=state,
            osl_ref=rule.source_ref,
            summary=_summary(rule),
            reason=reason,
        )
        for rule, state, reason in (
            (rule, *_state_and_reason(rule, record, _is_traced(context.trace_for(rule.rule_id))))
            for rule in context.rules
        )
    )
    reports = tuple(
        ReportCoverage(kind=str(kind), checks_applied=record.checks_by_report.get(str(kind), 0))
        for kind in sorted(context.reports, key=str)
    )
    coverage = Coverage(
        requirements=requirements,
        reports=reports,
        notices=tuple(context.notices),
    )
    counts = coverage.counts
    _LOG.info(
        "run %s coverage: %d checked, %d traced but unchecked, %d untraced, %d manual; "
        "%d report(s) with no check",
        context.run_id,
        counts["checked"],
        counts["traced_unchecked"],
        counts["untraced"],
        counts["manual"],
        len(coverage.unchecked_reports),
    )
    return coverage


def as_rows(coverage: Coverage) -> list[dict[str, object]]:
    """Render coverage for storage and for the wire.

    Args:
        coverage: The computed coverage.

    Returns:
        One plain dictionary per requirement, in a shape both the database column and
        the API model read without translation.
    """
    return [
        {
            "rule_id": entry.rule_id,
            "req_type": entry.req_type,
            "state": entry.state,
            "osl_ref": entry.osl_ref,
            "summary": entry.summary,
            "reason": entry.reason,
        }
        for entry in coverage.requirements
    ]


def _as_int(value: object) -> int:
    """Read a stored count back as a number.

    Args:
        value: Whatever the JSON column held.

    Returns:
        The count, or zero when the stored value is not a number. A malformed row must
        not stop a reviewer opening the run.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def from_rows(
    rows: Sequence[dict[str, object]],
    reports: Sequence[dict[str, object]] = (),
    notices: Sequence[str] = (),
) -> Coverage:
    """Rebuild coverage from what was stored.

    Args:
        rows: The stored requirement rows.
        reports: The stored per-report counts.
        notices: The stored run notices.

    Returns:
        The coverage, with anything unreadable left out rather than raising: a stored
        row that no longer parses must not stop a reviewer opening the run.
    """
    requirements: list[RequirementCoverage] = []
    for row in rows:
        state = str(row.get("state", ""))
        if state not in {"checked", "traced_unchecked", "untraced", "manual"}:
            continue
        requirements.append(
            RequirementCoverage(
                rule_id=str(row.get("rule_id", "")),
                req_type=str(row.get("req_type", "")),
                state=state,  # type: ignore[arg-type]
                osl_ref=str(row.get("osl_ref", "")),
                summary=str(row.get("summary", "")),
                reason=str(row.get("reason", "")),
            )
        )
    return Coverage(
        requirements=tuple(requirements),
        reports=tuple(
            ReportCoverage(
                kind=str(r.get("kind", "")),
                checks_applied=_as_int(r.get("checks_applied", 0)),
            )
            for r in reports
        ),
        notices=tuple(notices),
    )
