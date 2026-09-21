"""Keeping each finding signature's state current (Phase 6.18a).

`demotion.py` holds the rules and does the arithmetic; this is the part that reads the
findings a database already has and writes down what those rules conclude. Split so the
reasoning can be tested without a database, which is also how `checks/` is arranged.

The state is recomputed when a person records a verdict, because that is the only event
that can change it. Recomputing reads every finding sharing the signature rather than
adjusting a counter, so a corrected verdict, a deleted run or a restored signature all
land correctly without anybody having to remember to undo something.

**In 6.18a nothing reads the result to decide what a reviewer sees** (ADR-043). The
review queue is exactly what it was.
"""

from __future__ import annotations

import logging
from typing import Final, Sequence

import sqlalchemy as sa
from sqlalchemy.orm import Session

from greenlight_ai.db import models
from greenlight_ai.db.types import utcnow
from greenlight_ai.training import demotion

__all__ = ["recompute_for_finding", "recompute_for_run", "signature_of", "would_demote"]

_LOG: Final = logging.getLogger(__name__)


def signature_of(run: models.Run, finding: models.Finding) -> str:
    """The signature a stored finding belongs to.

    Args:
        run: The run the finding came from, for the customer and the programme.
        finding: The stored finding.

    Returns:
        The digest. See :func:`greenlight_ai.training.demotion.signature`.
    """
    return demotion.signature(
        customer_name=run.customer_name,
        scope=run.scope,
        rule_ref=finding.rule_ref,
        finding_type=finding.type,
        element_ref=finding.element_ref,
    )


def _verdicts(
    session: Session, run: models.Run, finding: models.Finding
) -> list[tuple[str, str, int]]:
    """Every verdict recorded against this signature, oldest first.

    Args:
        session: An open session.
        run: The run the triggering finding came from.
        finding: The triggering finding, for the rule, type and element.

    Returns:
        ``(review_status, severity, run_id)`` per finding, oldest decision first.
        Shadow findings are excluded: a rule nobody has been shown cannot have earned
        anybody's trust, and counting it would let a shadow rule demote itself.
    """
    rows = session.execute(
        sa.select(
            models.Finding.review_status,
            models.Finding.severity,
            models.Finding.run_id,
        )
        .join(models.Run, models.Run.id == models.Finding.run_id)
        .where(
            models.Run.customer_name == run.customer_name,
            models.Run.scope == run.scope,
            models.Finding.rule_ref == finding.rule_ref,
            models.Finding.type == finding.type,
            models.Finding.element_ref == finding.element_ref,
            models.Finding.shadow.is_(False),
            models.Finding.review_status != "undecided",
        )
        .order_by(models.Finding.reviewed_at, models.Finding.id)
    ).all()
    return [(str(status), str(severity), int(run_id)) for status, severity, run_id in rows]


def recompute_for_finding(
    session: Session, finding: models.Finding
) -> models.FindingSignatureState | None:
    """Bring one signature's state up to date after a verdict.

    Args:
        session: An open session. Flushed, not committed: the caller owns the
            transaction the verdict itself was written in.
        finding: The finding whose verdict has just been recorded.

    Returns:
        The stored state, or ``None`` when the finding carries no rule reference and so
        belongs to no signature worth tracking.
    """
    if not finding.rule_ref:
        return None
    run = session.get(models.Run, finding.run_id)
    if run is None:
        return None

    digest = signature_of(run, finding)
    counted = demotion.tally(_verdicts(session, run, finding))
    state, reason = demotion.decide(counted)

    row = session.execute(
        sa.select(models.FindingSignatureState).where(
            models.FindingSignatureState.signature == digest
        )
    ).scalar_one_or_none()
    if row is None:
        row = models.FindingSignatureState(
            signature=digest,
            customer_name=run.customer_name,
            scope=run.scope,
            rule_ref=finding.rule_ref,
            finding_type=finding.type,
            element_ref=finding.element_ref,
            first_seen=utcnow(),
        )
        session.add(row)

    row.state = state
    row.reason = reason
    row.occurrences = counted.occurrences
    row.dismissed = counted.dismissed
    row.upheld = counted.upheld
    row.severities = sorted(counted.severities)
    row.justified_by_run_ids = list(demotion.justifying_runs(counted))
    row.last_seen = utcnow()
    session.flush()

    if state == demotion.WOULD_DEMOTE:
        _LOG.info(
            "signature %s would demote: %s occurrences, all dismissed (customer=%s scope=%s)",
            digest,
            counted.occurrences,
            run.customer_name,
            run.scope or "-",
        )
    return row


def recompute_for_run(session: Session, run_id: int) -> int:
    """Bring every signature touched by one run up to date.

    Used after a bulk decision, where recomputing per finding would read the same rows
    many times over.

    Args:
        session: An open session.
        run_id: The run whose findings were just decided.

    Returns:
        How many distinct signatures were updated.
    """
    findings = list(
        session.execute(
            sa.select(models.Finding).where(
                models.Finding.run_id == run_id,
                models.Finding.review_status != "undecided",
            )
        ).scalars()
    )
    seen: set[str] = set()
    for finding in findings:
        if not finding.rule_ref:
            continue
        run = session.get(models.Run, finding.run_id)
        if run is None:
            continue
        digest = signature_of(run, finding)
        if digest in seen:
            continue
        seen.add(digest)
        recompute_for_finding(session, finding)
    return len(seen)


def would_demote(
    session: Session, *, customer_name: str = "", scope: str = ""
) -> Sequence[models.FindingSignatureState]:
    """The signatures that have earned their way out of the review queue.

    What 6.18b will act on and 6.18c will measure. In 6.18a it is a report an
    administrator can read and nothing else.

    Args:
        session: An open session.
        customer_name: Limit to one customer, or every customer when empty.
        scope: Limit to one delivery programme, or every programme when empty.

    Returns:
        The rows, most recently seen first.
    """
    query = sa.select(models.FindingSignatureState).where(
        models.FindingSignatureState.state == demotion.WOULD_DEMOTE
    )
    if customer_name:
        query = query.where(models.FindingSignatureState.customer_name == customer_name)
    if scope:
        query = query.where(models.FindingSignatureState.scope == scope)
    return list(
        session.execute(query.order_by(models.FindingSignatureState.last_seen.desc())).scalars()
    )
