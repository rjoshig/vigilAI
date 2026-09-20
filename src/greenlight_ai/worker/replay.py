"""Replaying a candidate rule against work already finished (Phase 6.13e).

Before an administrator approves a rule drafted from what reviewers wrote, they are
shown what it would have done. That claim used to be a substring count: it looked for
the rule's field name in the titles of recent findings, which said nothing at all about
a check or a compliance rule, and called the result "runs examined".

This evaluates the candidate for real. The stored report files of recent finalized runs
are parsed again, with the same masking every run uses, and the captured configuration is
read back; then the evaluator that would run the rule in the pipeline runs it here. No
model is called and nothing is written to a run: replay reads.

It is honest about what it cannot know. A rule that fires on a run says only that it
would have produced a finding, not that the finding would have been right, and the
dismissal count beside it is an estimate drawn from findings reviewers already judged
about the same field. Both are labelled where they are shown.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

import sqlalchemy as sa
from sqlalchemy.orm import Session

from greenlight_ai.checks import expressions
from greenlight_ai.checks.field_constraints import FieldConstraintSpec
from greenlight_ai.checks.field_constraints import evaluate as evaluate_constraints
from greenlight_ai.checks.named_values import NamedValue, resolve_all
from greenlight_ai.db import models, repository
from greenlight_ai.parsers.base import ConfigDocument, ReportDocument
from greenlight_ai.parsers.config_json import JsonConfigParser
from greenlight_ai.parsers.masking import DEFAULT_MASKED_COLUMNS
from greenlight_ai.parsers.reports.xlsx import parser_for
from greenlight_ai.training.synthesis import constraint_value

__all__ = ["REPLAY_NOTE", "replay_candidate"]

_LOG: Final = logging.getLogger(__name__)

#: File kinds that are not reports, so the replay does not try a workbook parser on them.
_NON_REPORT_KINDS: Final[frozenset[str]] = frozenset({"osl", "config"})

#: How many run titles to carry back, so the console can name what it would have found.
_MAX_EXAMPLES: Final[int] = 5

#: Said on every replay, because what it measures has a boundary and the console says so.
REPLAY_NOTE: Final[str] = (
    "Each run's stored reports were parsed again and the rule evaluated against them. "
    "Firing means it would have raised a finding, not that the finding would have been "
    "right. The dismissal count is an estimate from findings reviewers already judged "
    "about the same field."
)


def _reports(run: models.Run, data_dir: Path, masked: Sequence[str]) -> dict[str, ReportDocument]:
    """Parse the first stored part of each report kind on a run."""
    out: dict[str, ReportDocument] = {}
    for file in sorted(run.files, key=lambda f: (f.kind, f.part, f.id)):
        if file.kind in _NON_REPORT_KINDS or file.kind in out:
            continue
        path = data_dir / file.storage_key
        if not path.exists():
            continue
        try:
            out[file.kind] = parser_for(file.kind).parse(path, masked)
        except (KeyError, OSError, ValueError) as exc:
            _LOG.info("replay: run %s report %s unreadable (%s)", run.id, file.kind, type(exc))
    return out


def _config(session: Session, run: models.Run, data_dir: Path) -> ConfigDocument | None:
    """The configuration the run carried: its own file, else the captured version."""
    for file in run.files:
        if file.kind == "config":
            path = data_dir / file.storage_key
            if path.exists():
                try:
                    return JsonConfigParser().parse(path)
                except (OSError, ValueError) as exc:
                    _LOG.info("replay: run %s config unreadable (%s)", run.id, type(exc))
            break

    captured = session.execute(
        sa.select(models.Config)
        .where(models.Config.configuration_id == run.configuration_id)
        .order_by(models.Config.version.desc())
        .limit(1)
    ).scalar_one_or_none()
    if captured is None:
        return None
    try:
        return JsonConfigParser().parse_mapping(dict(captured.content or {}))
    except Exception as exc:  # pragma: no cover - a stored config that no longer parses
        _LOG.info("replay: captured config for %s unreadable (%s)", run.configuration_id, type(exc))
        return None


def _constraint_fires(
    body: Mapping[str, Any],
    reports: Mapping[str, ReportDocument],
    aliases: Any,
) -> tuple[bool, str]:
    """Evaluate a drafted field constraint the way stage 7 would."""
    spec = FieldConstraintSpec(
        id=0,
        field=str(body.get("field", "")),
        constraint=str(body.get("constraint", "")),
        value=constraint_value(body),
        report_kinds=tuple(str(kind) for kind in (body.get("report_kinds") or ())),
        severity=str(body.get("severity", "medium")),
    )
    if not spec.field or not spec.constraint:
        return False, ""
    for outcome in evaluate_constraints([spec], reports, aliases):
        if outcome.passed is False:
            return True, outcome.detail
    return False, ""


def _check_fires(
    body: Mapping[str, Any],
    named_values: Sequence[NamedValue],
    reports: Mapping[str, ReportDocument],
    config: ConfigDocument | None,
) -> tuple[bool, str]:
    """Evaluate a drafted check the way stage 7 would, with code doing the comparing."""
    expression = str(body.get("expression", "")).strip()
    if not expression:
        return False, ""
    values = resolve_all(named_values, reports, config)
    try:
        result = expressions.evaluate(expression, values)
    except (expressions.ExpressionError, expressions.UnresolvedValue):
        # A value this run's reports do not carry is not a failure; it is a run the
        # rule says nothing about, and counting it as firing would overstate the rule.
        return False, ""
    if result.passed:
        return False, ""
    shown = ", ".join(f"{name} = {value}" for name, value in sorted(result.resolved.items()))
    return True, f"{expression} did not hold ({shown})"


def _compliance_fires(body: Mapping[str, Any], config: ConfigDocument | None) -> tuple[bool, str]:
    """A compliance rule fires when no configuration path contains its fragment."""
    fragment = str(body.get("json_path_contains", "")).strip()
    if not fragment or config is None:
        return False, ""
    if any(fragment in block.json_path for block in config.blocks):
        return False, ""
    return True, f"No configuration path contains {fragment!r}."


def replay_candidate(
    session: Session,
    candidate: models.RuleCandidate,
    data_dir: Path,
    limit: int = 5,
) -> dict[str, Any]:
    """Evaluate a candidate against the last finalized runs (Phase 6.13e).

    Args:
        session: An open session.
        candidate: The candidate to replay.
        data_dir: The shared volume, where the stored files live.
        limit: How many finalized runs to examine, newest first.

    Returns:
        What the console shows before approval: how many runs were examined, which of
        them the rule would have fired on, a few examples of what it would have said,
        an estimate of how many related findings reviewers dismissed, and a note saying
        what those numbers do and do not mean.
    """
    runs = list(
        session.execute(
            sa.select(models.Run)
            .where(models.Run.status == "finalized")
            .order_by(models.Run.created_at.desc())
            .limit(max(0, limit))
        ).scalars()
    )
    body = dict(candidate.body or {})
    kind = candidate.target_kind
    masked = repository.load_masked_columns(session) or DEFAULT_MASKED_COLUMNS
    aliases = repository.load_aliases(session)
    named_values = repository.load_admin_config(session).named_values if kind == "check" else ()

    fired_on: list[int] = []
    examples: list[str] = []
    unreadable = 0

    for run in runs:
        reports = _reports(run, data_dir, masked)
        config = _config(session, run, data_dir) if kind != "field_constraint" else None
        if kind == "field_constraint" and not reports:
            unreadable += 1
            continue
        if kind == "compliance_rule" and config is None:
            unreadable += 1
            continue

        if kind == "field_constraint":
            fires, detail = _constraint_fires(body, reports, aliases)
        elif kind == "check":
            fires, detail = _check_fires(
                body,
                [value for value in named_values if isinstance(value, NamedValue)],
                reports,
                config,
            )
        elif kind == "compliance_rule":
            fires, detail = _compliance_fires(body, config)
        else:
            fires, detail = False, ""

        if fires:
            fired_on.append(int(run.id))
            if detail and len(examples) < _MAX_EXAMPLES:
                examples.append(f"{run.order_number or run.id}: {detail}")

    return {
        "runs_examined": len(runs) - unreadable,
        "runs_available": len(runs),
        "unreadable": unreadable,
        "would_fire_on": fired_on,
        "examples": examples,
        "previously_dismissed": _dismissed_nearby(session, body, runs),
        "note": REPLAY_NOTE,
        "evaluated": True,
    }


def _dismissed_nearby(session: Session, body: Mapping[str, Any], runs: Sequence[models.Run]) -> int:
    """How many findings about the same field reviewers already called false positives.

    This is the one number replay cannot compute exactly: the candidate has produced no
    findings yet, so there is nothing to look up. Counting the findings a reviewer
    dismissed about the same attribute is the nearest honest signal, and it is labelled
    an estimate wherever it is shown.
    """
    field = str(body.get("field", "")).strip()
    if not field or not runs:
        return 0
    rows = session.execute(
        sa.select(models.Finding.title).where(
            models.Finding.run_id.in_([run.id for run in runs]),
            models.Finding.review_status == "false_positive",
        )
    ).scalars()
    return sum(1 for title in rows if field.lower() in (title or "").lower())
