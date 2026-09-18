"""Build the configured client. Switching provider is a ``.env`` change (ADR-004)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Final

from vigilai.llm.anthropic import AnthropicClient
from vigilai.llm.cache import LLMCache, MemoryCache, SqliteCache
from vigilai.llm.client import CallLog, LLMClient
from vigilai.llm.mock import MockClient
from vigilai.llm.openai_compat import OpenAIClient
from vigilai.llm.settings import LLMSettings

__all__ = ["build_client", "build_cache"]

_LOG: Final = logging.getLogger(__name__)


def build_cache(settings: LLMSettings, path: Path | None = None) -> LLMCache:
    """Build the stage cache.

    Args:
        settings: The validated settings, supplying the model and prompt version that
            form part of every key.
        path: A SQLite file for a cache that survives between CLI runs. Without it the
            cache is in-process, which still prevents sending the same content twice
            within one run.

    Returns:
        The cache.
    """
    backend = SqliteCache(path) if path is not None else MemoryCache()
    return LLMCache(backend=backend, model=settings.model, prompt_version=settings.prompt_version)


def build_client(
    settings: LLMSettings | None = None,
    cache: LLMCache | None = None,
    call_log: CallLog | None = None,
    **kwargs: Any,
) -> LLMClient:
    """Build the client named by ``LLM_PROVIDER``.

    Args:
        settings: The validated settings; read from the environment when omitted.
        cache: The stage cache; a fresh in-memory cache when omitted.
        call_log: Where call statistics accumulate; a fresh log when omitted.
        **kwargs: Passed to the client, e.g. an httpx ``transport`` in tests.

    Returns:
        A client satisfying :class:`~vigilai.llm.client.LLMClient`.

    Raises:
        ConfigError: When the settings are invalid.
    """
    resolved = settings or LLMSettings.from_env()
    shared = {"cache": cache, "call_log": call_log, **kwargs}
    shared = {k: v for k, v in shared.items() if v is not None}

    _LOG.info(
        "building %s client (model=%s, prompt_version=%s)",
        resolved.provider,
        resolved.model,
        resolved.prompt_version,
    )
    if resolved.provider == "openai":
        return OpenAIClient(resolved, **shared)
    if resolved.provider == "anthropic":
        return AnthropicClient(resolved, **shared)
    return MockClient(resolved, **shared)
