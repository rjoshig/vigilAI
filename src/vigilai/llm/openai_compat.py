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

from vigilai.llm.base import BaseClient
from vigilai.llm.client import LLMResponseError, LLMTimeoutError
from vigilai.llm.settings import LLMSettings

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
            **kwargs: Passed to :class:`~vigilai.llm.base.BaseClient` (cache, call_log).
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

    def _send(self, system: str, user: str) -> tuple[str, int, int]:
        """Post one chat completion.

        Args:
            system: The system prompt.
            user: The user prompt.

        Returns:
            A ``(text, prompt_tokens, completion_tokens)`` triple.

        Raises:
            LLMTimeoutError: When the endpoint does not answer in time.
            LLMResponseError: When the status is not 2xx or the body is unusable.
        """
        payload: dict[str, object] = {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": self.settings.max_tokens,
            "temperature": self.settings.temperature,
        }
        try:
            response = self._client.post("/chat/completions", json=payload)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"no response within {self.settings.timeout_s}s") from exc
        except httpx.HTTPError as exc:
            raise LLMResponseError(f"transport failed: {type(exc).__name__}") from exc

        if response.status_code >= 400:
            # The body may echo the prompt, so only the status is reported (ADR-003).
            raise LLMResponseError(f"endpoint returned HTTP {response.status_code}")

        try:
            body = response.json()
            choice = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError("response body was not a chat completion") from exc

        usage = body.get("usage") or {}
        return (
            str(choice),
            int(usage.get("prompt_tokens", 0)),
            int(usage.get("completion_tokens", 0)),
        )

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._client.close()
