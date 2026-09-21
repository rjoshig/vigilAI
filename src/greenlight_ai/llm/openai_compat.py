"""OpenAI-compatible client: ``POST {base_url}/chat/completions``.

One endpoint shape covers vLLM, TGI, Ollama, and most in-house gateways, which is why
it is the default for both local development and production (``docs/design.md``
"LLM adapter"). Plain ``httpx``; no vendor SDK, so nothing extra to install in an
air-gapped network (ADR-004).
"""

from __future__ import annotations

import logging
from typing import Any, Final

import httpx

from pydantic import BaseModel

from greenlight_ai.llm.base import BaseClient
from greenlight_ai.llm.client import LLMResponseError, LLMTimeoutError, Sent
from greenlight_ai.llm.settings import LLMSettings

__all__ = ["OpenAIClient"]

_LOG: Final = logging.getLogger(__name__)


class OpenAIClient(BaseClient):
    """Talks to an OpenAI-compatible ``/chat/completions`` endpoint."""

    provider_name = "openai"

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
                network (standards/python.md).
            **kwargs: Passed to :class:`~greenlight_ai.llm.base.BaseClient` (cache, call_log).
        """
        super().__init__(settings, **kwargs)
        headers = {"Content-Type": "application/json"}
        if settings.api_key:
            headers["Authorization"] = f"Bearer {settings.api_key}"
        self._client = httpx.Client(
            base_url=settings.base_url,
            headers=headers,
            timeout=settings.timeout_s,
            transport=transport,
        )

    def _send(self, system: str, user: str, schema: type[BaseModel] | None = None) -> Sent:
        """Post one chat completion.

        Args:
            system: The system prompt.
            user: The user prompt.
            schema: The answer's shape. Sent as ``response_format`` when guided
                decoding is on, so a serving stack that supports it (vLLM does) cannot
                return anything that is not that shape. ``docs/design.md`` has
                recommended this since Phase 2 (Phase 6.21e).

        Returns:
            What came back, and whether the schema was sent.

        Raises:
            LLMTimeoutError: When the endpoint does not answer in time.
            LLMResponseError: When the status is not 2xx or the body is unusable.
        """
        guided = self._guided_wanted(schema)
        payload: dict[str, object] = {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": self.settings.max_tokens,
            "temperature": self.settings.temperature,
        }
        if guided and schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": schema.model_json_schema(),
                    "strict": True,
                },
            }

        response = self._post(payload)
        if guided and response.status_code == 400:
            # A gateway that has never heard of ``response_format`` rejects the whole
            # request. Which field it disliked is not knowable without reading a body
            # that may echo the prompt (ADR-003), so the rule is the simple one: under
            # ``auto``, drop the field, retry once, and stop offering it this process.
            self._guided_refusal()
            if self.settings.guided_json == "auto":
                payload.pop("response_format", None)
                guided = False
                response = self._post(payload)

        if response.status_code >= 400:
            # The body may echo the prompt, so only the status is reported (ADR-003).
            raise LLMResponseError(f"endpoint returned HTTP {response.status_code}")

        try:
            body = response.json()
            choice = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError("response body was not a chat completion") from exc

        usage = body.get("usage") or {}
        return Sent(
            text=str(choice),
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            guided=guided,
        )

    def _post(self, payload: dict[str, object]) -> httpx.Response:
        """Send one request, turning transport failures into :class:`LLMError`.

        Args:
            payload: The chat-completion body.

        Returns:
            The response, whatever its status. The caller decides what a status means,
            because a 400 has two readings when guided decoding is on.

        Raises:
            LLMTimeoutError: When the endpoint does not answer in time.
            LLMResponseError: When the transport fails.
        """
        try:
            return self._client.post("/chat/completions", json=payload)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"no response within {self.settings.timeout_s}s") from exc
        except httpx.HTTPError as exc:
            raise LLMResponseError(f"transport failed: {type(exc).__name__}") from exc

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._client.close()
