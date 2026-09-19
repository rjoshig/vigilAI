#!/usr/bin/env python3
"""Score the pipeline against the golden set.

The golden set is the accuracy benchmark for extraction and reconciliation: synthetic
OSLs whose correct answer is known, run whenever a prompt or the model changes
(``docs/llm-privacy.md``, ADR-003). Each case carries its own oracle in
``manifest.json``, so the expected answer travels with the fixture rather than living in
a second file that can drift.

Provider-agnostic by design (ADR-014): the default scripted stand-in needs no model, and
``--provider openai`` points the same harness at a real one to produce the numbers
Phase 6 needs.

Usage:
    python scripts/golden_set.py
    python scripts/golden_set.py --provider openai --out docs/benchmarks/phase-2.md
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from synthetic_model import FIXTURE_ALIASES, build_client  # noqa: E402

from greenlight_ai.llm.factory import build_cache, build_client as build_real_client  # noqa: E402
from greenlight_ai.llm.settings import LLMSettings  # noqa: E402
from greenlight_ai.pipeline.context import STAGE_ORDER, RunContext  # noqa: E402
from greenlight_ai.pipeline.run import PipelineError, run_pipeline  # noqa: E402

_LOG: Final = logging.getLogger("golden_set")


@dataclass(frozen=True, slots=True)
class CaseScore:
    """How the pipeline did on one case.

    Attributes:
        name: The case name.
        expected: Finding types the oracle requires.
        produced: Finding types the run produced.
        true_positives: Expected types that were produced.
        false_negatives: Expected types that were missed.
        false_positives: Serious types produced that the oracle does not expect.
        error: The failure message when the run did not complete.
    """

    name: str
    expected: frozenset[str]
    produced: frozenset[str]
    true_positives: frozenset[str]
    false_negatives: frozenset[str]
    false_positives: frozenset[str]
    error: str = ""

    @property
    def passed(self) -> bool:
        """Whether the case met its oracle exactly.

        Returns:
            ``True`` when nothing was missed, nothing spurious was raised, and the run
            completed.
        """
        return not self.false_negatives and not self.false_positives and not self.error


#: Finding types that are informational rather than assertions about the delivery. A
#: run may raise these without being wrong, so they are not counted as false positives.
ADVISORY_TYPES: Final[frozenset[str]] = frozenset(
    {"low_confidence_extraction", "could_not_evaluate", "profile_anomaly"}
)


def score_case(
    case: Mapping[str, object], root: Path, provider: str, cache: Path | None
) -> CaseScore:
    """Run one case and compare the result with its oracle.

    Args:
        case: The manifest entry.
        root: The fixtures root.
        provider: ``"synthetic"`` for the scripted stand-in, or a real provider name.
        cache: A SQLite cache file, shared across cases so repeated runs are cheap.

    Returns:
        The case's score.
    """
    name = str(case["name"])
    expected = frozenset(case["expected"]["findings"])  # type: ignore[index]

    if provider == "synthetic":
        client = build_client()
    else:
        settings = LLMSettings.from_env().model_copy(update={"provider": provider})
        client = build_real_client(settings, cache=build_cache(settings, cache))

    context = RunContext(
        run_id=f"golden-{name}",
        osl_path=root / str(case["osl"]),
        config_path=root / str(case["config"]),
        report_paths={
            kind: root / path  # type: ignore[misc]
            for kind, path in case["reports"].items()  # type: ignore[union-attr]
        },
        client=client,
        customer=str(case["customer"]),
        aliases=FIXTURE_ALIASES,
    )

    error = ""
    try:
        run_pipeline(context, stages=STAGE_ORDER)
    except PipelineError as exc:
        error = str(exc)

    produced = frozenset(f.type for f in context.findings)
    serious = (
        frozenset(f.type for f in context.findings if f.severity in ("high", "medium"))
        - ADVISORY_TYPES
    )

    return CaseScore(
        name=name,
        expected=expected,
        produced=produced,
        true_positives=expected & produced,
        false_negatives=expected - produced,
        false_positives=serious - expected,
        error=error,
    )


def score_all(
    manifest: Mapping[str, object], root: Path, provider: str, cache: Path | None
) -> list[CaseScore]:
    """Run every case.

    Args:
        manifest: The decoded manifest.
        root: The fixtures root.
        provider: Which provider to use.
        cache: A shared SQLite cache file.

    Returns:
        One score per case, in manifest order.
    """
    return [
        score_case(case, root, provider, cache)
        for case in manifest["cases"]  # type: ignore[union-attr]
    ]


def per_type(scores: Sequence[CaseScore]) -> dict[str, dict[str, int]]:
    """Aggregate true positives, misses, and spurious findings per finding type.

    Args:
        scores: The case scores.

    Returns:
        Finding type to its counts.
    """
    totals: dict[str, dict[str, int]] = defaultdict(
        lambda: {"expected": 0, "found": 0, "missed": 0, "spurious": 0}
    )
    for score in scores:
        for kind in score.expected:
            totals[kind]["expected"] += 1
        for kind in score.true_positives:
            totals[kind]["found"] += 1
        for kind in score.false_negatives:
            totals[kind]["missed"] += 1
        for kind in score.false_positives:
            totals[kind]["spurious"] += 1
    return dict(totals)


def _ratio(numerator: int, denominator: int) -> str:
    """Format a ratio as a percentage, or a dash when undefined.

    Args:
        numerator: The top.
        denominator: The bottom.

    Returns:
        A percentage string, or ``"—"`` when there is nothing to divide by.
    """
    return "—" if denominator == 0 else f"{numerator / denominator:.0%}"


def render(scores: Sequence[CaseScore], provider: str, model: str) -> str:
    """Render the report.

    Args:
        scores: The case scores.
        provider: Which provider produced them.
        model: Which model, for the record.

    Returns:
        A Markdown report suitable for ``docs/benchmarks/``.
    """
    passed = sum(1 for s in scores if s.passed)
    found = sum(len(s.true_positives) for s in scores)
    expected = sum(len(s.expected) for s in scores)
    spurious = sum(len(s.false_positives) for s in scores)

    lines = [
        "# Golden set results",
        "",
        f"- Provider: `{provider}` · model: `{model}`",
        f"- Cases: **{passed} / {len(scores)}** met their oracle exactly",
        f"- Recall: **{_ratio(found, expected)}** ({found} of {expected} expected findings)",
        f"- Precision: **{_ratio(found, found + spurious)}** ({spurious} spurious)",
        "",
        "## Per finding type",
        "",
        "| Finding type | Expected | Found | Missed | Spurious | Recall |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for kind, counts in sorted(per_type(scores).items()):
        lines.append(
            f"| {kind} | {counts['expected']} | {counts['found']} | {counts['missed']} "
            f"| {counts['spurious']} | {_ratio(counts['found'], counts['expected'])} |"
        )

    lines += [
        "",
        "## Per case",
        "",
        "| Case | Result | Missed | Spurious |",
        "| --- | --- | --- | --- |",
    ]
    for score in scores:
        result = "pass" if score.passed else ("error" if score.error else "fail")
        lines.append(
            f"| {score.name} | {result} | {', '.join(sorted(score.false_negatives)) or '—'} "
            f"| {', '.join(sorted(score.false_positives)) or '—'} |"
        )

    failures = [s for s in scores if s.error]
    if failures:
        lines += ["", "## Runs that did not complete", ""]
        lines += [f"- `{s.name}`: {s.error}" for s in failures]

    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Command-line arguments.

    Returns:
        ``0`` when every case met its oracle, ``1`` otherwise, so CI can gate on it.
    """
    parser = argparse.ArgumentParser(description="Score the pipeline against the golden set.")
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=None,
        help="An existing fixtures root. Generated into a temporary directory when omitted.",
    )
    parser.add_argument(
        "--provider",
        default="synthetic",
        help=(
            "'synthetic' (default) uses the scripted stand-in and needs no model. "
            "'openai' or 'anthropic' uses the configured endpoint."
        ),
    )
    parser.add_argument("--cache", type=Path, default=None, help="A SQLite stage cache to reuse.")
    parser.add_argument("--out", type=Path, default=None, help="Write the report here.")
    parser.add_argument(
        "--log-level", default="WARNING", choices=("DEBUG", "INFO", "WARNING", "ERROR")
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level, format="%(levelname)s %(name)s: %(message)s")

    with tempfile.TemporaryDirectory() as temporary:
        root = args.fixtures
        if root is None:
            root = Path(temporary)
            subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).parent / "generate_fixtures.py"),
                    "--out",
                    str(root),
                    "--log-level",
                    "ERROR",
                ],
                check=True,
            )
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        scores = score_all(manifest, root, args.provider, args.cache)

    model = "n/a" if args.provider == "synthetic" else LLMSettings.from_env().model
    report = render(scores, args.provider, model)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
        _LOG.warning("wrote %s", args.out)
    else:
        print(report, end="")

    return 0 if all(s.passed for s in scores) else 1


if __name__ == "__main__":
    sys.exit(main())
