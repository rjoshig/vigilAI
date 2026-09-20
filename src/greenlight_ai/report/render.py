"""Rendering the frozen one-page report.

The report is generated once from the reviewed findings, stored, and never regenerated
(ADR-005). That is why this module returns the HTML and its hash together: the hash is
what later proves the stored file is the one that was reviewed.

Everything it renders is already masked (ADR-003); nothing here can unmask a value
because nothing unmasked reaches it.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Sequence

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from greenlight_ai.db import models
from greenlight_ai.db.drift import Drift
from greenlight_ai.rules.schema import Rule

__all__ = ["RenderedReport", "render_report", "verdict_for", "environment"]

_LOG: Final = logging.getLogger(__name__)

#: Where the templates live.
TEMPLATE_DIR: Final[Path] = Path(__file__).parent / "templates"

#: The decision that means the delivery has a real problem.
_NOT_OK: Final[str] = "confirmed"

#: Decisions that mean a reviewer looked and accepted it.
_OK: Final[frozenset[str]] = frozenset({"false_positive", "accepted_risk"})


@dataclass(frozen=True, slots=True)
class RenderedReport:
    """The report and the hash that identifies it.

    Attributes:
        html: The self-contained document.
        sha256: Its hash, stored so a later read can prove the file is unchanged.
        verdict: ``"ok"`` or ``"not_ok"``.
    """

    html: str
    sha256: str
    verdict: str


def environment() -> Environment:
    """Build the Jinja environment.

    Returns:
        An environment with autoescaping on and undefined variables raising. A silently
        blank field in a frozen report is a defect nobody can fix afterwards, so a
        missing value must fail at render time instead.
    """
    return Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html"]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def verdict_for(findings: Sequence[models.Finding]) -> str:
    """Decide the report's verdict.

    Args:
        findings: The run's findings with their decisions.

    Returns:
        ``"not_ok"`` when any finding was confirmed as a real problem, otherwise
        ``"ok"``. An undecided finding cannot appear here: the gate (ADR-015) blocks
        finalizing until every high-severity one is decided.
    """
    return "not_ok" if any(f.review_status == _NOT_OK for f in findings) else "ok"


def _decision(review_status: str) -> str:
    """Map a stored decision onto what the report shows.

    The API records what is true about the finding; the report shows what it means for
    the order, which is the opposite word for a confirmed finding.

    Args:
        review_status: The stored decision.

    Returns:
        ``"ok"``, ``"not_ok"``, or ``""`` when undecided.
    """
    if review_status == _NOT_OK:
        return "not_ok"
    if review_status in _OK:
        return "ok"
    return ""


def _matrix_row(
    rule: Rule, trace: models.Trace | None, findings: Sequence[models.Finding]
) -> dict[str, Any]:
    """Build one traceability row.

    Args:
        rule: The requirement.
        trace: Its link to a config element, if any.
        findings: The findings that name this requirement.

    Returns:
        The row as the template renders it.
    """
    types = {f.type for f in findings}
    if trace is None or trace.element_id is None or trace.verdict == "not_related":
        status = "missing"
    elif trace.verdict == "contradicts" or types & {
        "value_mismatch",
        "operator_mismatch",
        "waterfall_order_mismatch",
        "report_violates_rule",
    }:
        status = "mismatch"
    elif "extra_rule_in_config" in types:
        status = "extra"
    elif trace.verdict == "partial" or findings:
        status = "partial"
    else:
        status = "match"

    decisions = {_decision(f.review_status) for f in findings}
    decision = "not_ok" if "not_ok" in decisions else ("ok" if "ok" in decisions else "")

    return {
        "rule_id": rule.rule_id,
        "req_type": rule.req_type,
        "osl": _describe(rule),
        "config": trace.element_id if trace and trace.element_id else "no matching config rule",
        "status": status,
        "decision": decision,
    }


def _describe(rule: Rule) -> str:
    """Render a rule's payload for the matrix.

    Args:
        rule: The requirement.

    Returns:
        A short description carrying field names and thresholds only (ADR-003).
    """
    if rule.values:
        return ", ".join(rule.values)
    if rule.steps:
        return " → ".join(rule.steps)
    if rule.quantity is not None:
        return f"{rule.quantity:g}"
    if rule.conditions:
        return " AND ".join(f"{c.field_name} {c.operator} {c.value}" for c in rule.conditions)
    return "—"


def _duration(stages: Sequence[models.RunStage]) -> str:
    """Render the pipeline duration.

    Args:
        stages: The run's stage records.

    Returns:
        A short human reading, e.g. ``"4m 12s"``.
    """
    total_ms = sum(stage.duration_ms for stage in stages)
    seconds = total_ms / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    return f"{int(seconds // 60)}m {int(seconds % 60):02d}s"


def render_report(
    run: models.Run,
    findings: Sequence[models.Finding],
    rules: Sequence[Rule],
    traces: Sequence[models.Trace],
    stages: Sequence[models.RunStage],
    calls: Sequence[models.LlmCall],
    generated_by: str = "",
    now: dt.datetime | None = None,
    drift: Drift | None = None,
    attestation: dict[str, Any] | None = None,
    mismatches: Sequence[Any] = (),
    submitted_by: str = "",
    reviewers: Sequence[str] = (),
) -> RenderedReport:
    """Render the frozen report.

    Args:
        run: The run row.
        findings: Its findings, with decisions.
        rules: Its canonical requirements.
        traces: Its requirement-to-element links.
        stages: Its per-stage records.
        calls: Its model-call records.
        generated_by: Who finalized it.
        now: The generation time; injectable so a test can assert a stable hash.
        drift: What changed since the previous finalized run (ADR-030).
        submitted_by: Who submitted the run. A report that is evidence of a review
            should say who asked for it and who reviewed it (Phase 6.2d), and the two
            are often not the same person.
        reviewers: Who decided the findings, each named once. Empty when nobody did,
            which the report says rather than implying a review that never happened.
        mismatches: Where the artifacts disagreed with the submission and somebody
            accepted it before the run started (ADR-041). Shown on the report because a
            reviewer signing the delivery should see that the question was waived.
        attestation: What the person confirmed when they froze it (Phase 6.11d): the
            coverage counts, the gaps they acknowledged, the shadow rules and
            definition versions in force, and the run's notices. A report that is
            evidence of a review should say what the reviewer was shown.

    Returns:
        The document and its hash.
    """
    trace_by_rule = {trace.rule_id: trace for trace in traces}
    findings_by_rule: dict[str, list[models.Finding]] = {}
    for finding in findings:
        if finding.rule_ref:
            findings_by_rule.setdefault(finding.rule_ref, []).append(finding)

    matrix = [
        _matrix_row(rule, trace_by_rule.get(rule.rule_id), findings_by_rule.get(rule.rule_id, []))
        for rule in rules
    ]
    not_ok = [f for f in findings if f.review_status == _NOT_OK]

    counts = {"high": 0, "medium": 0, "low": 0, "review": 0}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1

    evidence = [
        {
            "finding_id": finding.finding_id,
            "title": finding.title,
            **{
                key: (finding.evidence or {}).get(key, "")
                for key in (
                    "osl_ref",
                    "osl_text",
                    "config_path",
                    "config_value",
                    "report_name",
                    "report_sheet",
                    "report_cell",
                    "report_value",
                )
            },
        }
        for finding in not_ok
    ]

    generated = (now or dt.datetime.now(dt.timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")
    html = (
        environment()
        .get_template("report.html.j2")
        .render(
            run=run,
            findings=findings,
            not_ok=not_ok,
            rules=rules,
            matrix=matrix,
            matched=sum(1 for row in matrix if row["status"] == "match"),
            counts=counts,
            evidence=evidence,
            waterfall=[],
            top_issues=list(run.top_issues or []),
            verdict=verdict_for(findings),
            generated_at=generated,
            generated_by=generated_by,
            submitted_by=submitted_by,
            reviewers=list(reviewers),
            drift=drift,
            attestation=attestation or {},
            mismatches=list(mismatches),
            stats={
                "duration": _duration(stages),
                "calls": len(calls),
                "tokens": sum(c.prompt_tokens + c.completion_tokens for c in calls),
                "cache_hits": sum(1 for c in calls if c.cached),
            },
        )
    )

    digest = hashlib.sha256(html.encode("utf-8")).hexdigest()
    _LOG.info("rendered report for run %d (%d bytes, sha %s)", run.id, len(html), digest[:12])
    return RenderedReport(html=html, sha256=digest, verdict=verdict_for(findings))


def write_report(html: str, data_dir: Path, run_id: int) -> str:
    """Store the rendered report on the shared volume.

    Args:
        html: The document.
        data_dir: The shared volume.
        run_id: Which run it belongs to.

    Returns:
        The storage key, relative to the data directory.
    """
    target = data_dir / "reports" / f"run-{run_id}.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")
    return str(target.relative_to(data_dir))
