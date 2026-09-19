"""The command-line entry point.

``vigilai run`` takes the three inputs and writes findings JSON. It is the first entry
point (Phase 2) and stays usable after the API lands, because the golden set and any
in-house spot check run through it rather than through the web app.

Example:
    vigilai run --osl osl.docx --config config.json \\
        --report dirt=dirt.xlsx --report counts=counts.xlsx --out findings.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Final, Mapping, Sequence

from vigilai.llm.client import LLMClient
from vigilai.llm.factory import build_cache, build_client
from vigilai.llm.settings import ConfigError, LLMSettings
from vigilai.parsers.base import ParseError, ReportKind
from vigilai.parsers.reports.xlsx import PARSERS
from vigilai.pipeline.context import STAGE_ORDER, RunContext
from vigilai.pipeline.run import PipelineError, run_pipeline
from vigilai.rules.normalize import AliasTable

__all__ = ["main", "run_command", "build_parser"]

_LOG: Final = logging.getLogger("vigilai")

#: Exit codes. A run that completes but finds problems is a success: the tool did its
#: job. Only a failure to *run* is a non-zero exit, so a wrapper script can tell "the
#: delivery is wrong" from "the check did not happen".
EXIT_OK: Final[int] = 0
EXIT_USAGE: Final[int] = 2
EXIT_FAILED: Final[int] = 3


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser.

    Returns:
        The parser, with one subcommand.
    """
    parser = argparse.ArgumentParser(
        prog="vigilai",
        description=(
            "QC validation for a credit-data fulfillment process: reconcile the OSL "
            "requirement spec, the ETL config, and the output reports."
        ),
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    run = subcommands.add_parser(
        "run",
        help="Run the pipeline over one set of inputs and write findings JSON.",
        description="Run the nine-stage pipeline and write findings JSON.",
    )
    run.add_argument("--osl", type=Path, required=True, help="The OSL requirement spec (.docx).")
    run.add_argument("--config", type=Path, required=True, help="The ETL configuration (.json).")
    run.add_argument(
        "--report",
        action="append",
        default=[],
        metavar="KIND=PATH",
        help=("An output report, repeatable. KIND is one of: " + ", ".join(sorted(PARSERS)) + "."),
    )
    run.add_argument(
        "--out",
        type=Path,
        default=Path("findings.json"),
        help="Where to write the findings JSON (default: findings.json).",
    )
    run.add_argument("--run-id", default="cli-run", help="Identifier recorded on the run.")
    run.add_argument("--customer", default="", help="Customer name, used to scope admin checks.")
    run.add_argument(
        "--provider",
        choices=("mock", "openai", "anthropic"),
        default=None,
        help="Override LLM_PROVIDER for this run.",
    )
    run.add_argument(
        "--cache",
        type=Path,
        default=None,
        help=(
            "A SQLite file for the stage cache, so repeated runs reuse earlier work. "
            "Without it the cache lives in memory for the run only."
        ),
    )
    run.add_argument(
        "--stage",
        action="append",
        choices=list(STAGE_ORDER),
        default=None,
        help="Run only these stages, in order. Repeatable. Default: all nine.",
    )
    run.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Logging verbosity (default: INFO).",
    )
    return parser


def _parse_reports(pairs: Sequence[str]) -> dict[ReportKind, Path]:
    """Turn ``KIND=PATH`` arguments into a mapping.

    Args:
        pairs: The raw ``--report`` values.

    Returns:
        Report kind to path.

    Raises:
        ValueError: When a pair is malformed or names an unknown report kind. Naming the
            valid kinds in the message saves a trip to the docs.
    """
    reports: dict[ReportKind, Path] = {}
    for pair in pairs:
        kind, separator, path = pair.partition("=")
        if not separator or not path:
            raise ValueError(f"--report expects KIND=PATH, got {pair!r}")
        kind = kind.strip().lower()
        if kind not in PARSERS:
            raise ValueError(
                f"unknown report kind {kind!r}; valid kinds are {', '.join(sorted(PARSERS))}"
            )
        reports[kind] = Path(path)
    return reports


def run_command(
    args: argparse.Namespace,
    client: LLMClient | None = None,
    aliases: AliasTable | None = None,
) -> int:
    """Execute the ``run`` subcommand.

    Args:
        args: Parsed arguments.
        client: An LLM client to use instead of the one the environment configures. The
            golden set injects a scripted stand-in through this seam.
        aliases: The attribute alias table. Phase 3 loads it from the database.

    Returns:
        A process exit code.
    """
    try:
        reports = _parse_reports(args.report)
    except ValueError as exc:
        _LOG.error("%s", exc)
        return EXIT_USAGE

    if not reports:
        _LOG.error("at least one --report is required")
        return EXIT_USAGE

    if client is None:
        try:
            settings = LLMSettings.from_env()
            if args.provider:
                settings = settings.model_copy(update={"provider": args.provider})
            client = build_client(settings, cache=build_cache(settings, args.cache))
        except ConfigError as exc:
            _LOG.error("configuration problem: %s", exc)
            return EXIT_USAGE

    context = RunContext(
        run_id=args.run_id,
        osl_path=args.osl,
        config_path=args.config,
        report_paths=reports,
        client=client,
        customer=args.customer,
        aliases=aliases or AliasTable.from_mapping({}),
    )

    stages = tuple(args.stage) if args.stage else STAGE_ORDER
    try:
        run_pipeline(context, stages=stages)
    except (PipelineError, ParseError) as exc:
        _LOG.error("run %s failed: %s", args.run_id, exc)
        _write(args.out, context, failed=str(exc))
        return EXIT_FAILED

    _write(args.out, context)
    _LOG.info(
        "run %s: %d findings (%d high) written to %s",
        args.run_id,
        len(context.findings),
        len(context.high_severity_findings),
        args.out,
    )
    return EXIT_OK


def _write(path: Path, context: RunContext, failed: str = "") -> None:
    """Write the findings document.

    A failed run still writes its document, carrying the stages that did complete and
    the error, so a wrapper can see how far the run got.

    Args:
        path: Where to write.
        context: The run context.
        failed: The failure message, when the run did not complete.
    """
    document: dict[str, object] = {
        "run_id": context.run_id,
        "customer": context.customer,
        "osl": str(context.osl_path),
        "config": str(context.config_path),
        "reports": {kind: str(p) for kind, p in context.report_paths.items()},
        "rules_version": context.rules_version,
        "summary": context.summary,
        "top_issues": list(context.top_issues),
        "can_finalize": context.can_finalize,
        "counts": _counts(context),
        "stages": [
            {
                "stage": record.stage,
                "status": record.status,
                "duration_ms": record.duration_ms,
                "llm_calls": record.llm_calls,
                "cache_hits": record.cache_hits,
                "tokens": record.tokens,
                "error": record.error,
            }
            for record in context.stages.values()
        ],
        "findings": [finding.model_dump(mode="json") for finding in context.findings],
    }
    if failed:
        document["failed"] = failed

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def _counts(context: RunContext) -> Mapping[str, int]:
    """Summarise the findings by severity.

    Args:
        context: The run context.

    Returns:
        Severity to count, plus the totals a caller usually wants.
    """
    counts = {"high": 0, "medium": 0, "low": 0, "review": 0}
    for finding in context.findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
    counts["total"] = len(context.findings)
    counts["rules"] = len(context.rules)
    counts["config_elements"] = len(context.elements)
    return counts


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Command-line arguments, defaulting to ``sys.argv[1:]``.

    Returns:
        A process exit code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=args.log_level,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if args.command == "run":
        return run_command(args)
    parser.error(f"unknown command {args.command!r}")
    return EXIT_USAGE  # pragma: no cover - argparse exits first


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
