"""Turning observations into candidate rules, and candidates into rules (ADR-021).

The model proposes; code disposes. Everything it returns is validated here before an
administrator sees it, fingerprinted against the rules that already exist, and
replayed against known cases. Approval is the only step that creates something the
pipeline will run, and a person takes it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final, Sequence

import sqlalchemy as sa
from sqlalchemy.orm import Session

from vigilai.checks.field_constraints import CONSTRAINT_KINDS
from vigilai.db import models
from vigilai.llm.client import LLMClient, LLMResponseError
from vigilai.llm.prompts.synthesize import SYNTHESIZE_PROMPT
from vigilai.llm.prompts.schemas import SynthesisResponse, SynthesizedRule
from vigilai.training.lifecycle import set_state

__all__ = [
    "SynthesisError",
    "ValidationProblem",
    "synthesize",
    "validate_rule",
    "fingerprint_rule",
    "find_conflicts",
    "approve",
]

_LOG: Final = logging.getLogger(__name__)

#: How many statements go into one call. More than this and the model starts merging
#: expectations that only look alike, and the administrator cannot tell which
#: observation produced which rule.
MAX_STATEMENTS: Final[int] = 12


class SynthesisError(Exception):
    """Synthesis could not produce anything usable, with the reason in its message."""


@dataclass(frozen=True, slots=True)
class ValidationProblem:
    """Why a drafted rule was rejected before anyone saw it.

    Attributes:
        rule_name: What the model called it.
        reason: What is wrong, in a sentence an administrator can act on.
    """

    rule_name: str
    reason: str


def validate_rule(rule: SynthesizedRule, known_fields: Sequence[str]) -> str:
    """Check a drafted rule against what the engine can actually run.

    A malformed or out-of-scope candidate is rejected outright rather than shown,
    because any parse-level trust of free-form model output is where an injection
    becomes an effect.

    Args:
        rule: What the model returned.
        known_fields: Attribute names the tool knows, so an invented one is caught.

    Returns:
        An empty string when the rule is usable, otherwise the reason it is not.
    """
    if rule.target_kind == "unsupported":
        return rule.cannot_express or "the model could not express this as a rule"
    if not rule.name.strip():
        return "the rule has no name"

    if rule.target_kind == "field_constraint":
        if not rule.field.strip():
            return "a field constraint must name a field"
        if rule.constraint not in CONSTRAINT_KINDS:
            return f"{rule.constraint!r} is not a constraint this version can check"
        if known_fields and rule.field not in known_fields:
            return (
                f"{rule.field!r} is not an attribute the tool knows; add an alias for "
                "it first rather than letting a rule invent one"
            )
        if rule.constraint in ("allowed_values", "forbidden_values") and not rule.values:
            return f"{rule.constraint} needs at least one value"
        if rule.constraint == "range" and rule.minimum is None and rule.maximum is None:
            return "a range needs a minimum, a maximum, or both"
        if rule.constraint == "format" and not rule.pattern.strip():
            return "a format constraint needs a pattern"
        if rule.constraint == "fill_rate_min" and rule.minimum is None:
            return "a fill rate needs a minimum percentage"
        return ""

    if rule.target_kind == "check":
        if not rule.expression.strip():
            return "a check needs an expression"
        return ""

    if rule.target_kind == "compliance_rule":
        if not rule.reasoning.strip():
            return "a compliance rule needs its reasoning, which is what a reviewer reads"
        return ""

    return f"{rule.target_kind!r} is not a rule kind"


def _body(rule: SynthesizedRule) -> dict[str, Any]:
    """The structured rule, shaped by its target kind.

    Args:
        rule: The drafted rule.

    Returns:
        What approval will write into the rule table.
    """
    if rule.target_kind == "field_constraint":
        value: Any
        if rule.constraint in ("allowed_values", "forbidden_values"):
            value = list(rule.values)
        elif rule.constraint == "range":
            value = {"min": rule.minimum, "max": rule.maximum}
        elif rule.constraint == "format":
            value = rule.pattern
        elif rule.constraint == "fill_rate_min":
            value = rule.minimum
        else:
            value = {}
        return {
            "field": rule.field,
            "constraint": rule.constraint,
            "value": value,
            "report_kinds": list(rule.report_kinds),
        }
    if rule.target_kind == "check":
        return {"expression": rule.expression}
    return {"reasoning": rule.reasoning}


def fingerprint_rule(target_kind: str, body: dict[str, Any], scope: str) -> str:
    """A stable identity for "this rule already exists".

    Args:
        target_kind: Which rule surface.
        body: The structured rule.
        scope: Who it applies to.

    Returns:
        A string that two rules share when they say the same thing about the same
        thing. Overlap is found on (scope, assertion type, parameters), which is what
        every comparable tool uses, and it has to run at creation: overlapping rules
        accumulate silently and are very hard to untangle afterwards.
    """
    if target_kind == "field_constraint":
        key = f"{body.get('field', '')}|{body.get('constraint', '')}"
    elif target_kind == "check":
        key = " ".join(str(body.get("expression", "")).split())
    else:
        key = str(body.get("reasoning", ""))[:100]
    return f"{target_kind}|{scope}|{key}".lower()


def find_conflicts(
    session: Session, target_kind: str, body: dict[str, Any], scope: str
) -> list[dict[str, Any]]:
    """Existing rules that overlap a candidate.

    Args:
        session: An open session.
        target_kind: Which rule surface.
        body: The structured rule.
        scope: Who it applies to.

    Returns:
        One entry per overlap, naming the rule and what it says. A contradiction is
        caught the same way: one rule permitting a blank while another forbids it is
        an overlap with opposite verdicts, and the administrator decides which wins.
    """
    wanted = fingerprint_rule(target_kind, body, scope)
    conflicts: list[dict[str, Any]] = []

    if target_kind == "field_constraint":
        rows = session.execute(
            sa.select(models.FieldConstraint).where(
                models.FieldConstraint.state != "deleted",
                models.FieldConstraint.field == body.get("field", ""),
            )
        ).scalars()
        for row in rows:
            existing = fingerprint_rule(
                "field_constraint",
                {"field": row.field, "constraint": row.constraint},
                row.scope,
            )
            if existing == wanted or row.constraint == body.get("constraint"):
                conflicts.append(
                    {
                        "rule_kind": "field_constraint",
                        "id": row.id,
                        "summary": f"{row.field} {row.constraint}",
                        "scope": row.scope,
                        "state": row.state,
                        "same": existing == wanted,
                    }
                )
    elif target_kind == "check":
        checks = session.execute(
            sa.select(models.CheckDefinitionRow).where(models.CheckDefinitionRow.state != "deleted")
        ).scalars()
        for check in checks:
            existing = fingerprint_rule("check", {"expression": check.expression}, check.scope)
            if existing == wanted:
                conflicts.append(
                    {
                        "rule_kind": "check",
                        "id": check.id,
                        "summary": check.expression,
                        "scope": check.scope,
                        "state": check.state,
                        "same": True,
                    }
                )
    return conflicts


def synthesize(
    session: Session,
    client: LLMClient,
    observations: Sequence[models.TrainingObservation],
    *,
    known_fields: Sequence[str] = (),
    report_kinds: Sequence[str] = (),
    actor: str = "",
    user_id: int | None = None,
) -> list[models.RuleCandidate]:
    """Draft candidate rules from a group of observations.

    Args:
        session: An open session.
        client: The model adapter.
        observations: What people wrote. Their text reaches the prompt inside a
            delimited block, marked as data to interpret rather than instructions to
            follow.
        known_fields: Attribute names the tool knows, so an invented one is caught.
        report_kinds: The report types that exist.
        actor: Who asked for the synthesis.
        user_id: Their account id.

    Returns:
        The stored candidates, each already validated and fingerprinted for overlap.
        A statement the model could not express becomes a rejected candidate carrying
        the reason, not silence.

    Raises:
        SynthesisError: When no observations were given, or the model returned
            nothing usable at all.
    """
    if not observations:
        raise SynthesisError("no observations were selected")
    selected = list(observations)[:MAX_STATEMENTS]

    statements = "\n".join(f"- {_statement_text(observation)}" for observation in selected)
    result = client.complete(
        SYNTHESIZE_PROMPT.system,
        SYNTHESIZE_PROMPT.render(
            statements=statements,
            attributes=", ".join(known_fields) or "none recorded",
            report_types=", ".join(report_kinds) or "none recorded",
        ),
        SynthesisResponse,
        stage="training_synthesize",
        prompt_version=SYNTHESIZE_PROMPT.version,
    )
    try:
        parsed = result.parsed(SynthesisResponse)
    except LLMResponseError as exc:
        raise SynthesisError(f"the model did not return a usable answer: {exc}") from exc

    if not parsed.rules:
        # Nothing was produced, so nothing is marked. Marking an observation as
        # synthesized when no candidate exists would take it out of the queue and
        # leave the person who wrote it waiting for an answer that never comes.
        raise SynthesisError(
            "the model returned no rules for these statements; they are unchanged and "
            "still in the queue"
        )

    source_ids = [observation.id for observation in selected]
    scope = _scope_for(selected)
    created: list[models.RuleCandidate] = []

    for rule in parsed.rules:
        problem = validate_rule(rule, known_fields)
        body = _body(rule)
        candidate = models.RuleCandidate(
            name=rule.name.strip(),
            target_kind=rule.target_kind,
            body=body,
            reasoning=rule.reasoning,
            severity=rule.severity,
            scope=scope,
            source_observation_ids=source_ids,
            status="rejected" if problem else "draft",
            admin_note=problem,
            model_draft=rule.model_dump(mode="json"),
            model_used=result.model,
            prompt_version=SYNTHESIZE_PROMPT.version,
            conflicts=[] if problem else find_conflicts(session, rule.target_kind, body, scope),
            created_by_user_id=user_id,
            created_by=actor,
        )
        session.add(candidate)
        created.append(candidate)

    session.flush()

    # The observation is marked, never consumed: asking again says it has already
    # been synthesized rather than doing the work twice or quietly dropping it.
    usable = next((c for c in created if c.status == "draft"), None)
    for observation in selected:
        observation.status = "synthesized"
        observation.candidate_id = usable.id if usable is not None else None
        observation.synthesized_at = sa.func.now()
    session.flush()

    _LOG.info("synthesized %d candidate(s) from %d observation(s)", len(created), len(selected))
    return created


def _statement_text(observation: models.TrainingObservation) -> str:
    """One observation, rendered for the prompt.

    Args:
        observation: The stored observation.

    Returns:
        Its statement, with what it points at and what the person expects. The anchor
        is included because "this field" means nothing without it.
    """
    parts = [observation.statement.strip()]
    if observation.expectation.strip():
        parts.append(f"Expected: {observation.expectation.strip()}")
    for anchor in observation.anchors or []:
        if not isinstance(anchor, dict):
            continue
        where = " ".join(
            str(anchor.get(key, "")).strip()
            for key in ("artifact", "sheet", "cell", "field", "reference")
            if str(anchor.get(key, "")).strip()
        )
        if where:
            parts.append(f"Points at: {where}")
    return " ".join(parts)


def _scope_for(observations: Sequence[models.TrainingObservation]) -> str:
    """The narrowest scope that covers a group.

    Args:
        observations: The group being synthesized.

    Returns:
        ``all``, a customer name, or ``programme:CODE``. The narrowest that fits is
        the default because the most common cause of a noisy rule is an assumption
        that holds for most records and not all; widening on evidence is easy, and
        narrowing after the complaints is not.
    """
    configs = {o.configuration_id for o in observations if o.kind == "config_note"}
    if configs and len(configs) == 1 and all(o.kind == "config_note" for o in observations):
        # A rule learned from a configuration note applies to that configuration and
        # no other; that is the whole point of writing the note there (ADR-024).
        return f"config:{configs.pop()}"
    hints = {observation.scope_hint for observation in observations}
    customers = {
        observation.customer_name for observation in observations if observation.customer_name
    }
    programmes = {observation.scope_code for observation in observations if observation.scope_code}

    if hints == {"customer"} and len(customers) == 1:
        return customers.pop()
    if hints == {"programme"} and len(programmes) == 1:
        return f"programme:{programmes.pop()}"
    if len(customers) == 1 and "global" not in hints:
        return customers.pop()
    return "all"


def approve(
    session: Session,
    candidate: models.RuleCandidate,
    *,
    scope: str | None = None,
    into_shadow: bool = True,
    actor: str = "",
    user_id: int | None = None,
    note: str = "",
) -> Any:
    """Turn a candidate into a rule the pipeline runs.

    Args:
        session: An open session.
        candidate: The candidate being approved.
        scope: A narrower scope than the candidate proposed, when the administrator
            wants one.
        into_shadow: Whether the rule starts in shadow. It should: precision is
            unknown until a rule has met real data, and a false-positive flood costs
            reviewer trust that takes months to earn back.
        actor: Who approved it.
        user_id: Their account id.
        note: Anything worth recording about the decision.

    Returns:
        The created rule row.

    Raises:
        SynthesisError: When the candidate has already been decided, or its target
            kind is not something the engine runs.
    """
    if candidate.status != "draft":
        raise SynthesisError(f"this candidate is already {candidate.status}")

    effective_scope = scope or candidate.scope
    body = dict(candidate.body or {})
    state = "shadow" if into_shadow else "active"

    if candidate.target_kind == "field_constraint":
        row: Any = models.FieldConstraint(
            field=str(body.get("field", "")),
            constraint=str(body.get("constraint", "")),
            value=body.get("value"),
            report_kinds=list(body.get("report_kinds") or []),
            severity=candidate.severity,
            reasoning=candidate.reasoning,
            scope=effective_scope,
            state=state,
            origin="learned",
            candidate_id=candidate.id,
            created_by=actor,
        )
    elif candidate.target_kind == "check":
        row = models.CheckDefinitionRow(
            name=candidate.name,
            expression=str(body.get("expression", "")),
            reasoning=candidate.reasoning,
            severity=candidate.severity,
            scope=effective_scope,
            is_active=state == "active",
            state=state,
            origin="learned",
            candidate_id=candidate.id,
        )
    elif candidate.target_kind == "compliance_rule":
        row = models.ComplianceRuleRow(
            name=candidate.name,
            requirement={"json_path_contains": candidate.name, "expected_value": True},
            scope=effective_scope,
            reasoning=candidate.reasoning,
            is_active=state == "active",
            state=state,
            origin="learned",
            candidate_id=candidate.id,
        )
    else:
        raise SynthesisError(f"{candidate.target_kind!r} is not something the engine runs")

    session.add(row)
    session.flush()

    candidate.status = "approved"
    candidate.admin_note = note or candidate.admin_note
    candidate.decided_by = actor
    candidate.decided_by_user_id = user_id
    candidate.decided_at = sa.func.now()

    set_state(
        session,
        candidate.target_kind,
        row.id,
        state,
        actor=actor,
        user_id=user_id,
        note=note or f"approved from candidate {candidate.id}",
    )
    _LOG.info(
        "candidate %d approved as %s %d in %s", candidate.id, candidate.target_kind, row.id, state
    )
    return row
