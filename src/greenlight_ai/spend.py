"""What a run cost, and who is spending (Phase 6.21d).

The tool has counted tokens since Phase 2 — per call, per stage, per day. Nobody could
see what any of it *cost*, and nobody could see who was spending: the per-person usage
report counts runs, failures and holds, and has never counted a token.

This is the whole of the change, and what it deliberately is not:

**It is arithmetic over what is already stored.** Every figure comes from the
``llm_calls`` rows the adapter writes. Nothing new is recorded, nothing is estimated,
and a run's cost is its tokens times a rate somebody typed in.

**It refuses nothing.** The per-run token budget stays the only hard stop in the
product (``LLM_MAX_TOKENS_PER_RUN``). A monthly band produces a warning on a screen, and
a warning is a thing an administrator reads, not a thing that stops a delivery being
validated. Adding a second refusal is a decision for after somebody has looked at these
numbers, which is the point of producing them.

**It states its own assumption.** With no rate configured the figures stay in tokens and
no currency appears at all, because a cost built on a rate nobody supplied is a number
that will be quoted back as fact. Cached calls cost nothing and are counted apart,
rather than folded in where they would flatter the total.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Final, Sequence

import sqlalchemy as sa
from sqlalchemy.orm import Session

from greenlight_ai.config.store import resolve
from greenlight_ai.db import models

__all__ = ["Rate", "Spend", "cost_of", "rate_for", "spend_by_day", "spend_for_runs"]

_LOG: Final = logging.getLogger(__name__)

#: A million, named so the arithmetic below reads as what it is.
_PER: Final[int] = 1_000_000


@dataclass(frozen=True, slots=True)
class Rate:
    """What a token costs here, if anybody has said.

    Attributes:
        per_million: Whole currency units per million tokens. Zero means nobody has
            said, and every figure stays in tokens.
        currency: What the amounts are denominated in.
        monthly_warning: The month's spend above which the console shows a band. Zero
            switches it off.
    """

    per_million: float = 0.0
    currency: str = "USD"
    monthly_warning: float = 0.0

    @property
    def known(self) -> bool:
        """Whether a cost can be quoted at all."""
        return self.per_million > 0


@dataclass(frozen=True, slots=True)
class Spend:
    """Tokens and money over some set of runs.

    Attributes:
        tokens: Tokens actually sent, across calls the cache did not serve.
        cached_calls: Calls the cache served, which cost nothing.
        calls: Calls that reached a model.
        cost: ``tokens`` at the configured rate, or ``0.0`` when there is none.
    """

    tokens: int = 0
    cached_calls: int = 0
    calls: int = 0
    cost: float = 0.0


def rate_for(session: Session) -> Rate:
    """Read the configured rate.

    Args:
        session: An open session.

    Returns:
        The rate. Defaults leave every figure in tokens, which is the right state until
        somebody who knows the contract fills it in.
    """
    return Rate(
        per_million=float(resolve(session, "cost.per_million_tokens").value or 0),
        currency=str(resolve(session, "cost.currency").value or "USD").strip() or "USD",
        monthly_warning=float(resolve(session, "cost.monthly_warning").value or 0),
    )


def cost_of(tokens: int, rate: Rate) -> float:
    """What some tokens cost.

    Args:
        tokens: Tokens sent.
        rate: The configured rate.

    Returns:
        The amount, or ``0.0`` when no rate is configured. Not rounded here: a caller
        showing one run rounds differently from one showing a month, and rounding twice
        is how a column stops adding up.
    """
    return (tokens / _PER) * rate.per_million if rate.known else 0.0


def spend_for_runs(session: Session, run_ids: Sequence[int], rate: Rate) -> dict[int, Spend]:
    """What each of some runs spent.

    Args:
        session: An open session.
        run_ids: The runs to total.
        rate: The configured rate.

    Returns:
        Run id to its spend, absent for a run that made no call at all. Cached calls
        are counted but contribute no tokens, which is how the adapter records them
        (``llm/base.py``) and is what makes a re-check visibly free.
    """
    if not run_ids:
        return {}

    rows = session.execute(
        sa.select(
            models.LlmCall.run_id,
            sa.func.sum(sa.case((models.LlmCall.cached, 0), else_=models.LlmCall.prompt_tokens)),
            sa.func.sum(
                sa.case((models.LlmCall.cached, 0), else_=models.LlmCall.completion_tokens)
            ),
            sa.func.sum(sa.case((models.LlmCall.cached, 1), else_=0)),
            sa.func.sum(sa.case((models.LlmCall.cached, 0), else_=1)),
        )
        .where(models.LlmCall.run_id.in_(run_ids))
        .group_by(models.LlmCall.run_id)
    ).all()

    built: dict[int, Spend] = {}
    for run_id, prompt, completion, cached, sent in rows:
        tokens = int(prompt or 0) + int(completion or 0)
        built[int(run_id)] = Spend(
            tokens=tokens,
            cached_calls=int(cached or 0),
            calls=int(sent or 0),
            cost=cost_of(tokens, rate),
        )
    return built


def spend_by_day(
    session: Session, start: dt.date, end: dt.date, rate: Rate
) -> list[tuple[dt.date, Spend]]:
    """What the deployment spent each day of a period.

    Args:
        session: An open session.
        start: First day, inclusive.
        end: Last day, inclusive.
        rate: The configured rate.

    Returns:
        One entry per day that made a call, oldest first. Sparse: a quiet day is
        absent rather than a zero, which is how every other per-day series in the
        product is built.
    """
    day = sa.func.date(models.LlmCall.created_at)
    rows = session.execute(
        sa.select(
            day,
            sa.func.sum(sa.case((models.LlmCall.cached, 0), else_=models.LlmCall.prompt_tokens)),
            sa.func.sum(
                sa.case((models.LlmCall.cached, 0), else_=models.LlmCall.completion_tokens)
            ),
            sa.func.sum(sa.case((models.LlmCall.cached, 1), else_=0)),
            sa.func.sum(sa.case((models.LlmCall.cached, 0), else_=1)),
        )
        .where(
            models.LlmCall.created_at >= dt.datetime.combine(start, dt.time.min),
            models.LlmCall.created_at
            < dt.datetime.combine(end + dt.timedelta(days=1), dt.time.min),
        )
        .group_by(day)
        .order_by(day)
    ).all()

    built: list[tuple[dt.date, Spend]] = []
    for raw_day, prompt, completion, cached, sent in rows:
        parsed = raw_day if isinstance(raw_day, dt.date) else dt.date.fromisoformat(str(raw_day))
        tokens = int(prompt or 0) + int(completion or 0)
        built.append(
            (
                parsed,
                Spend(
                    tokens=tokens,
                    cached_calls=int(cached or 0),
                    calls=int(sent or 0),
                    cost=cost_of(tokens, rate),
                ),
            )
        )
    return built
