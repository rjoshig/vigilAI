"""Findings nobody authored a rule for (Phase 6.21c).

`profile_anomaly` has been a declared finding type since Phase 2, labelled in the UI
and used in a prompt example, and nothing in `src/` ever produced one. These are what
producing one has to be worth: it fires on a real shift, it stays quiet on ordinary
variation, and — the property that decides whether anybody ever trusts the category —
it says nothing at all until it has enough history to have an opinion.
"""

from __future__ import annotations

from typing import Mapping, Sequence

import pytest

from greenlight_ai.checks import anomaly
from greenlight_ai.checks.profile import AttributeProfile


def shape(**measures: float | None) -> Mapping[str, AttributeProfile]:
    """One delivery, as one attribute's numbers."""
    return {"mort_bal": AttributeProfile(name="MORT_BAL", **measures)}


def steady(count: int, **measures: float) -> Sequence[Mapping[str, AttributeProfile]]:
    """A history of identical deliveries."""
    return [shape(**measures) for _ in range(count)]


def wobbling(
    values: Sequence[float], measure: str = "null_rate"
) -> list[Mapping[str, AttributeProfile]]:
    """A history whose one measure moves a little from delivery to delivery."""
    return [shape(**{measure: value}) for value in values]


# ------------------------------------------------------------------- staying quiet


def test_it_says_nothing_without_enough_history() -> None:
    """The property that decides whether the category is ever trusted.

    A baseline of one delivery is not a baseline, and a tool that invented one would
    teach reviewers to ignore the whole thing in its first week.
    """
    history = wobbling([0.04, 0.041])
    assert anomaly.compare(shape(null_rate=0.9), history) == []


def test_a_delivery_inside_its_own_variation_produces_nothing() -> None:
    history = wobbling([0.040, 0.043, 0.038, 0.041, 0.039])
    assert anomaly.compare(shape(null_rate=0.042), history) == []


def test_a_measure_this_delivery_does_not_report_is_not_an_anomaly() -> None:
    """A missing number is a gap, not a change, and the coverage panel owns gaps."""
    history = wobbling([0.040, 0.043, 0.038, 0.041])
    assert anomaly.compare(shape(null_rate=None), history) == []


def test_an_attribute_the_history_does_not_carry_is_skipped() -> None:
    """An attribute delivered for the first time has a history of nothing."""
    history = [{"other": AttributeProfile(name="OTHER", null_rate=0.01)} for _ in range(5)]
    assert anomaly.compare(shape(null_rate=0.9), history) == []


def test_an_attribute_that_only_recently_gained_a_measure_is_skipped() -> None:
    """A history of one is a history of one, even inside a history of ten."""
    history = [shape(null_rate=0.04)] + [shape() for _ in range(9)]
    assert anomaly.compare(shape(null_rate=0.9), history) == []


# ------------------------------------------------------------------------- firing


def test_a_null_rate_that_jumps_is_found() -> None:
    """The design doc's own example, at last produced by code rather than a prompt."""
    history = wobbling([0.040, 0.043, 0.038, 0.041, 0.039])
    found = anomaly.compare(shape(null_rate=0.182), history)

    assert len(found) == 1
    assert found[0].attribute == "MORT_BAL"
    assert found[0].measure == "null_rate"
    assert found[0].value == pytest.approx(0.182)
    assert found[0].median == pytest.approx(0.040)
    assert found[0].history == 5


def test_a_history_that_never_moved_is_judged_proportionally() -> None:
    """A multiple of no spread is nothing, so the question becomes how big a change."""
    found = anomaly.compare(shape(minimum=400.0), steady(5, minimum=300.0))

    assert len(found) == 1
    assert found[0].multiple == 0.0, "no spread to be a multiple of"
    assert found[0].share == pytest.approx(1 / 3)


def test_a_small_change_against_a_fixed_number_is_left_alone() -> None:
    """A threshold nudged by a percent is a tuning change, not an anomaly."""
    assert anomaly.compare(shape(minimum=305.0), steady(5, minimum=300.0)) == []


def test_a_number_that_was_always_zero_becoming_something_is_found() -> None:
    """The case no ratio can express, and the one most likely to matter."""
    found = anomaly.compare(shape(null_rate=0.15), steady(4, null_rate=0.0))
    assert len(found) == 1


def test_one_odd_delivery_in_the_history_does_not_hide_the_next() -> None:
    """Why the median, and not the mean.

    A single 60% month drags a mean to 15%, which is close enough to this delivery's
    18% to hide it. The median does not move, so the next one is still found — which
    is the whole reason this does not use a mean and a standard deviation.
    """
    history = wobbling([0.60, 0.040, 0.043, 0.038, 0.041])
    assert anomaly.compare(shape(null_rate=0.182), history), "the outlier did not mask it"


def test_every_measure_is_watched_not_only_the_null_rate() -> None:
    history = [shape(null_rate=0.01, minimum=300.0, maximum=850.0, mean=700.0) for _ in range(5)]
    found = anomaly.compare(
        shape(null_rate=0.01, minimum=300.0, maximum=850.0, mean=120.0), history
    )
    assert [entry.measure for entry in found] == ["mean"]


def test_sensitivity_decides_how_much_is_found() -> None:
    history = wobbling([0.040, 0.043, 0.038, 0.041, 0.039])
    lenient = anomaly.compare(shape(null_rate=0.055), history, sensitivity=20.0)
    strict = anomaly.compare(shape(null_rate=0.055), history, sensitivity=2.0)

    assert lenient == [] and len(strict) == 1


# -------------------------------------------------------------------- what it says


def test_the_finding_carries_the_numbers_that_produced_it() -> None:
    """A finding with no rule behind it has to justify itself, so it says everything."""
    history = wobbling([0.040, 0.043, 0.038, 0.041, 0.039])
    detail = anomaly.describe(anomaly.compare(shape(null_rate=0.182), history)[0])

    assert "18.2%" in detail and "4.0%" in detail
    assert "previous 5 finalized deliveries" in detail
    assert "No rule covers this" in detail
    assert "not the same as being wrong" in detail, "it must not read as an accusation"


def test_the_flat_case_words_itself_differently() -> None:
    """Because "4.0 times the usual spread" is meaningless when there was no spread."""
    detail = anomaly.describe(anomaly.compare(shape(minimum=400.0), steady(5, minimum=300.0))[0])
    assert "has not moved" in detail
    assert "times as far" not in detail


def test_the_title_names_the_attribute_and_the_measure() -> None:
    history = wobbling([0.040, 0.043, 0.038, 0.041, 0.039])
    title = anomaly.compare(shape(null_rate=0.182), history)[0].title
    assert "MORT_BAL" in title and "null rate" in title


# ---------------------------------------------------------------------- measured


def test_the_benchmark_holds_at_the_shipped_sensitivity() -> None:
    """An anomaly detector nobody measured is a false-positive generator.

    The floors are below what `docs/benchmarks/phase-6.21-anomaly.md` records, so a
    change that makes the check noisier fails here rather than in somebody's review
    queue. They are not the numbers to aim at — they are the numbers below which the
    category stops being worth reading.
    """
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from anomaly_benchmark import _rates, score_all  # noqa: PLC0415

    # Fewer trials than the published table: this guards a floor, it does not publish.
    precision, recall = _rates(score_all(trials=120))

    assert recall >= 0.95, "a real shift must not be missed"
    assert precision >= 0.80, "most of what it reports must be real"


# ----------------------------------------------------------- reaching a real run


def test_the_finding_type_is_produced_by_a_real_code_path() -> None:
    """`profile_anomaly` was declared in Phase 2 and constructed nowhere until now.

    Walked through the stage rather than the module, because "the arithmetic works"
    and "a reviewer sees it" are different claims and only the second one is the
    phase's promise.
    """
    from pathlib import Path

    from greenlight_ai.checks.definitions import AdminConfig
    from greenlight_ai.pipeline import s7_reports
    from greenlight_ai.pipeline.context import RunContext

    context = RunContext(
        run_id="TEST-ANOMALY",
        osl_path=Path("osl.docx"),
        config_path=Path("config.json"),
        report_paths={},
        client=None,  # type: ignore[arg-type]
        admin=AdminConfig(),
        profile_history=tuple(wobbling([0.040, 0.043, 0.038, 0.041, 0.039])),
    )
    # Stand in for the DIRT read, which has its own tests.
    reading = dict(shape(null_rate=0.182))
    s7_reports.read_profile = lambda *_a, **_k: reading  # type: ignore[assignment]
    try:
        s7_reports._check_anomalies(context, context.resolver)  # type: ignore[arg-type]
    finally:
        from greenlight_ai.checks.profile import read_profile

        s7_reports.read_profile = read_profile  # type: ignore[assignment]

    produced = [f for f in context.findings if f.type == "profile_anomaly"]
    assert len(produced) == 1
    assert produced[0].severity == "low", "code cannot know what matters, so it says low"
    assert produced[0].engine == "code"
    assert "MORT_BAL" in produced[0].title
