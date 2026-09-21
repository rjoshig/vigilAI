"""Anthropic-style client: ``POST {base_url}/v1/messages``.

Plain ``httpx``, no vendor SDK (ADR-004). The system prompt is a top-level field rather
than a message, which is the one shape difference from the OpenAI-compatible path.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Final

import httpx

from pydantic import BaseModel

from greenlight_ai.llm.base import BaseClient
from greenlight_ai.llm.client import LLMResponseError, LLMTimeoutError, Sent
from greenlight_ai.llm.settings import LLMSettings

__all__ = ["AnthropicClient", "ANTHROPIC_VERSION"]

_LOG: Final = logging.getLogger(__name__)

#: The one tool a guided request offers. The Messages API has no
#: ``response_format``; requiring a single tool is how an answer is constrained to
#: a JSON schema there (Phase 6.21e).
_TOOL: Final[str] = "record_answer"

#: Pinned so a server-side default change cannot alter behaviour silently.
ANTHROPIC_VERSION: Final[str] = "2023-06-01"


class AnthropicClient(BaseClient):
    """Talks to an Anthropic-style ``/v1/messages`` endpoint."""

    provider_name = "anthropic"

    def __init__(
        self,
        settings: LLMSettings,
        transport: httpx.BaseTransport | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialise the client.

        Args:
            settings: The validated settings.
            transport: An httpx transport, injected by tests so no test touches the
                network.
            **kwargs: Passed to :class:`~greenlight_ai.llm.base.BaseClient`.
        """
        super().__init__(settings, **kwargs)
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": ANTHROPIC_VERSION,
        }
        if settings.api_key:
            headers["x-api-key"] = settings.api_key
        self._client = httpx.Client(
            base_url=settings.base_url,
            headers=headers,
            timeout=settings.timeout_s,
            transport=transport,
        )

    def _send(self, system: str, user: str, schema: type[BaseModel] | None = None) -> Sent:
        """Post one message request.

        Args:
            system: The system prompt, sent as the top-level ``system`` field.
            user: The user prompt.
            schema: The answer's shape. Sent as a single tool the model is required to
                call, which is how the Messages API constrains an answer to a JSON
                schema — there is no ``response_format`` here (Phase 6.21e).

        Returns:
            What came back, and whether the schema was sent.

        Raises:
            LLMTimeoutError: When the endpoint does not answer in time.
            LLMResponseError: When the status is not 2xx or the body is unusable.
        """
        guided = self._guided_wanted(schema)
        payload: dict[str, object] = {
            "model": self.settings.model,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "max_tokens": self.settings.max_tokens,
            "temperature": self.settings.temperature,
        }
        if guided and schema is not None:
            payload["tools"] = [
                {
                    "name": _TOOL,
                    "description": "Record the answer in the shape the caller asked for.",
                    "input_schema": schema.model_json_schema(),
                }
            ]
            payload["tool_choice"] = {"type": "tool", "name": _TOOL}

        response = self._post(payload)
        if guided and response.status_code == 400:
            # Which field the endpoint disliked is not knowable without reading a body
            # that may echo the prompt (ADR-003), so the rule is the simple one: under
            # ``auto``, drop the tool, retry once, and stop offering it this process.
            self._guided_refusal()
            if self.settings.guided_json == "auto":
                payload.pop("tools", None)
                payload.pop("tool_choice", None)
                guided = False
                response = self._post(payload)

        if response.status_code >= 400:
            raise LLMResponseError(f"endpoint returned HTTP {response.status_code}")

        try:
            body = response.json()
            blocks = body["content"]
            # A forced tool call answers in ``input`` rather than in a text block, so
            # the JSON is already parsed and is re-serialised for the one validator
            # every provider shares.
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            if not text:
                text = "".join(
                    json.dumps(b.get("input", {}))
                    for b in blocks
                    if b.get("type") == "tool_use" and b.get("name") == _TOOL
                )
        except (ValueError, KeyError, TypeError) as exc:
            raise LLMResponseError("response body was not a messages response") from exc

        usage = body.get("usage") or {}
        return Sent(
            text=text,
            prompt_tokens=int(usage.get("input_tokens", 0)),
            completion_tokens=int(usage.get("output_tokens", 0)),
            guided=guided,
        )

    def _post(self, payload: dict[str, object]) -> httpx.Response:
        """Send one request, turning transport failures into :class:`LLMError`.

        Args:
            payload: The messages body.

        Returns:
            The response, whatever its status. The caller decides what a status means,
            because a 400 has two readings when guided decoding is on.

        Raises:
            LLMTimeoutError: When the endpoint does not answer in time.
            LLMResponseError: When the transport fails.
        """
        try:
            return self._client.post("/v1/messages", json=payload)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"no response within {self.settings.timeout_s}s") from exc
        except httpx.HTTPError as exc:
            raise LLMResponseError(f"transport failed: {type(exc).__name__}") from exc

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._client.close()
