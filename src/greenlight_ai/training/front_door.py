"""One place to tell the tool something, on top of the surfaces that already run it.

An administrator who wants this tool to check something has to know which of sixteen
places it belongs on, and each of those places is the right home for what it holds. The
tempting answer is a seventeenth surface that accepts anything. That would be a second
path into the rule tables, a second evaluator to keep honest, and a second place to look
when a finding is wrong.

So the front door is a step in front of the loop ADR-021 already built, and nothing
else. The model places the sentence; the drafting, the validation, the fingerprint, the
conflict check and the critique pass are `training.synthesis`, unchanged; what comes out
is an ordinary candidate that the ordinary approval path handles. A statement that is
background rather than a rule is said to be background and offered to the surface that
holds background, never forced into a rule that would then be wrong. A statement the
model cannot place comes back with its question and creates nothing.

The classification routes; it does not draft. Synthesis decides the rule's shape as it
always has, and when the two disagree the answer says so rather than hiding it — a
statement the tool read two ways is exactly what an administrator should see before
approving anything.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final, Sequence

from sqlalchemy.orm import Session

from greenlight_ai import scopes
from greenlight_ai.db import models
from greenlight_ai.llm.client import LLMClient, LLMError, LLMResponseError
from greenlight_ai.llm.prompts.admin_classify import CLASSIFY_PROMPT
from greenlight_ai.llm.prompts.schemas import ClassifyResponse
from greenlight_ai.training.synthesis import SynthesisError, synthesize

__all__ = ["FrontDoorError", "FrontDoorResult", "RULE_SURFACES", "place"]

_LOG: Final = logging.getLogger(__name__)

#: The surfaces that become a candidate rule. ``background`` and ``unclear`` do not.
RULE_SURFACES: Final[tuple[str, ...]] = ("field_constraint", "check", "compliance_rule")

#: What an observation is filed as, per surface. A check and a compliance rule are both
#: reconciliation work; only a field constraint has its own kind in the queue.
_OBSERVATION_KIND: Final[dict[str, str]] = {
    "field_constraint": "field_constraint",
    "check": "reconciliation",
    "compliance_rule": "reconciliation",
}

#: Where a statement that is not a rule is offered instead.
_BACKGROUND_HOME: Final[str] = (
    "This is background rather than a rule. It belongs in an artifact type's AI context "
    "when it says how to read a file, or in a standing instruction when it applies to "
    "every run."
)


class FrontDoorError(Exception):
    """The statement could not be placed at all, with the reason in its message."""


@dataclass(frozen=True, slots=True)
class FrontDoorResult:
    """What became of one sentence.

    Attributes:
        surface: What the model called it, from the closed set.
        reason: Why, in one sentence, for the administrator.
        confidence: How sure the classification was.
        question: What the model needs to know, when it could not place the sentence.
        candidate: The candidate rule, when one was drafted. ``None`` otherwise.
        observation_id: The observation the statement was filed as, when it became one.
        note: What the administrator should do next, when nothing was created.
        drafted_as: The shape synthesis actually drafted, which is usually the surface
            and is worth seeing when it is not.
    """

    surface: str
    reason: str = ""
    confidence: float = 0.0
    question: str = ""
    candidate: models.RuleCandidate | None = None
    observation_id: int | None = None
    note: str = ""
    drafted_as: str = ""


def _hints(scope: str) -> dict[str, str]:
    """Turn a scope token into the hints an observation carries.

    Synthesis derives a candidate's scope from its observations rather than from an
    argument, so the front door says where the statement applies by filing it that way.
    There is no second route to a scope, just as there is no second route to a rule.

    Args:
        scope: Any scope token (:mod:`greenlight_ai.scopes`).

    Returns:
        The observation fields that express it.
    """
    parsed = scopes.parse(scope)
    if parsed.kind == "programme":
        return {"scope_hint": "programme", "scope_code": parsed.value}
    if parsed.kind == "customer":
        return {"scope_hint": "customer", "customer_name": parsed.value}
    if parsed.kind == "configuration":
        return {"scope_hint": "global", "configuration_id": parsed.value}
    return {"scope_hint": "global"}


def classify(
    client: LLMClient,
    statement: str,
    *,
    known_fields: Sequence[str] = (),
    report_kinds: Sequence[str] = (),
) -> ClassifyResponse:
    """Ask which surface a statement belongs on.

    Args:
        client: The model adapter.
        statement: What the administrator wrote. It reaches the prompt inside a
            delimited block, marked as data rather than as an instruction.
        known_fields: Attribute names the tool knows.
        report_kinds: The report types that exist.

    Returns:
        The classification.

    Raises:
        FrontDoorError: When the model could not be reached, or answered with
            something the schema rejects.
    """
    try:
        result = client.complete(
            CLASSIFY_PROMPT.system,
            CLASSIFY_PROMPT.render(
                statement=statement.strip(),
                attributes=", ".join(known_fields) or "none recorded",
                report_types=", ".join(report_kinds) or "none recorded",
            ),
            ClassifyResponse,
            stage="admin_classify",
            prompt_version=CLASSIFY_PROMPT.version,
        )
        return result.parsed(ClassifyResponse)
    except LLMResponseError as exc:
        raise FrontDoorError(f"the model did not return a usable answer: {exc}") from exc
    except LLMError as exc:
        raise FrontDoorError(f"the model could not be reached: {exc}") from exc


def place(
    session: Session,
    client: LLMClient,
    statement: str,
    *,
    scope: str = "",
    known_fields: Sequence[str] = (),
    report_kinds: Sequence[str] = (),
    actor: str = "",
    user_id: int | None = None,
) -> FrontDoorResult:
    """Put one sentence on the surface it belongs on.

    Args:
        session: An open session.
        client: The model adapter.
        statement: What the administrator wrote.
        scope: Where it applies, as a scope token. Everywhere when omitted.
        known_fields: Attribute names the tool knows, so an invented one is caught.
        report_kinds: The report types that exist.
        actor: Who wrote it.
        user_id: Their account id.

    Returns:
        What became of it: a candidate in draft, an offer to a surface that holds
        background, or a question. Nothing is created in the last two cases, because a
        rule drafted from a sentence nobody could place is a finding nobody can explain.

    Raises:
        FrontDoorError: When the statement is empty, or the model could not be reached.
    """
    text = statement.strip()
    if not text:
        raise FrontDoorError("nothing was written")

    classified = classify(client, text, known_fields=known_fields, report_kinds=report_kinds)
    surface = classified.surface

    if surface == "unclear":
        _LOG.info("front door: could not place a statement from %s", actor or "?")
        return FrontDoorResult(
            surface=surface,
            reason=classified.reason,
            confidence=classified.confidence,
            question=classified.question or "What would you like the tool to check?",
            note="Nothing was created.",
        )

    if surface == "background":
        _LOG.info("front door: background statement from %s", actor or "?")
        return FrontDoorResult(
            surface=surface,
            reason=classified.reason,
            confidence=classified.confidence,
            note=_BACKGROUND_HOME,
        )

    observation = models.TrainingObservation(
        kind=_OBSERVATION_KIND.get(surface, "reconciliation"),
        statement=text,
        author=actor,
        author_user_id=user_id,
        status="new",
        **_hints(scope),
    )
    session.add(observation)
    session.flush()

    try:
        candidates = synthesize(
            session,
            client,
            [observation],
            known_fields=known_fields,
            report_kinds=report_kinds,
            actor=actor,
            user_id=user_id,
        )
    except SynthesisError as exc:
        # The observation stays: somebody said something, and the record of that is
        # worth more than the row it occupies (ADR-021). It is in the queue, where an
        # administrator can synthesize it with others.
        return FrontDoorResult(
            surface=surface,
            reason=classified.reason,
            confidence=classified.confidence,
            observation_id=observation.id,
            note=f"No rule was drafted: {exc}. The statement is in the training queue.",
        )

    drafted = next((c for c in candidates if c.status == "draft"), None) or candidates[0]
    note = ""
    if drafted.status == "draft" and drafted.target_kind != surface:
        note = (
            f"Read as a {surface.replace('_', ' ')} and drafted as a "
            f"{drafted.target_kind.replace('_', ' ')}. Check it says what you meant."
        )
    elif drafted.status != "draft":
        note = drafted.admin_note or "The draft was rejected before anyone saw it."

    _LOG.info(
        "front door: %s from %s became candidate %s (%s)",
        surface,
        actor or "?",
        drafted.id,
        drafted.status,
    )
    return FrontDoorResult(
        surface=surface,
        reason=classified.reason,
        confidence=classified.confidence,
        candidate=drafted,
        observation_id=observation.id,
        note=note,
        drafted_as=drafted.target_kind,
    )
