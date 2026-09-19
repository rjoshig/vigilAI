"""Anthropic-style client: ``POST {base_url}/v1/messages``.

Plain ``httpx``, no vendor SDK (ADR-004). The system prompt is a top-level field rather
than a message, which is the one shape difference from the OpenAI-compatible path.
"""

from __future__ import annotations

import logging
from typing import Any, Final

import httpx

from greenlight_ai.llm.base import BaseClient
from greenlight_ai.llm.client import LLMResponseError, LLMTimeoutError
from greenlight_ai.llm.settings import LLMSettings

__all__ = ["AnthropicClient", "ANTHROPIC_VERSION"]

_LOG: Final = logging.getLogger(__name__)

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

    def _send(self, system: str, user: str) -> tuple[str, int, int]:
        """Post one message request.

        Args:
            system: The system prompt, sent as the top-level ``system`` field.
            user: The user prompt.

        Returns:
            A ``(text, input_tokens, output_tokens)`` triple.

        Raises:
            LLMTimeoutError: When the endpoint does not answer in time.
            LLMResponseError: When the status is not 2xx or the body is unusable.
        """
        payload: dict[str, object] = {
            "model": self.settings.model,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "max_tokens": self.settings.max_tokens,
            "temperature": self.settings.temperature,
        }
        try:
            response = self._client.post("/v1/messages", json=payload)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"no response within {self.settings.timeout_s}s") from exc
        except httpx.HTTPError as exc:
            raise LLMResponseError(f"transport failed: {type(exc).__name__}") from exc

        if response.status_code >= 400:
            raise LLMResponseError(f"endpoint returned HTTP {response.status_code}")

        try:
            body = response.json()
            blocks = body["content"]
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        except (ValueError, KeyError, TypeError) as exc:
            raise LLMResponseError("response body was not a messages response") from exc

        usage = body.get("usage") or {}
        return (
            text,
            int(usage.get("input_tokens", 0)),
            int(usage.get("output_tokens", 0)),
        )

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._client.close()
