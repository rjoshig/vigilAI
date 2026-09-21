#!/usr/bin/env python3
"""Measure the anomaly check before anybody trusts it (Phase 6.21c).

An anomaly detector nobody measured is a false-positive generator, and the failure
mode is not a wrong finding — it is a reviewer learning that the whole category is
noise and skipping it from then on. So this scores the check the way Phase 6.11's
harness scores the pipeline: generate deliveries whose answer is known, run the check
over them, and report precision and recall.

**What is synthetic here, and what that costs.** The histories are drawn from a normal
distribution around a fixed level, and the planted shifts are step changes. Real
deliveries drift, have seasons, and change when a customer changes their file — none
of which this simulates. So the numbers below bound the arithmetic, not the product:
they say the method does what it claims on data that behaves, and Phase 7 says whether
real deliveries behave. That is the same position `phase-7.1.md` takes on the
demotion bar, and for the same reason.

Usage:
    python scripts/anomaly_benchmark.py
    python scripts/anomaly_benchmark.py --out docs/benchmarks/phase-6.21-anomaly.md
"""

from __future__ import annotations

import argparse
import logging
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from greenlight_ai.checks import anomaly  # noqa: E402
from greenlight_ai.checks.profile import AttributeProfile  # noqa: E402

__all__ = ["Scenario", "Score", "main", "score_all"]

_LOG: Final = logging.getLogger("anomaly_benchmark")

#: How many deliveries each scenario is run over. Enough that one lucky draw does not
#: move a rate by more than a point.
TRIALS: Final[int] = 400

#: How much history each simulated delivery has behind it.
HISTORY: Final[int] = 8

#: The seed, so the table in the docs is the table anybody regenerating it gets.
SEED: Final[int] = 20_260_921


@dataclass(frozen=True, slots=True)
class Scenario:
    """One kind of delivery, and whether the check should fire on it.

    Attributes:
        name: What it is, for the table.
        level: The measure's usual value.
        noise: How much it moves between ordinary deliveries, as a standard deviation.
        shift: What this delivery reports instead, as a multiple of the level. ``1.0``
            is an ordinary delivery.
        anomalous: Whether the check is supposed to fire.
        detail: The sentence in the table's last column.
    """

    name: str
    level: float
    noise: float
    shift: float
    anomalous: bool
    detail: str


#: The cases worth measuring. Half are ordinary deliveries, because a detector's
#: precision is decided by how often it stays quiet, and a suite of only anomalies
#: would report a perfect score for a check that fires on everything.
SCENARIOS: Final[tuple[Scenario, ...]] = (
    Scenario(
        "ordinary · steady",
        level=0.04,
        noise=0.002,
        shift=1.0,
        anomalous=False,
        detail="A null rate that sits where it always sits.",
    ),
    Scenario(
        "ordinary · noisy",
        level=0.04,
        noise=0.010,
        shift=1.0,
        anomalous=False,
        detail="The same, on a measure that moves a lot between deliveries.",
    ),
    Scenario(
        "ordinary · a nudge, steady",
        level=0.04,
        noise=0.002,
        shift=1.1,
        anomalous=False,
        detail="Up a tenth on a measure that varies by a twentieth. Within reach.",
    ),
    Scenario(
        "ordinary · a nudge, noisy",
        level=0.04,
        noise=0.010,
        shift=1.4,
        anomalous=False,
        detail="Up by 40% on a measure that already wanders by a quarter.",
    ),
    Scenario(
        "anomaly · four times",
        level=0.04,
        noise=0.002,
        shift=4.5,
        anomalous=True,
        detail="The design doc's own example: 4% becoming 18%.",
    ),
    Scenario(
        "anomaly · ten times",
        level=0.04,
        noise=0.002,
        shift=10.0,
        anomalous=True,
        detail="A field that has quietly stopped being populated.",
    ),
    Scenario(
        "anomaly · collapse",
        level=0.04,
        noise=0.002,
        shift=0.0,
        anomalous=True,
        detail="A rate that goes to zero, which is as odd as one that spikes.",
    ),
    Scenario(
        "anomaly · four times, noisy",
        level=0.04,
        noise=0.010,
        shift=4.5,
        anomalous=True,
        detail="The hard case: a real shift on a measure that already wanders.",
    ),
)


@dataclass
class Score:
    """What one scenario scored.

    Attributes:
        scenario: The case.
        fired: How many of its trials produced a finding.
        trials: How many were run.
    """

    scenario: Scenario
    fired: int = 0
    trials: int = 0

    @property
    def rate(self) -> float:
        """The share of trials that produced a finding."""
        return self.fired / self.trials if self.trials else 0.0

    @property
    def correct(self) -> int:
        """Trials the check got right."""
        return self.fired if self.scenario.anomalous else self.trials - self.fired


def _delivery(value: float) -> dict[str, AttributeProfile]:
    """One delivery's profile, as one attribute's null rate."""
    return {"mort_bal": AttributeProfile(name="MORT_BAL", null_rate=max(value, 0.0))}


def run(scenario: Scenario, rng: random.Random, trials: int = TRIALS) -> Score:
    """Run one scenario.

    Args:
        scenario: The case to run.
        rng: The random source, seeded by the caller so the table reproduces.
        trials: How many deliveries to simulate.

    Returns:
        Its score.
    """
    score = Score(scenario=scenario, trials=trials)
    for _ in range(trials):
        history = [_delivery(rng.gauss(scenario.level, scenario.noise)) for _ in range(HISTORY)]
        current = _delivery(
            scenario.level * scenario.shift
            if scenario.shift != 1.0
            else rng.gauss(scenario.level, scenario.noise)
        )
        if anomaly.compare(current, history):
            score.fired += 1
    return score


def score_all(trials: int = TRIALS, seed: int = SEED) -> list[Score]:
    """Run every scenario.

    Args:
        trials: How many deliveries per scenario.
        seed: The random seed.

    Returns:
        The scores, in scenario order.
    """
    rng = random.Random(seed)
    return [run(scenario, rng, trials) for scenario in SCENARIOS]


def _rates(scores: Sequence[Score]) -> tuple[float, float]:
    """Precision and recall across every scenario.

    Args:
        scores: What each scenario scored.

    Returns:
        ``(precision, recall)``. Precision is the share of findings that were real;
        recall the share of real anomalies that produced one.
    """
    true_positive = sum(s.fired for s in scores if s.scenario.anomalous)
    false_positive = sum(s.fired for s in scores if not s.scenario.anomalous)
    false_negative = sum(s.trials - s.fired for s in scores if s.scenario.anomalous)
    precision = true_positive / (true_positive + false_positive) if true_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive else 0.0
    return precision, recall


def report(scores: Sequence[Score]) -> str:
    """Render the results as the markdown that goes in `docs/benchmarks/`.

    Args:
        scores: What each scenario scored.

    Returns:
        The document.
    """
    precision, recall = _rates(scores)
    lines = [
        "# Anomaly check — synthetic benchmark",
        "",
        f"Produced by `scripts/anomaly_benchmark.py` · {TRIALS} deliveries per scenario · "
        f"{HISTORY} deliveries of history each · seed {SEED}.",
        "",
        "The check compares a delivery against the median and median absolute deviation "
        "of the previous finalized deliveries of the same configuration "
        "(`checks/anomaly.py`). No model is involved.",
        "",
        f"**Precision {precision:.1%} · recall {recall:.1%}**, at the shipped sensitivity "
        f"of {anomaly.SENSITIVITY:g} and a minimum history of {anomaly.MIN_HISTORY}.",
        "",
        "| Scenario | Should fire | Did fire | What it is |",
        "| --- | --- | --- | --- |",
    ]
    for score in scores:
        lines.append(
            f"| {score.scenario.name} | {'yes' if score.scenario.anomalous else 'no'} "
            f"| {score.rate:.1%} | {score.scenario.detail} |"
        )
    lines += [
        "",
        "## What these numbers are, and are not",
        "",
        "The histories are drawn from a normal distribution around a fixed level and the "
        "shifts are step changes. Real deliveries drift, have seasons, and change when a "
        "customer changes their file — none of which this simulates. **These numbers "
        "bound the arithmetic, not the product.** They say the method does what it claims "
        "on data that behaves; whether real deliveries behave is a Phase 7 question, and "
        "the sensitivity is a console setting for exactly that reason.",
        "",
        "## What building it taught",
        "",
        "The first version of this table had a scenario asserting that a null rate up by "
        "40% should *not* fire. It fired every time, and the benchmark was right: on a "
        "measure that has sat at 4.0% ± 0.2% for eight deliveries, 5.6% is eight "
        "deviations out and something has changed. The assumption was wrong, not the "
        "check. What counts as a nudge is relative to how much that measure normally "
        "moves — which is the entire reason this compares against a spread rather than "
        "against a fixed percentage, and it is worth stating because it reads as "
        "counterintuitive until you do the arithmetic.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    """Run the benchmark.

    Args:
        argv: Command-line arguments.

    Returns:
        ``0``.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="write the report here instead of stdout")
    parser.add_argument("--trials", type=int, default=TRIALS)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument(
        "--log-level", default="WARNING", choices=["DEBUG", "INFO", "WARNING", "ERROR"]
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level, format="%(levelname)s %(name)s: %(message)s")

    scores = score_all(args.trials, args.seed)
    document = report(scores)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(document, encoding="utf-8")
        _LOG.warning("wrote %s", args.out)
    else:
        print(document, end="")

    precision, recall = _rates(scores)
    _LOG.info("precision %.3f recall %.3f", precision, recall)
    return 0


if __name__ == "__main__":  # pragma: no cover - a script entry point
    raise SystemExit(main())
