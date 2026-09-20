"""What already covers the thing someone is writing about (Phase 6.1e).

Two different moments want the same answer.

At **approval**, a candidate rule is fingerprinted against the rules that exist, so an
administrator never promotes a second rule over the same ground without saying so
(:mod:`greenlight_ai.training.synthesis`). That has always run.

At **writing**, a reviewer typing "this field is never blank" should be told that a rule
already says so, or that one says the opposite, while they can still reconsider. Telling
them at the candidate stage is telling them weeks later, through an administrator, about
a sentence they no longer remember writing. This module answers that second question.

It is a lookup, not a judgement: it finds the active rules that touch the same field or
the same anchor and hands them back. Nothing is blocked, because an observation that
contradicts an active rule is often the useful signal that the old rule is wrong
(ADR-021).
"""

from __future__ import annotations

import logging
from typing import Any, Final, Iterable, Mapping, Sequence

import sqlalchemy as sa
from sqlalchemy.orm import Session

from greenlight_ai.db import models
from greenlight_ai.training.lifecycle import RUNNING_STATES

__all__ = ["CONTRADICTION_HINTS", "covering_rules", "reads_as_contradiction"]

_LOG: Final = logging.getLogger(__name__)

#: Words that flip the meaning of a statement about a field. A sentence carrying one of
#: these beside a rule that says the opposite is worth showing the author, and is
#: deliberately a hint rather than a verdict: the model reads meaning, not a regex, and
#: nothing here decides anything (ADR-001).
CONTRADICTION_HINTS: Final[tuple[str, ...]] = (
    "can be blank",
    "may be blank",
    "is sometimes blank",
    "is often blank",
    "is allowed to be",
    "does not have to",
    "need not",
    "is optional",
    "is not required",
    "no longer",
)

#: The constraint kinds whose plain meaning is "this must always be there".
_ALWAYS_PRESENT: Final[frozenset[str]] = frozenset({"not_blank", "fill_rate_min"})


def _fields_in(anchors: Iterable[Mapping[str, Any]]) -> list[str]:
    """The attribute names an observation points at.

    Args:
        anchors: The stored anchors.

    Returns:
        Each field once, lowercased, in the order they appear.
    """
    fields: list[str] = []
    for anchor in anchors:
        name = str(anchor.get("field", "") or "").strip().lower()
        if name and name not in fields:
            fields.append(name)
    return fields


def _references_in(anchors: Iterable[Mapping[str, Any]]) -> list[str]:
    """The OSL sections or configuration paths an observation points at.

    Args:
        anchors: The stored anchors.

    Returns:
        Each reference once, in the order they appear.
    """
    references: list[str] = []
    for anchor in anchors:
        reference = str(anchor.get("reference", "") or "").strip()
        if reference and reference not in references:
            references.append(reference)
    return references


def reads_as_contradiction(statement: str, constraint: str) -> bool:
    """Whether a statement reads as the opposite of a constraint that already runs.

    A hint, and described as one wherever it is shown. The point is to put the existing
    rule in front of the author while they can still reconsider, not to decide that
    they are wrong: an observation that contradicts an active rule is often the signal
    that the old rule needs narrowing (ADR-021).

    Args:
        statement: What the person wrote.
        constraint: The existing rule's constraint kind.

    Returns:
        ``True`` when the statement permits what the constraint forbids.
    """
    if constraint not in _ALWAYS_PRESENT:
        return False
    lowered = " ".join(statement.lower().split())
    return any(hint in lowered for hint in CONTRADICTION_HINTS)


def covering_rules(
    session: Session, anchors: Sequence[Mapping[str, Any]], statement: str = ""
) -> list[dict[str, Any]]:
    """The active rules that already cover what an observation points at.

    Args:
        session: An open session.
        anchors: The observation's anchors.
        statement: What the person wrote, used only to mark a likely contradiction.

    Returns:
        One entry per covering rule: its kind, id, name, what it asserts, and whether
        the statement reads as the opposite of it. Empty when nothing covers this,
        which is the ordinary case.
    """
    fields = _fields_in(anchors)
    references = _references_in(anchors)
    if not fields and not references:
        return []

    found: list[dict[str, Any]] = []

    if fields:
        rows = session.execute(
            sa.select(models.FieldConstraint).where(
                sa.func.lower(models.FieldConstraint.field).in_(fields),
                models.FieldConstraint.state.in_(tuple(RUNNING_STATES)),
            )
        ).scalars()
        for row in rows:
            found.append(
                {
                    "kind": "field_constraint",
                    "id": row.id,
                    "name": row.field,
                    "summary": f"{row.field} {row.constraint.replace('_', ' ')}".strip(),
                    "scope": row.scope,
                    "state": row.state,
                    "contradicts": reads_as_contradiction(statement, row.constraint),
                }
            )

    if references:
        # A compliance rule names the configuration path it requires, so an observation
        # anchored to that path is about the same thing.
        rows_c = session.execute(
            sa.select(models.ComplianceRuleRow).where(
                models.ComplianceRuleRow.state.in_(tuple(RUNNING_STATES))
            )
        ).scalars()
        for rule in rows_c:
            requirement = rule.requirement if isinstance(rule.requirement, dict) else {}
            path = str(requirement.get("json_path_contains", "") or "")
            if path and any(path in reference or reference in path for reference in references):
                found.append(
                    {
                        "kind": "compliance_rule",
                        "id": rule.id,
                        "name": rule.name,
                        "summary": f"the configuration must contain {path}",
                        "scope": rule.scope,
                        "state": rule.state,
                        "contradicts": False,
                    }
                )

    if found:
        _LOG.info(
            "observation anchors are already covered by %d active rule(s)",
            len(found),
        )
    return found
