"""Asking the endpoint for the shape, and degrading when it will not (6.21e).

``docs/design.md`` has recommended guided decoding since Phase 2 — *"If the serving
stack supports guided or JSON-schema decoding (vLLM does), turn it on. It removes most
format errors."* — and nothing sent it. Phase 7 runs on a 20–40B in-house model, where
this is the largest reliability gain available for the smallest change.

What matters as much as sending it is what happens on a gateway that has never heard of
it. Which field an endpoint disliked is not knowable without reading a body that may
echo the prompt (ADR-003), so the rule is the simple one: under ``auto``, a 400 on a
guided request means drop the field, retry once, and stop offering it this process.

No test touches the network: every request goes through an injected httpx mock
transport (standards/python.md).
"""

from __future__ import annotations

import json
from typing import Any, Callable

import httpx
import pytest
from pydantic import BaseModel

from greenlight_ai.llm import AnthropicClient, LLMResponseError, LLMSettings, OpenAIClient


class Answer(BaseModel):
    """A tiny schema for exercising guided decoding."""

    verdict: str
    confidence: float


ANSWER = '{"verdict": "found", "confidence": 0.9}'


def _openai_body(text: str) -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": text}}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
    }


def _anthropic_text(text: str) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": 13, "output_tokens": 5},
    }


def _anthropic_tool(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [{"type": "tool_use", "name": "record_answer", "input": payload}],
        "usage": {"input_tokens": 13, "output_tokens": 5},
    }


def _settings(provider: str, **overrides: Any) -> LLMSettings:
    values: dict[str, Any] = {
        "provider": provider,
        "base_url": "http://llm.internal/v1",
        "model": "test-model",
        "api_key": "secret",
    }
    values.update(overrides)
    return LLMSettings(**values)


def _recorder(
    responses: list[httpx.Response],
) -> tuple[Callable[[httpx.Request], httpx.Response], list[dict[str, Any]]]:
    """A handler that replays ``responses`` in order and keeps every body it was sent."""
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return responses[min(len(sent) - 1, len(responses) - 1)]

    return handler, sent


# --------------------------------------------------------------- openai-compatible


def test_the_schema_is_sent_by_default() -> None:
    """``auto`` is the shipped default, so a vLLM deployment gets this for nothing."""
    handler, sent = _recorder([httpx.Response(200, json=_openai_body(ANSWER))])
    client = OpenAIClient(_settings("openai"), transport=httpx.MockTransport(handler))

    client.complete("sys", "user", Answer, stage="s4_trace")

    fmt = sent[0]["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["name"] == "Answer"
    assert fmt["json_schema"]["strict"] is True
    assert "verdict" in fmt["json_schema"]["schema"]["properties"]


def test_a_call_with_no_schema_never_asks_for_one() -> None:
    handler, sent = _recorder([httpx.Response(200, json=_openai_body("prose"))])
    client = OpenAIClient(_settings("openai"), transport=httpx.MockTransport(handler))

    client.complete("sys", "user", stage="s9_summarize")
    assert "response_format" not in sent[0]


def test_off_is_the_behaviour_before_this_setting_existed() -> None:
    handler, sent = _recorder([httpx.Response(200, json=_openai_body(ANSWER))])
    client = OpenAIClient(
        _settings("openai", guided_json="off"), transport=httpx.MockTransport(handler)
    )

    client.complete("sys", "user", Answer, stage="s4_trace")
    assert sent[0].keys() == {"model", "messages", "max_tokens", "temperature"}


def test_an_endpoint_that_refuses_is_retried_without_the_schema() -> None:
    """A gateway that has never heard of the field is not a broken deployment."""
    handler, sent = _recorder(
        [
            httpx.Response(400, json={"error": "unknown field"}),
            httpx.Response(200, json=_openai_body(ANSWER)),
        ]
    )
    client = OpenAIClient(_settings("openai"), transport=httpx.MockTransport(handler))

    result = client.complete("sys", "user", Answer, stage="s4_trace")

    assert result.parsed(Answer).verdict == "found"
    assert len(sent) == 2
    assert "response_format" in sent[0] and "response_format" not in sent[1]


def test_a_refusal_is_not_repeated_on_every_later_call() -> None:
    """The latch. One wasted call per process, not one per stage."""
    handler, sent = _recorder(
        [
            httpx.Response(400, json={"error": "unknown field"}),
            httpx.Response(200, json=_openai_body(ANSWER)),
        ]
    )
    client = OpenAIClient(_settings("openai"), transport=httpx.MockTransport(handler))

    client.complete("sys", "one", Answer, stage="s4_trace")
    client.complete("sys", "two", Answer, stage="s4_trace")

    assert len(sent) == 3, "the second call took one request, not two"
    assert "response_format" not in sent[2]


def test_the_call_record_says_whether_the_schema_was_sent() -> None:
    """Recorded rather than assumed, so the golden set can measure what it bought."""
    handler, _ = _recorder([httpx.Response(200, json=_openai_body(ANSWER))])
    client = OpenAIClient(_settings("openai"), transport=httpx.MockTransport(handler))
    client.complete("sys", "user", Answer, stage="s4_trace")
    assert client.call_log.records[-1].guided is True

    handler, _ = _recorder([httpx.Response(200, json=_openai_body(ANSWER))])
    off = OpenAIClient(
        _settings("openai", guided_json="off"), transport=httpx.MockTransport(handler)
    )
    off.complete("sys", "user", Answer, stage="s4_trace")
    assert off.call_log.records[-1].guided is False


def test_on_means_an_administrator_said_they_want_it() -> None:
    """No latch, no silent retry: the refusal surfaces as the error it is."""
    handler, sent = _recorder([httpx.Response(400, json={"error": "unknown field"})])
    client = OpenAIClient(
        _settings("openai", guided_json="on"), transport=httpx.MockTransport(handler)
    )

    with pytest.raises(LLMResponseError):
        client.complete("sys", "user", Answer, stage="s4_trace")
    assert len(sent) == 1


def test_an_ordinary_failure_is_still_an_ordinary_failure() -> None:
    """A 500 is not a refusal of the field, so nothing is dropped or latched."""
    handler, sent = _recorder([httpx.Response(500, json={"error": "upstream"})])
    client = OpenAIClient(_settings("openai"), transport=httpx.MockTransport(handler))

    with pytest.raises(LLMResponseError):
        client.complete("sys", "user", Answer, stage="s4_trace")
    assert len(sent) == 1


def test_no_error_body_is_read_or_logged(caplog: pytest.LogCaptureFixture) -> None:
    """ADR-003 at the one place the new code touches an error response."""
    handler, _ = _recorder(
        [
            httpx.Response(400, json={"error": {"message": "prompt was: SECRET-ROW-DATA"}}),
            httpx.Response(200, json=_openai_body(ANSWER)),
        ]
    )
    client = OpenAIClient(_settings("openai"), transport=httpx.MockTransport(handler))

    with caplog.at_level("DEBUG"):
        client.complete("sys", "user", Answer, stage="s4_trace")
    assert "SECRET-ROW-DATA" not in caplog.text


# ------------------------------------------------------------------------ anthropic


def test_anthropic_constrains_with_a_required_tool() -> None:
    """The Messages API has no ``response_format``; a forced tool is how it is done."""
    handler, sent = _recorder(
        [httpx.Response(200, json=_anthropic_tool({"verdict": "found", "confidence": 0.9}))]
    )
    client = AnthropicClient(_settings("anthropic"), transport=httpx.MockTransport(handler))

    result = client.complete("sys", "user", Answer, stage="s4_trace")

    assert result.parsed(Answer).confidence == pytest.approx(0.9)
    assert sent[0]["tool_choice"] == {"type": "tool", "name": "record_answer"}
    assert "verdict" in sent[0]["tools"][0]["input_schema"]["properties"]


def test_anthropic_still_reads_a_plain_text_answer() -> None:
    """Which is what comes back when guided decoding is off, or was refused."""
    handler, _ = _recorder([httpx.Response(200, json=_anthropic_text(ANSWER))])
    client = AnthropicClient(
        _settings("anthropic", guided_json="off"), transport=httpx.MockTransport(handler)
    )

    assert (
        client.complete("sys", "user", Answer, stage="s4_trace").parsed(Answer).verdict == "found"
    )


def test_anthropic_degrades_on_a_refusal_too() -> None:
    handler, sent = _recorder(
        [
            httpx.Response(400, json={"error": "unknown field"}),
            httpx.Response(200, json=_anthropic_text(ANSWER)),
        ]
    )
    client = AnthropicClient(_settings("anthropic"), transport=httpx.MockTransport(handler))

    client.complete("sys", "user", Answer, stage="s4_trace")
    assert len(sent) == 2
    assert "tools" in sent[0] and "tools" not in sent[1]
