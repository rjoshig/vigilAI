"""What a run cost, and who is spending (Phase 6.21d).

Two properties carry the whole of this part. **Nothing new refuses anything** — the
per-run token budget stays the only hard stop, and a monthly band is a warning on a
screen. And **no rate means no money**: with nothing configured the figures stay in
tokens and no currency appears at all, because a cost built on a rate nobody supplied
is a number that gets quoted back as fact.

The third thing worth pinning: a cached call costs nothing and is counted apart.
Folding it in would flatter the total, and a re-check — which is all cache hits — would
appear to cost as much as the run it re-checked.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai import spend
from greenlight_ai.config.store import invalidate, write_setting
from greenlight_ai.db import models
from greenlight_ai.db.session import create_all, create_engine, session_factory
from greenlight_ai.db.settings import DbSettings


@pytest.fixture()
def session(tmp_path: Path) -> Iterator[Session]:
    settings = DbSettings(url=f"sqlite+pysqlite:///{tmp_path}/t.db", data_dir=tmp_path)
    engine = create_engine(settings)
    create_all(engine)
    factory: sessionmaker[Session] = session_factory(engine)
    invalidate()
    with factory() as open_session:
        yield open_session
    invalidate()


def _run(session: Session, status: str = "finalized") -> models.Run:
    run = models.Run(
        customer_name="Northwind Lending",
        order_number="ORD-1",
        configuration_id="CFG-1",
        status=status,
    )
    session.add(run)
    session.flush()
    return run


def _call(
    session: Session,
    run: models.Run,
    prompt: int = 0,
    completion: int = 0,
    cached: bool = False,
    at: dt.datetime | None = None,
) -> None:
    session.add(
        models.LlmCall(
            run_id=run.id,
            stage="s2_extract",
            provider="mock",
            model="m",
            prompt_tokens=prompt,
            completion_tokens=completion,
            cached=cached,
            **({"created_at": at} if at else {}),
        )
    )
    session.flush()


# --------------------------------------------------------------------- the rate


def test_no_rate_means_no_money(session: Session) -> None:
    """The default, and the only honest state until somebody knows the contract."""
    rate = spend.rate_for(session)
    assert rate.per_million == 0.0
    assert rate.known is False
    assert spend.cost_of(1_000_000, rate) == 0.0


def test_a_rate_turns_tokens_into_money(session: Session) -> None:
    write_setting(session, "cost.per_million_tokens", "3", actor="tester")
    invalidate()

    rate = spend.rate_for(session)
    assert rate.known is True
    assert spend.cost_of(1_000_000, rate) == pytest.approx(3.0)
    assert spend.cost_of(250_000, rate) == pytest.approx(0.75)


def test_a_currency_nobody_set_falls_back_rather_than_blanking(session: Session) -> None:
    write_setting(session, "cost.currency", "   ", actor="tester")
    invalidate()
    assert spend.rate_for(session).currency == "USD"


# ------------------------------------------------------------------- per run


def test_a_run_totals_only_what_it_sent(session: Session) -> None:
    write_setting(session, "cost.per_million_tokens", "10", actor="tester")
    invalidate()
    run = _run(session)
    _call(session, run, prompt=100, completion=50)
    _call(session, run, prompt=200, completion=25)

    spent = spend.spend_for_runs(session, [run.id], spend.rate_for(session))[run.id]
    assert spent.tokens == 375
    assert spent.calls == 2
    assert spent.cost == pytest.approx(375 / 1_000_000 * 10)


def test_a_cached_call_costs_nothing_and_is_counted_apart(session: Session) -> None:
    """Which is what makes a re-check visibly free, and is why it is not folded in."""
    write_setting(session, "cost.per_million_tokens", "10", actor="tester")
    invalidate()
    run = _run(session)
    _call(session, run, prompt=100, completion=50)
    _call(session, run, cached=True)
    _call(session, run, cached=True)

    spent = spend.spend_for_runs(session, [run.id], spend.rate_for(session))[run.id]
    assert spent.tokens == 150
    assert spent.calls == 1
    assert spent.cached_calls == 2


def test_a_run_that_called_nothing_is_absent_rather_than_zero(session: Session) -> None:
    run = _run(session)
    assert spend.spend_for_runs(session, [run.id], spend.rate_for(session)) == {}


def test_asking_about_no_runs_costs_no_query(session: Session) -> None:
    assert spend.spend_for_runs(session, [], spend.rate_for(session)) == {}


def test_one_run_is_not_charged_for_another(session: Session) -> None:
    first, second = _run(session), _run(session)
    _call(session, first, prompt=100)
    _call(session, second, prompt=900)

    spent = spend.spend_for_runs(session, [first.id, second.id], spend.rate_for(session))
    assert spent[first.id].tokens == 100
    assert spent[second.id].tokens == 900


# ------------------------------------------------------------------- per day


def test_a_period_is_grouped_by_day(session: Session) -> None:
    run = _run(session)
    today = dt.datetime.now(dt.timezone.utc)
    yesterday = today - dt.timedelta(days=1)
    _call(session, run, prompt=100, at=yesterday)
    _call(session, run, prompt=50, at=yesterday)
    _call(session, run, prompt=25, at=today)

    days = spend.spend_by_day(session, yesterday.date(), today.date(), spend.rate_for(session))
    assert [entry.tokens for _day, entry in days] == [150, 25]
    assert [day for day, _entry in days] == [yesterday.date(), today.date()]


def test_the_last_day_of_the_period_is_included(session: Session) -> None:
    """Off by one here would silently drop today, which is the day somebody is asking about."""
    run = _run(session)
    now = dt.datetime.now(dt.timezone.utc)
    _call(session, run, prompt=42, at=now)

    days = spend.spend_by_day(session, now.date(), now.date(), spend.rate_for(session))
    assert [entry.tokens for _day, entry in days] == [42]


def test_a_quiet_day_is_absent_rather_than_a_zero(session: Session) -> None:
    """Sparse, like every other per-day series in the product."""
    run = _run(session)
    now = dt.datetime.now(dt.timezone.utc)
    _call(session, run, prompt=42, at=now)

    days = spend.spend_by_day(
        session, now.date() - dt.timedelta(days=5), now.date(), spend.rate_for(session)
    )
    assert len(days) == 1


def test_a_call_outside_the_period_is_not_counted(session: Session) -> None:
    run = _run(session)
    now = dt.datetime.now(dt.timezone.utc)
    _call(session, run, prompt=999, at=now - dt.timedelta(days=10))

    days = spend.spend_by_day(
        session, now.date() - dt.timedelta(days=2), now.date(), spend.rate_for(session)
    )
    assert days == []


# ---------------------------------------------------------------- the warning


def test_the_monthly_band_is_read_but_refuses_nothing(session: Session) -> None:
    """The property the whole part rests on: this produces a number, not a gate.

    Nothing in :mod:`greenlight_ai.spend` can refuse a submission — there is no code
    path from a band to a rejection, and the only hard stop remains the per-run token
    budget in the adapter.
    """
    write_setting(session, "cost.monthly_warning", "500", actor="tester")
    invalidate()
    assert spend.rate_for(session).monthly_warning == pytest.approx(500.0)

    source = Path("src/greenlight_ai/spend.py").read_text(encoding="utf-8")
    assert "raise" not in source, "nothing here may refuse anything"
    assert "HTTPException" not in source
