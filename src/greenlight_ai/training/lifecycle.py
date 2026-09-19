"""The one place a rule changes state (ADR-021).

    draft → shadow → active ⇄ disabled → deleted → (permanent after six months)

Every transition records who made it and when, and **no transition happens by
itself**. No rule expires: a rule that has not fired in a year is either load-bearing
or dead, and nothing inside the system can tell which, so a person decides and the
dead-rule report is what puts the question in front of them.

Deletion is soft. A deleted rule stops running immediately and can be restored whole
for six months, after which what remains is a tombstone — identity, version, and
reasoning — because findings on old runs cite a rule by reference and must still
explain themselves.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Final, Literal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from greenlight_ai.db import models

__all__ = [
    "RULE_STATES",
    "RESTORE_WINDOW_DAYS",
    "RuleKind",
    "RuleState",
    "LifecycleError",
    "set_state",
    "enable_rule",
    "disable_rule",
    "delete_rule",
    "restore_rule",
    "purge_deleted_rules",
    "load_rule",
]

_LOG: Final = logging.getLogger(__name__)

RuleKind = Literal["check", "compliance_rule", "field_constraint", "programme_rule"]
RuleState = Literal["draft", "shadow", "active", "disabled", "deleted"]

#: Every state a rule can be in. ``draft`` and ``shadow`` exist so that "suggested"
#: and "active" are never the same thing, which is the one convention every mature
#: data-quality tool shares.
RULE_STATES: Final[tuple[str, ...]] = ("draft", "shadow", "active", "disabled", "deleted")

#: How long a deleted rule can be brought back. Long enough that a mistake is noticed
#: in the ordinary course of a quarter's work, short enough that the list stays
#: readable.
RESTORE_WINDOW_DAYS: Final[int] = 183

#: Which states actually produce findings a reviewer sees. ``shadow`` runs and counts
#: but shows nobody, which is where a rule's precision becomes knowable.
VISIBLE_STATES: Final[frozenset[str]] = frozenset({"active"})
RUNNING_STATES: Final[frozenset[str]] = frozenset({"active", "shadow"})

_TABLES: Final[dict[str, Any]] = {
    "check": models.CheckDefinitionRow,
    "compliance_rule": models.ComplianceRuleRow,
    "field_constraint": models.FieldConstraint,
    "programme_rule": models.ProgrammeRule,
}


class LifecycleError(Exception):
    """A state change that is not allowed, with the reason in its message."""


def load_rule(session: Session, rule_kind: str, rule_id: int) -> Any:
    """Fetch a rule of any kind.

    Args:
        session: An open session.
        rule_kind: ``check``, ``compliance_rule``, or ``field_constraint``.
        rule_id: The row id.

    Returns:
        The row.

    Raises:
        LifecycleError: When the kind is unknown or the rule does not exist.
    """
    table = _TABLES.get(rule_kind)
    if table is None:
        raise LifecycleError(f"{rule_kind!r} is not a rule kind")
    row = session.get(table, rule_id)
    if row is None:
        raise LifecycleError(f"no {rule_kind} with id {rule_id}")
    return row


def set_state(
    session: Session,
    rule_kind: str,
    rule_id: int,
    to_state: str,
    *,
    actor: str = "",
    user_id: int | None = None,
    note: str = "",
) -> Any:
    """Move a rule to a new state and record who did it.

    Args:
        session: An open session.
        rule_kind: Which rule surface.
        rule_id: The row id.
        to_state: The new state.
        actor: Who is doing it.
        user_id: Their account id.
        note: Why, when there is a reason worth keeping.

    Returns:
        The updated row.

    Raises:
        LifecycleError: When the state is unknown, or when restoring a rule whose
            six-month window has passed.
    """
    if to_state not in RULE_STATES:
        raise LifecycleError(f"{to_state!r} is not a rule state")

    row = load_rule(session, rule_kind, rule_id)
    from_state = row.state
    now = dt.datetime.now(dt.timezone.utc)

    if from_state == "deleted" and to_state != "deleted":
        deleted_at = row.deleted_at
        if deleted_at is not None and now - deleted_at > dt.timedelta(days=RESTORE_WINDOW_DAYS):
            raise LifecycleError(
                f"this rule was deleted more than {RESTORE_WINDOW_DAYS} days ago and "
                "can no longer be restored"
            )

    row.state = to_state
    row.deleted_at = now if to_state == "deleted" else None
    # `is_active` is what every existing query reads, so the two are kept consistent
    # here rather than in each caller. Only `active` produces findings a reviewer
    # sees; a shadowed rule runs and is counted, and nothing else runs at all.
    if hasattr(row, "is_active"):
        row.is_active = to_state == "active"

    session.add(
        models.RuleStateChange(
            rule_kind=rule_kind,
            rule_id=rule_id,
            from_state=from_state,
            to_state=to_state,
            note=note[:2000],
            actor_user_id=user_id,
            actor=actor[:200],
        )
    )
    session.flush()
    _LOG.info("%s %d: %s -> %s by %s", rule_kind, rule_id, from_state, to_state, actor or "?")
    if rule_kind == "programme_rule":
        from greenlight_ai.db import versions

        versions.record_programme_version(
            session, row.scope_code, actor, f"rule {to_state}: {row.title}"
        )
    return row


def enable_rule(session: Session, rule_kind: str, rule_id: int, **who: Any) -> Any:
    """Put a rule back into service.

    Args:
        session: An open session.
        rule_kind: Which rule surface.
        rule_id: The row id.
        **who: ``actor``, ``user_id``, and ``note``.

    Returns:
        The updated row.
    """
    return set_state(session, rule_kind, rule_id, "active", **who)


def disable_rule(session: Session, rule_kind: str, rule_id: int, **who: Any) -> Any:
    """Switch a rule off, reversibly.

    This is where a noisy rule goes, and where a rule goes that is wrong for now and
    may be right later. Deleting it would throw away the argument for it.

    Args:
        session: An open session.
        rule_kind: Which rule surface.
        rule_id: The row id.
        **who: ``actor``, ``user_id``, and ``note``.

    Returns:
        The updated row.
    """
    return set_state(session, rule_kind, rule_id, "disabled", **who)


def delete_rule(session: Session, rule_kind: str, rule_id: int, **who: Any) -> Any:
    """Delete a rule, restorable for six months.

    Args:
        session: An open session.
        rule_kind: Which rule surface.
        rule_id: The row id.
        **who: ``actor``, ``user_id``, and ``note``.

    Returns:
        The updated row.
    """
    return set_state(session, rule_kind, rule_id, "deleted", **who)


def restore_rule(session: Session, rule_kind: str, rule_id: int, **who: Any) -> Any:
    """Bring a deleted rule back, switched off.

    It returns disabled rather than active on purpose: whoever deleted it had a
    reason, and the person restoring it should look before it starts producing
    findings again.

    Args:
        session: An open session.
        rule_kind: Which rule surface.
        rule_id: The row id.
        **who: ``actor``, ``user_id``, and ``note``.

    Returns:
        The updated row.

    Raises:
        LifecycleError: When the six-month window has passed.
    """
    return set_state(session, rule_kind, rule_id, "disabled", **who)


def purge_deleted_rules(session: Session) -> int:
    """Make old deletions permanent, keeping a tombstone.

    Args:
        session: An open session.

    Returns:
        How many rules passed out of the restore window. Their bodies are cleared and
        they stop appearing anywhere, but the row survives: findings on old runs cite
        a rule by reference, and a reference to nothing explains nothing.
    """
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=RESTORE_WINDOW_DAYS)
    purged = 0
    for kind, table in _TABLES.items():
        rows = session.execute(
            sa.select(table).where(
                table.state == "deleted",
                table.deleted_at.is_not(None),
                table.deleted_at < cutoff,
            )
        ).scalars()
        for row in rows:
            if getattr(row, "expression", None):
                row.expression = ""
            if getattr(row, "instruction", None):
                row.instruction = ""
            if hasattr(row, "requirement"):
                row.requirement = {}
            if hasattr(row, "value"):
                row.value = {}
            if hasattr(row, "text"):
                row.text = ""
            purged += 1
            _LOG.info("%s %d is now permanently deleted; a tombstone remains", kind, row.id)
    session.flush()
    return purged
