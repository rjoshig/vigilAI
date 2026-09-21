"""The mock client: canned answers, no network, used by every test and by Phase 2.

Tests never call a real LLM (standards/python.md), and the whole of Phase 2 is built and
validated against this provider (ADR-014). The mock is therefore not a stub: it answers
plausibly for each stage so the pipeline can be exercised end to end, and it records
what it was asked so tests can assert on prompt content.

Answers come from a responder table keyed by stage. A test that needs a specific answer
registers one, which is the injected-fake path the standards call for.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Final, Mapping

from greenlight_ai.llm.base import BaseClient
from greenlight_ai.llm.client import LLMResponseError
from greenlight_ai.llm.settings import LLMSettings

__all__ = ["MockClient", "Responder", "canned_for_stage"]

_LOG: Final = logging.getLogger(__name__)

#: A responder receives the system and user prompts and returns the response text.
Responder = Callable[[str, str], str]


def canned_for_stage(stage: str) -> str:
    """Return a schema-shaped answer for a pipeline stage.

    The shapes match what each stage's prompt asks for, so the orchestrator can run with
    no provider configured. Values are deliberately empty rather than invented: a mock
    that fabricates requirements would make a passing test meaningless.

    Args:
        stage: The pipeline stage name, e.g. ``"s2_extract"``.

    Returns:
        A JSON document as text.
    """
    shapes: Mapping[str, str] = {
        "s2_extract": '{"requirements": []}',
        "s3_describe": '{"elements": []}',
        "s4_trace": '{"verdict": "not_related", "reason": "mock client", "confidence": 0.0}',
        "s8_verify": '{"agreed": true, "reason": "mock client", "confidence": 0.0}',
        "s8_coverage": '{"gaps": []}',
        "training_critique": (
            '{"faithful": true, "problem": "", "overlaps": false, "overlaps_with": "", '
            '"confidence": 0.0}'
        ),
        "s8_lens_delivery": (
            '{"agreed": true, "reason": "mock client", "confidence": 0.0, "missed": []}'
        ),
        "s8_lens_compliance": (
            '{"agreed": true, "reason": "mock client", "confidence": 0.0, "missed": []}'
        ),
        "s8_lens_requirements": (
            '{"agreed": true, "reason": "mock client", "confidence": 0.0, "missed": []}'
        ),
        "s9_summarize": '{"summary": "Mock summary; no model was called.", "top_issues": []}',
        "admin_classify": (
            '{"surface": "unclear", "reason": "mock client", "confidence": 0.0, '
            '"question": "What would you like the tool to check?"}'
        ),
        "admin_draft_check": '{"named_values": [], "expression": "", "reasoning": "", '
        '"severity": "medium"}',
        "admin_judgment": '{"verdict": "review", "reason": "mock client", ' '"confidence": 0.0}',
        # "absent" rather than "found": the mock must not invent a path, and
        # absence is what the deterministic matcher already concluded.
        "compliance_locate": '{"verdict": "absent", "json_path": "", '
        '"reason": "mock client", "confidence": 0.0}',
        # "unclear" rather than a programme: the mock must not contradict a submitter,
        # and unfamiliar vocabulary is what the keyword check already concluded.
        "programme_reading": '{"programme_code": "", "verdict": "unclear", '
        '"phrases": [], "reason": "mock client", "confidence": 0.0}',
    }
    return shapes.get(stage, "{}")


class MockClient(BaseClient):
    """Answers without a network call.

    Attributes:
        prompts: Every ``(stage, system, user)`` triple this client was asked, in order,
            so a test can assert that a prompt carried no sample rows.
    """

    provider_name = "mock"

    def __init__(
        self,
        settings: LLMSettings | None = None,
        responders: Mapping[str, Responder] | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialise the client.

        Args:
            settings: The settings; a mock-provider default is used when omitted.
            responders: Stage name to responder, overriding the canned answers.
            **kwargs: Passed to :class:`~greenlight_ai.llm.base.BaseClient`.
        """
        super().__init__(settings or LLMSettings(), **kwargs)
        self._responders: dict[str, Responder] = dict(responders or {})
        self.prompts: list[tuple[str, str, str]] = []
        self._current_stage = ""

    def register(self, stage: str, responder: Responder) -> None:
        """Set the answer for a stage.

        Args:
            stage: The pipeline stage name.
            responder: Called with the system and user prompts; returns response text.
        """
        self._responders[stage] = responder

    def register_text(self, stage: str, text: str) -> None:
        """Set a fixed answer for a stage.

        Args:
            stage: The pipeline stage name.
            text: The response text to return.
        """
        self._responders[stage] = lambda _system, _user: text

    def complete(self, system: str, user: str, schema: Any = None, **kwargs: Any) -> Any:
        """Record the stage, then delegate to the shared caching path.

        Args:
            system: The system prompt.
            user: The user prompt.
            schema: The output schema, if any.
            **kwargs: ``stage`` and ``prompt_version``.

        Returns:
            The result, from the cache or from a responder.
        """
        self._current_stage = str(kwargs.get("stage", ""))
        return super().complete(system, user, schema, **kwargs)

    def _send(self, system: str, user: str) -> tuple[str, int, int]:
        """Produce a canned answer.

        Args:
            system: The system prompt.
            user: The user prompt.

        Returns:
            A ``(text, prompt_tokens, completion_tokens)`` triple. Token counts are
            estimated from length so budget behaviour can be exercised without a model.

        Raises:
            LLMResponseError: When a registered responder raises, which is how a test
                simulates a bad answer.
        """
        stage = self._current_stage
        self.prompts.append((stage, system, user))
        responder = self._responders.get(stage)
        try:
            text = responder(system, user) if responder is not None else canned_for_stage(stage)
        except LLMResponseError:
            raise
        except Exception as exc:  # noqa: BLE001 - a responder is test code; surface it
            raise LLMResponseError(f"mock responder for stage {stage!r} failed") from exc
        return text, _estimate_tokens(system) + _estimate_tokens(user), _estimate_tokens(text)


def _estimate_tokens(text: str) -> int:
    """Estimate a token count from text length.

    Args:
        text: The text.

    Returns:
        Roughly one token per four characters, the usual English approximation. Only
        used so budget and usage behaviour are exercisable without a real model.
    """
    return max(1, len(text) // 4)
