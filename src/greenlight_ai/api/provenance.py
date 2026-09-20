"""Where a finding came from, and what became of what a person wrote (Phase 6.13b).

A finding carries ``rule_ref``, one of ``check:N``, ``compliance_rule:N``,
``field_constraint:N`` or ``programme_rule:N``, or an OSL requirement id, or nothing.
Until now that reference went to the reviewer as a bare string, and the only way to
learn that a finding came from a rule somebody's observation produced was to open the
admin console and search. This module answers the question once, for findings and for
observations alike, so the person who wrote a sentence can be told that it became rule
so-and-so, is in shadow, and is now live.

Nothing here decides anything. It reads the rule tables and renders.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Iterable, Mapping

import sqlalchemy as sa
from sqlalchemy.orm import Session

from greenlight_ai.api import schemas
from greenlight_ai.db import models

__all__ = [
    "RULE_TABLES",
    "RuleFacts",
    "decorate_findings",
    "facts_for_refs",
    "origin_of",
    "outcome_of",
    "parse_ref",
    "rule_from_candidate",
    "summary_of",
]

#: The four rule surfaces, by the kind a ``rule_ref`` names.
RULE_TABLES: Final[Mapping[str, Any]] = {
    "check": models.CheckDefinitionRow,
    "compliance_rule": models.ComplianceRuleRow,
    "field_constraint": models.FieldConstraint,
    "programme_rule": models.ProgrammeRule,
}

#: How a stored ``origin`` reads to a reviewer. A programme rule is always the
#: administrator's; everything else says where it came from.
_ORIGINS: Final[frozenset[str]] = frozenset({"admin", "guide", "meaning", "learned"})


@dataclass(frozen=True, slots=True)
class RuleFacts:
    """What a reviewer or an author needs to know about one rule.

    Attributes:
        ref: ``kind:id``.
        kind: Which rule surface.
        id: The row id.
        name: What the rule is called.
        summary: One line saying what it checks.
        origin: ``admin`` · ``guide`` · ``meaning`` · ``learned``.
        state: The lifecycle state (ADR-021).
        candidate_id: The candidate it was approved from, for a learned rule.
    """

    ref: str
    kind: str
    id: int
    name: str
    summary: str
    origin: str
    state: str
    candidate_id: int | None


def parse_ref(ref: str) -> tuple[str, int] | None:
    """Split a rule reference into its kind and id.

    Args:
        ref: The stored reference.

    Returns:
        The pair, or ``None`` for an OSL requirement id, an empty reference, or
        anything else that is not a rule.
    """
    kind, sep, raw = (ref or "").partition(":")
    if not sep or kind not in RULE_TABLES or not raw.isdigit():
        return None
    return kind, int(raw)


def summary_of(kind: str, row: Any) -> str:
    """One line saying what a rule actually checks.

    Args:
        kind: Which rule surface.
        row: The rule.

    Returns:
        The summary the rules screen searches and shows, and a finding now names.
    """
    if kind == "field_constraint":
        return f"{row.field} {row.constraint} {row.value}"
    if kind == "programme_rule":
        return f"{row.scope_code} {row.strictness}: {row.text}"
    if kind == "check":
        return str(row.expression or row.instruction)
    return str((row.requirement or {}).get("json_path_contains", ""))


def _facts(kind: str, row: Any) -> RuleFacts:
    origin = str(getattr(row, "origin", "admin") or "admin")
    return RuleFacts(
        ref=f"{kind}:{row.id}",
        kind=kind,
        id=int(row.id),
        name=str(
            getattr(row, "name", "") or getattr(row, "title", "") or getattr(row, "field", "")
        ),
        summary=summary_of(kind, row),
        origin=origin if origin in _ORIGINS else "admin",
        state=str(getattr(row, "state", "active") or "active"),
        candidate_id=getattr(row, "candidate_id", None),
    )


def facts_for_refs(session: Session, refs: Iterable[str]) -> dict[str, RuleFacts]:
    """Look up every rule a set of references names, one query per rule kind.

    Args:
        session: An open session.
        refs: The references, with repeats and non-rule references welcome.

    Returns:
        Reference to facts, for the references that name a rule that exists.
    """
    wanted: dict[str, set[int]] = {}
    for ref in refs:
        parsed = parse_ref(ref)
        if parsed is not None:
            wanted.setdefault(parsed[0], set()).add(parsed[1])

    out: dict[str, RuleFacts] = {}
    for kind, ids in wanted.items():
        table = RULE_TABLES[kind]
        for row in session.execute(sa.select(table).where(table.id.in_(sorted(ids)))).scalars():
            facts = _facts(kind, row)
            out[facts.ref] = facts
    return out


def origin_of(facts: RuleFacts | None) -> str:
    """How a finding's provenance reads to a reviewer.

    Args:
        facts: The rule behind the finding, or ``None`` when code produced it from
            the OSL and the configuration alone.

    Returns:
        ``built_in`` · ``admin`` · ``guide`` · ``meaning`` · ``learned``.
    """
    return facts.origin if facts is not None else "built_in"


def rule_from_candidate(session: Session, candidate_id: int) -> RuleFacts | None:
    """The rule an approved candidate became, if any.

    Args:
        session: An open session.
        candidate_id: The candidate.

    Returns:
        The rule's facts, or ``None`` while the candidate is a draft or was rejected.
    """
    for kind, table in RULE_TABLES.items():
        if not hasattr(table, "candidate_id"):
            continue
        row = (
            session.execute(sa.select(table).where(table.candidate_id == candidate_id))
            .scalars()
            .first()
        )
        if row is not None:
            return _facts(kind, row)
    return None


def outcome_of(
    session: Session, observation: models.TrainingObservation
) -> tuple[str, str, RuleFacts | None]:
    """What became of one observation, read from the rule tables rather than written.

    Derived rather than stored on purpose: a status written at approval time would
    say "approved" forever, while the rule it produced went live, was narrowed, or
    was disabled. The rule's own state is the truth, and this reads it.

    Args:
        session: An open session.
        observation: The observation.

    Returns:
        The outcome — ``waiting`` · ``drafted`` · ``approved`` (in shadow) · ``live`` ·
        ``disabled`` · ``rejected`` — a note for the author when there is one, and the
        rule's facts when a rule exists.
    """
    if observation.status == "rejected":
        return "rejected", observation.status_note or "", None
    if not observation.candidate_id:
        return "waiting", "", None

    candidate = session.get(models.RuleCandidate, observation.candidate_id)
    if candidate is None:
        return "waiting", "", None
    if candidate.status == "rejected":
        return "rejected", candidate.admin_note or "", None
    if candidate.status != "approved":
        return "drafted", "", None

    facts = rule_from_candidate(session, candidate.id)
    if facts is None:
        return "drafted", "", None
    if facts.state == "active":
        return "live", "", facts
    if facts.state in ("disabled", "deleted"):
        return "disabled", "", facts
    return "approved", "", facts


def decorate_findings(
    session: Session, findings: list[schemas.FindingOut]
) -> list[schemas.FindingOut]:
    """Fill in where each finding came from, in one pass.

    Args:
        session: An open session.
        findings: The wire findings, fresh from the rows.

    Returns:
        The same list, each finding carrying its origin and the rule's name and
        summary. A finding with no rule behind it says ``built_in``.
    """
    facts = facts_for_refs(session, (f.rule_ref for f in findings))
    for finding in findings:
        fact = facts.get(finding.rule_ref)
        finding.origin = origin_of(fact)
        if fact is not None:
            finding.rule_name = fact.name
            finding.rule_summary = fact.summary
    return findings
