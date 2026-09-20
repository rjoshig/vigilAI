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

from greenlight_ai import scopes
from greenlight_ai.checks.field_constraints import CONSTRAINT_KINDS
from greenlight_ai.db import models
from greenlight_ai.llm.client import LLMClient, LLMError, LLMResponseError
from greenlight_ai.llm.prompts.synthesize import SYNTHESIZE_PROMPT
from greenlight_ai.llm.prompts.synthesize_critique import CRITIQUE_PROMPT
from greenlight_ai.llm.prompts.schemas import (
    CritiqueResponse,
    SynthesisResponse,
    SynthesizedRule,
)
from greenlight_ai.training.lifecycle import set_state

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
        if not rule.json_path_contains.strip():
            return (
                "a compliance rule needs the configuration path fragment it looks for; "
                "without one it has nothing to check"
            )
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
    return {"json_path_contains": rule.json_path_contains.strip(), "reasoning": rule.reasoning}


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
                        "name": f"{row.field} {row.constraint}",
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
                        "name": check.name,
                        "summary": check.expression,
                        "scope": check.scope,
                        "state": check.state,
                        "same": True,
                    }
                )
    elif target_kind == "compliance_rule":
        wanted_path = str(body.get("json_path_contains", "")).strip()
        compliance_rows = session.execute(
            sa.select(models.ComplianceRuleRow).where(models.ComplianceRuleRow.state != "deleted")
        ).scalars()
        for compliance in compliance_rows:
            path = str((compliance.requirement or {}).get("json_path_contains", "")).strip()
            if wanted_path and path == wanted_path:
                conflicts.append(
                    {
                        "rule_kind": "compliance_rule",
                        "id": compliance.id,
                        "name": compliance.name,
                        "summary": path,
                        "scope": compliance.scope,
                        "state": compliance.state,
                        "same": compliance.scope == scope,
                    }
                )
    return conflicts


def _critique_once(
    session: Session,
    client: LLMClient,
    rule: Any,
    statements: str,
    known_fields: Sequence[str],
    scope: str,
) -> tuple[Any, dict[str, Any]]:
    """Read a drafted rule back against the statements, and redraft at most once.

    The model checks the draft, never the data. A redraft that fails validation is
    thrown away and the first draft stands, because a worse second attempt is not an
    improvement and an administrator should see the better of the two.

    Args:
        session: An open session, for the existing rules the draft might overlap.
        client: The model adapter.
        rule: The drafted rule.
        statements: What people wrote, as the synthesis prompt carried it.
        known_fields: Attribute names the tool knows.
        scope: The scope the candidate will carry.

    Returns:
        The rule to store (the redraft when there is a good one, otherwise the
        original) and what the critique said, empty when it could not run.
    """
    existing = find_conflicts(session, rule.target_kind, _body(rule), scope)
    existing_text = (
        "; ".join(f'"{c.get("name", "")}" ({c.get("summary", "")})' for c in existing) or "none"
    )
    draft_text = _draft_text(rule)

    try:
        result = client.complete(
            CRITIQUE_PROMPT.system,
            CRITIQUE_PROMPT.render(statements=statements, existing=existing_text, draft=draft_text),
            CritiqueResponse,
            stage="training_critique",
            prompt_version=CRITIQUE_PROMPT.version,
        )
        answer = result.parsed(CritiqueResponse)
    except (LLMError, LLMResponseError) as exc:
        # The critique is an improvement, not a gate: a draft nobody could check is
        # still a draft a person reads.
        _LOG.info("critique could not run (%s); the first draft stands", type(exc).__name__)
        return rule, {}

    critique = answer.model_dump(mode="json")
    if answer.faithful:
        return rule, critique

    try:
        second = client.complete(
            SYNTHESIZE_PROMPT.system,
            SYNTHESIZE_PROMPT.render(
                statements=(
                    f"{statements}\n\nA previous draft was rejected because: "
                    f"{answer.problem} Draft the rule again, fixing exactly that."
                ),
                attributes=", ".join(known_fields) or "none recorded",
                report_types="none recorded",
            ),
            SynthesisResponse,
            stage="training_synthesize",
            prompt_version=SYNTHESIZE_PROMPT.version,
        )
        redrafted = second.parsed(SynthesisResponse)
    except (LLMError, LLMResponseError) as exc:
        _LOG.info("redraft could not run (%s); the first draft stands", type(exc).__name__)
        return rule, critique

    # The redraft answers for every statement in the batch, so it can carry several
    # rules. The one that replaces this draft is the one about the same thing; taking
    # the first in the list swapped a compliance rule for a field constraint whenever
    # the batch held both (Phase 6.13a).
    candidate_rule = _matching_redraft(rule, redrafted.rules)
    if candidate_rule is None or validate_rule(candidate_rule, known_fields):
        # No redraft about this rule, or one that does not validate, is worse than
        # what it replaces.
        return rule, critique
    critique["redrafted"] = True
    return candidate_rule, critique


def _matching_redraft(
    original: SynthesizedRule, redrafts: Sequence[SynthesizedRule]
) -> SynthesizedRule | None:
    """Pick the redraft that is about the same rule as the original.

    Args:
        original: The draft the critique found unfaithful.
        redrafts: Every rule the redraft call returned.

    Returns:
        The redraft with the same target kind that shares the original's name or its
        source statements, else the only same-kind redraft, else ``None``.
    """
    same_kind = [r for r in redrafts if r.target_kind == original.target_kind]
    for candidate in same_kind:
        if candidate.name.strip() and candidate.name.strip() == original.name.strip():
            return candidate
    for candidate in same_kind:
        if original.from_statements and set(candidate.from_statements) & set(
            original.from_statements
        ):
            return candidate
    return same_kind[0] if len(same_kind) == 1 else None


def _draft_text(rule: Any) -> str:
    """Render a drafted rule for the critique prompt.

    Args:
        rule: The drafted rule.

    Returns:
        One line naming its kind and what it asserts.
    """
    body = _body(rule)
    parts = [f"{rule.target_kind}"]
    for key in ("field", "constraint", "expression", "value", "report_kinds"):
        if body.get(key) not in (None, "", [], {}):
            parts.append(f"{key}={body[key]}")
    return " ".join(str(part) for part in parts)


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

    # Numbered rather than bulleted, so a rule can say which statements it came from.
    statements = "\n".join(
        f"{index}. {_statement_text(observation)}" for index, observation in enumerate(selected, 1)
    )
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

    all_ids = [observation.id for observation in selected]
    scope = _scope_for(selected)
    created: list[models.RuleCandidate] = []

    for rule in parsed.rules:
        problem = validate_rule(rule, known_fields)
        body = _body(rule)
        critique: dict[str, Any] = {}
        first_draft = rule.model_dump(mode="json")
        if not problem:
            # One bounded revision. A well-formed rule that says something the person
            # did not is the failure an administrator cannot see from an expression,
            # and it is the one worth a second call (Phase 6.11g).
            rule, critique = _critique_once(session, client, rule, statements, known_fields, scope)
            problem = validate_rule(rule, known_fields)
            body = _body(rule)
        candidate = models.RuleCandidate(
            name=rule.name.strip(),
            target_kind=rule.target_kind,
            body=body,
            reasoning=rule.reasoning,
            severity=rule.severity,
            scope=scope,
            source_observation_ids=_sources_for(rule, all_ids),
            status="rejected" if problem else "draft",
            admin_note=problem,
            model_draft=first_draft,
            redraft=rule.model_dump(mode="json") if critique else {},
            critique=critique,
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
    # been synthesized rather than doing the work twice or quietly dropping it. Each
    # observation points at the draft that named it, so "what became of what I wrote"
    # has one answer per sentence rather than one per batch.
    fallback = next((c for c in created if c.status == "draft"), None)
    for observation in selected:
        own = next(
            (
                c
                for c in created
                if c.status == "draft" and observation.id in (c.source_observation_ids or [])
            ),
            fallback,
        )
        observation.status = "synthesized"
        observation.candidate_id = own.id if own is not None else None
        observation.synthesized_at = sa.func.now()
    session.flush()

    _LOG.info("synthesized %d candidate(s) from %d observation(s)", len(created), len(selected))
    return created


def _sources_for(rule: SynthesizedRule, all_ids: Sequence[int]) -> list[int]:
    """Which observations a drafted rule came from.

    Args:
        rule: The drafted rule, whose ``from_statements`` are one-based indexes into
            the numbered statements block.
        all_ids: The observation ids in the order they were numbered.

    Returns:
        The ids the model named, in order and without repeats. The whole batch when it
        named none or only nonsense, because a candidate with no source is worse than
        one with too many.
    """
    chosen = [
        all_ids[index - 1]
        for index in dict.fromkeys(rule.from_statements)
        if 1 <= index <= len(all_ids)
    ]
    return chosen or list(all_ids)


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
        A canonical scope token (:mod:`greenlight_ai.scopes`). The narrowest that fits
        is the default because the most common cause of a noisy rule is an assumption
        that holds for most records and not all; widening on evidence is easy, and
        narrowing after the complaints is not.
    """
    configs = {o.configuration_id for o in observations if o.kind == "config_note"}
    if configs and len(configs) == 1 and all(o.kind == "config_note" for o in observations):
        # A rule learned from a configuration note applies to that configuration and
        # no other; that is the whole point of writing the note there (ADR-024).
        return scopes.for_configuration(configs.pop()).token
    hints = {observation.scope_hint for observation in observations}
    customers = {
        observation.customer_name for observation in observations if observation.customer_name
    }
    programmes = {observation.scope_code for observation in observations if observation.scope_code}

    if hints == {"customer"} and len(customers) == 1:
        return scopes.for_customer(customers.pop()).token
    if hints == {"programme"} and len(programmes) == 1:
        return scopes.for_programme(programmes.pop()).token
    if len(customers) == 1 and "global" not in hints:
        return scopes.for_customer(customers.pop()).token
    return scopes.EVERYWHERE


def approve(
    session: Session,
    candidate: models.RuleCandidate,
    *,
    scope: str | None = None,
    into_shadow: bool = True,
    actor: str = "",
    user_id: int | None = None,
    note: str = "",
    resolution: str = "",
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
        resolution: What to do about an overlap with an existing rule:
            ``"supersede"`` disables the rule it overlaps, naming this one as its
            successor, or ``"keep_both"`` when the administrator has looked and says
            they cover different ground. Required when the candidate has conflicts.

    Returns:
        The created rule row.

    Raises:
        SynthesisError: When the candidate has already been decided, its target kind
            is not something the engine runs, or it overlaps an existing rule and the
            administrator has not said what to do about that.
    """
    if candidate.status != "draft":
        raise SynthesisError(f"this candidate is already {candidate.status}")

    effective_scope = scope or candidate.scope
    body = dict(candidate.body or {})
    # Found again now rather than read from synthesis time: a rule created in between
    # would otherwise be invisible to the one gate that exists to catch overlap.
    conflicts = find_conflicts(session, candidate.target_kind, body, effective_scope)
    candidate.conflicts = conflicts
    if conflicts and resolution not in ("supersede", "keep_both"):
        # Overlapping rules accumulate quietly and are very hard to untangle later, so
        # the decision is taken once, here, by the person approving (ADR-021).
        names = ", ".join(str(c.get("name", "")) for c in conflicts if c.get("name"))
        raise SynthesisError(
            f"this candidate overlaps {len(conflicts)} existing rule(s) ({names}). "
            "Say whether it supersedes them or whether both should run."
        )

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
            requirement={
                "json_path_contains": str(body.get("json_path_contains", "")).strip(),
                "expected_value": body.get("expected_value", True),
            },
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

    if conflicts and resolution == "supersede":
        _supersede(session, candidate, conflicts, row.id, actor=actor, user_id=user_id)

    _LOG.info(
        "candidate %d approved as %s %d in %s", candidate.id, candidate.target_kind, row.id, state
    )
    return row


def _supersede(
    session: Session,
    candidate: models.RuleCandidate,
    conflicts: Sequence[dict[str, Any]],
    successor_id: int,
    *,
    actor: str = "",
    user_id: int | None = None,
) -> None:
    """Disable the rules a newly approved rule replaces.

    Disabled rather than deleted: a superseded rule is reversible at any time, and its
    findings on old runs still have something to point at (ADR-021).

    Args:
        session: An open session.
        candidate: The candidate that was approved.
        conflicts: The overlaps recorded on it.
        successor_id: The rule that replaces them.
        actor: Who approved it.
        user_id: Their account id.
    """
    for conflict in conflicts:
        rule_id = conflict.get("id")
        if not isinstance(rule_id, int):
            continue
        try:
            set_state(
                session,
                candidate.target_kind,
                rule_id,
                "disabled",
                actor=actor,
                user_id=user_id,
                note=(
                    f"superseded by {candidate.target_kind} {successor_id}, approved from "
                    f"candidate {candidate.id}"
                ),
            )
        except Exception as exc:  # pragma: no cover - a rule deleted between the two steps
            _LOG.warning("could not supersede %s %s: %s", candidate.target_kind, rule_id, exc)
