"""Tests for the provider clients.

No test touches the network: every request goes through an injected httpx mock
transport (standards/python.md).
"""

from __future__ import annotations

import json
from typing import Any, Callable

import httpx
import pytest
from pydantic import BaseModel

from greenlight_ai.llm import (
    AnthropicClient,
    CallLog,
    LLMBudgetExceeded,
    LLMCache,
    LLMError,
    LLMResponseError,
    LLMSettings,
    LLMTimeoutError,
    MemoryCache,
    MockClient,
    OpenAIClient,
    build_client,
    extract_json,
)


class Answer(BaseModel):
    """A tiny schema for exercising validation."""

    verdict: str
    confidence: float


def _openai_body(text: str, prompt_tokens: int = 11, completion_tokens: int = 7) -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": text}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }


def _anthropic_body(text: str) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": 13, "output_tokens": 5},
    }


def _transport(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _openai_settings(**overrides: Any) -> LLMSettings:
    values: dict[str, Any] = {
        "provider": "openai",
        "base_url": "http://llm.internal/v1",
        "model": "test-model",
        "api_key": "secret",
    }
    values.update(overrides)
    return LLMSettings(**values)


# --- OpenAI-compatible ------------------------------------------------------------------


def test_openai_posts_to_chat_completions_with_both_messages() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["payload"] = json.loads(request.content)
        return httpx.Response(200, json=_openai_body("hello"))

    client = OpenAIClient(_openai_settings(), transport=_transport(handler))
    result = client.complete("system text", "user text", stage="s9_summarize")

    assert seen["url"] == "http://llm.internal/v1/chat/completions"
    assert seen["headers"]["authorization"] == "Bearer secret"
    assert seen["payload"]["messages"] == [
        {"role": "system", "content": "system text"},
        {"role": "user", "content": "user text"},
    ]
    assert seen["payload"]["temperature"] == 0.0
    assert result.text == "hello"
    assert result.prompt_tokens == 11
    assert result.total_tokens == 18


def test_openai_omits_the_auth_header_when_no_key_is_set() -> None:
    """Ollama and most in-house gateways need no credential."""
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        return httpx.Response(200, json=_openai_body("ok"))

    client = OpenAIClient(_openai_settings(api_key=""), transport=_transport(handler))
    client.complete("s", "u")
    assert "authorization" not in seen["headers"]


def test_openai_error_status_does_not_echo_the_body() -> None:
    """A 4xx body may quote the prompt, which must never reach a log (ADR-003)."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "prompt was: SECRET-ROW-DATA"}})

    client = OpenAIClient(_openai_settings(), transport=_transport(handler))
    with pytest.raises(LLMResponseError) as excinfo:
        client.complete("s", "u")
    assert "400" in str(excinfo.value)
    assert "SECRET-ROW-DATA" not in str(excinfo.value)


def test_openai_timeout_becomes_a_typed_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow")

    client = OpenAIClient(_openai_settings(), transport=_transport(handler))
    with pytest.raises(LLMTimeoutError):
        client.complete("s", "u")


def test_openai_rejects_a_body_that_is_not_a_completion() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    client = OpenAIClient(_openai_settings(), transport=_transport(handler))
    with pytest.raises(LLMResponseError, match="chat completion"):
        client.complete("s", "u")


def test_openai_tolerates_a_missing_usage_block() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})

    client = OpenAIClient(_openai_settings(), transport=_transport(handler))
    assert client.complete("s", "u").total_tokens == 0


# --- Anthropic ----------------------------------------------------------------------------


def test_anthropic_sends_system_as_a_top_level_field() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["payload"] = json.loads(request.content)
        return httpx.Response(200, json=_anthropic_body("answer"))

    settings = _openai_settings(provider="anthropic")
    client = AnthropicClient(settings, transport=_transport(handler))
    result = client.complete("system text", "user text")

    assert seen["url"] == "http://llm.internal/v1/v1/messages"
    assert seen["headers"]["x-api-key"] == "secret"
    assert seen["headers"]["anthropic-version"] == "2023-06-01"
    assert seen["payload"]["system"] == "system text"
    assert seen["payload"]["messages"] == [{"role": "user", "content": "user text"}]
    assert result.text == "answer"
    assert result.prompt_tokens == 13


def test_anthropic_joins_multiple_text_blocks() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "text", "text": "part one "},
                    {"type": "thinking", "text": "ignored"},
                    {"type": "text", "text": "part two"},
                ],
                "usage": {},
            },
        )

    client = AnthropicClient(_openai_settings(provider="anthropic"), transport=_transport(handler))
    assert client.complete("s", "u").text == "part one part two"


def test_anthropic_rejects_an_unexpected_body() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"nope": 1})

    client = AnthropicClient(_openai_settings(provider="anthropic"), transport=_transport(handler))
    with pytest.raises(LLMResponseError, match="messages response"):
        client.complete("s", "u")


# --- shared behaviour: cache, retry, budget, recording -------------------------------------


def test_the_cache_is_checked_before_every_call() -> None:
    """ADR-005: a miss is the only path to the network."""
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_openai_body("cached me"))

    client = OpenAIClient(_openai_settings(), transport=_transport(handler))
    first = client.complete("s", "u", stage="s2_extract")
    second = client.complete("s", "u", stage="s2_extract")

    assert calls == 1
    assert first.cached is False
    assert second.cached is True
    assert second.text == "cached me"


def test_a_cache_hit_reports_zero_tokens() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_openai_body("x"))

    client = OpenAIClient(_openai_settings(), transport=_transport(handler))
    client.complete("s", "u")
    assert client.complete("s", "u").total_tokens == 0
    assert client.call_log.cache_hits == 1


def test_a_different_schema_is_a_different_call() -> None:
    """Reusing an answer shaped for another schema would return the wrong shape."""

    class Other(BaseModel):
        agreed: bool

    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        body = '{"verdict": "implemented", "confidence": 0.9, "agreed": true}'
        return httpx.Response(200, json=_openai_body(body))

    client = OpenAIClient(_openai_settings(), transport=_transport(handler))
    client.complete("s", "u", Answer)
    client.complete("s", "u", Other)
    assert calls == 2


def test_invalid_json_is_retried_once_with_the_error_appended() -> None:
    prompts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        prompts.append(payload["messages"][1]["content"])
        if len(prompts) == 1:
            return httpx.Response(200, json=_openai_body("not json at all"))
        return httpx.Response(
            200, json=_openai_body('{"verdict": "implemented", "confidence": 0.9}')
        )

    client = OpenAIClient(_openai_settings(), transport=_transport(handler))
    result = client.complete("s", "u", Answer, stage="s4_trace")

    assert len(prompts) == 2
    assert "previous answer was rejected" in prompts[1]
    assert result.retries == 1
    assert result.parsed(Answer).verdict == "implemented"


def test_a_schema_violation_is_retried_then_raised() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_openai_body('{"verdict": "implemented"}'))

    client = OpenAIClient(_openai_settings(), transport=_transport(handler))
    with pytest.raises(LLMResponseError, match="after 2 attempts"):
        client.complete("s", "u", Answer, stage="s4_trace")


def test_a_failed_call_is_not_cached() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(500)

    client = OpenAIClient(_openai_settings(), transport=_transport(handler))
    with pytest.raises(LLMResponseError):
        client.complete("s", "u")
    with pytest.raises(LLMResponseError):
        client.complete("s", "u")
    assert attempts == 2


def test_the_run_budget_stops_a_runaway_run() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_openai_body("x", prompt_tokens=60, completion_tokens=0))

    client = OpenAIClient(_openai_settings(max_tokens_per_run=100), transport=_transport(handler))
    client.complete("s", "u1")
    client.complete("s", "u2")
    with pytest.raises(LLMBudgetExceeded, match="token budget"):
        client.complete("s", "u3", stage="s3_describe")


def test_cache_hits_do_not_consume_the_budget() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_openai_body("x", prompt_tokens=60, completion_tokens=0))

    client = OpenAIClient(_openai_settings(max_tokens_per_run=100), transport=_transport(handler))
    client.complete("s", "u1")
    for _ in range(10):
        client.complete("s", "u1")
    assert client.call_log.total_tokens == 60


def test_call_rows_carry_ids_and_counts_but_no_text() -> None:
    """ADR-003: statistics are ids and counts only."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_openai_body("some answer text"))

    client = OpenAIClient(_openai_settings(), transport=_transport(handler))
    client.complete("system", "user", stage="s2_extract")
    record = client.call_log.records[0]
    assert record.stage == "s2_extract"
    assert record.provider == "openai"
    assert record.ok is True
    fields = set(type(record).__slots__)
    assert not fields & {"system", "user", "prompt", "text", "response"}


def test_a_transport_failure_is_recorded_as_a_failed_call() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = OpenAIClient(_openai_settings(), transport=_transport(handler))
    with pytest.raises(LLMResponseError):
        client.complete("s", "u", stage="s2_extract")
    record = client.call_log.records[0]
    assert record.ok is False
    assert record.error == "LLMResponseError"


def test_a_shared_cache_serves_two_clients() -> None:
    """A second run reuses the first run's work when the content is unchanged."""
    cache = LLMCache(backend=MemoryCache(), model="test-model", prompt_version="1")
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_openai_body("shared"))

    first = OpenAIClient(_openai_settings(), transport=_transport(handler), cache=cache)
    first.complete("s", "u")
    second = OpenAIClient(_openai_settings(), transport=_transport(handler), cache=cache)
    assert second.complete("s", "u").cached is True
    assert calls == 1


# --- JSON extraction -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        '{"a": 1}',
        '```json\n{"a": 1}\n```',
        '```\n{"a": 1}\n```',
        'Here is the answer:\n{"a": 1}\nHope that helps.',
        '  \n {"a": 1}  ',
    ],
)
def test_json_is_recovered_from_the_shapes_models_actually_emit(text: str) -> None:
    assert extract_json(text) == {"a": 1}


@pytest.mark.parametrize("text", ["no json here", "", "[1, 2, 3]", "{not json}"])
def test_unusable_responses_raise(text: str) -> None:
    with pytest.raises(LLMResponseError):
        extract_json(text)


# --- mock client and factory ----------------------------------------------------------------


def test_the_mock_answers_every_llm_stage_against_its_real_schema() -> None:
    """ADR-014: the whole of Phase 2 runs on this provider, so it must satisfy them.

    All but one. `chat_answer` answers in prose and is never sent through `complete`
    (Phase 8c) — its shape is checked by code after the stream closes rather than by
    the adapter — so it is exercised by the streaming test below instead.
    """
    from greenlight_ai.llm.prompts import PROMPTS
    from greenlight_ai.llm.prompts.chat_answer import CHAT_ANSWER_PROMPT

    client = MockClient()
    for stage, prompt in PROMPTS.items():
        if stage == CHAT_ANSWER_PROMPT.stage:
            continue
        result = client.complete("s", f"u-{stage}", prompt.schema, stage=stage)
        assert result.data is not None
        assert result.parsed(prompt.schema) is not None


def test_the_mock_streams_the_one_prose_stage_in_pieces() -> None:
    """A mock that handed back the whole answer would let the streaming path pass
    on a property it has to earn: that the pieces concatenate to the whole answer."""
    from greenlight_ai.llm.prompts.chat_answer import CITATION_MARKER

    client = MockClient()
    pieces = list(client.stream("s", "u", stage="chat_answer"))
    assert len(pieces) > 1
    assert CITATION_MARKER in "".join(pieces)


def test_a_streamed_answer_is_cached_and_the_second_call_is_a_hit() -> None:
    """The cache is checked before the stream opens, as it is before every call."""
    client = MockClient()
    first = "".join(client.stream("s", "u", stage="chat_answer"))
    second = "".join(client.stream("s", "u", stage="chat_answer"))
    assert first == second
    assert client.call_log.cache_hits == 1


def test_an_abandoned_stream_caches_nothing() -> None:
    """A partial answer is never served to the next person (ADR-069)."""
    client = MockClient()
    stream = client.stream("s", "u", stage="chat_answer")
    next(stream)
    stream.close()
    list(client.stream("s", "u", stage="chat_answer"))
    assert client.call_log.cache_hits == 0


def test_a_stream_that_dies_mid_answer_is_still_recorded() -> None:
    """A call that failed is a call that happened.

    `complete` has always written an `ok=False` row when the transport fails. `stream`
    wrote its row only after the loop finished, so a stream that died mid-answer left no
    trace at all: invisible to the usage and spend screens, and free against the caps
    that are counted from exactly those rows.
    """

    class Dying(MockClient):
        def _send_stream(self, system: str, user: str):  # type: ignore[no-untyped-def]
            yield "The first half of an answer"
            raise LLMError("the endpoint hung up")

    client = Dying()
    with pytest.raises(LLMError):
        list(client.stream("s", "u", stage="chat_answer"))

    (record,) = client.call_log.records
    assert record.ok is False
    assert record.stage == "chat_answer"
    assert record.error == "LLMError"
    assert record.completion_tokens > 0, "what it managed to send is what it spent"


def test_a_reader_that_walks_away_is_still_recorded() -> None:
    """The hole ADR-072 closed, reopened through a different door.

    A caller that stops reading closes the generator, which raises **GeneratorExit** —
    and `GeneratorExit` does not derive from `Exception`. An `except Exception` around
    the streaming loop therefore caught nothing, appended nothing, and never reached the
    success-path record either. Zero `llm_calls` rows.

    That matters because ADR-072 moved the chat's per-run cap onto exactly those rows,
    on the grounds that the transcript was the client's own account and these are the
    server's. A client that asks a question, reads one piece and hangs up spends nothing
    against either cap and appears on no spend screen, while the provider was called and
    the tokens were spent.
    """

    class TwoPiece(MockClient):
        def _send_stream(self, system: str, user: str):  # type: ignore[no-untyped-def]
            yield "hello "
            yield "world"

    client = TwoPiece(LLMSettings())
    stream = client.stream("s", "u", stage="chat_answer")
    assert next(stream) == "hello "
    stream.close()

    (record,) = client.call_log.records
    assert record.ok is False
    assert record.error == "GeneratorExit"
    assert record.stage == "chat_answer"


def test_a_stream_that_dies_caches_nothing() -> None:
    """Recording the failure must not also store the half answer."""

    class Dying(MockClient):
        def _send_stream(self, system: str, user: str):  # type: ignore[no-untyped-def]
            yield "half"
            raise LLMError("the endpoint hung up")

    client = Dying()
    with pytest.raises(LLMError):
        list(client.stream("s", "u", stage="chat_answer"))
    assert client.call_log.cache_hits == 0


def test_the_mock_records_what_it_was_asked() -> None:
    client = MockClient()
    client.complete("system", "user", stage="s2_extract")
    assert client.prompts == [("s2_extract", "system", "user")]


def test_a_registered_responder_overrides_the_canned_answer() -> None:
    client = MockClient()
    client.register_text("s4_trace", '{"verdict": "implemented", "confidence": 0.9}')
    result = client.complete("s", "u", Answer, stage="s4_trace")
    assert result.parsed(Answer).verdict == "implemented"


def test_a_responder_sees_the_prompts() -> None:
    client = MockClient()
    client.register("s4_trace", lambda _s, user: json.dumps({"verdict": user, "confidence": 1.0}))
    result = client.complete("s", "implemented", Answer, stage="s4_trace")
    assert result.parsed(Answer).verdict == "implemented"


def test_the_factory_builds_the_configured_provider() -> None:
    assert isinstance(build_client(LLMSettings()), MockClient)
    assert isinstance(build_client(_openai_settings()), OpenAIClient)
    assert isinstance(build_client(_openai_settings(provider="anthropic")), AnthropicClient)


def test_the_factory_shares_an_injected_cache_and_log() -> None:
    cache = LLMCache(backend=MemoryCache(), model="mock-model", prompt_version="1")
    log = CallLog()
    client = build_client(LLMSettings(), cache=cache, call_log=log)
    client.complete("s", "u", stage="s9_summarize")
    assert len(log.records) == 1
