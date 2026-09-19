"""The single LLM adapter (ADR-004).

Only this package makes network calls to a model. Everything else calls
:class:`~greenlight_ai.llm.client.LLMClient` and gets an
:class:`~greenlight_ai.llm.client.LLMResult`. The cache is checked before every call
(ADR-005) and prompts never carry sample rows (ADR-003).
"""

from greenlight_ai.llm.anthropic import AnthropicClient
from greenlight_ai.llm.base import BaseClient, extract_json
from greenlight_ai.llm.cache import (
    CacheBackend,
    CacheEntry,
    LLMCache,
    MemoryCache,
    SqliteCache,
    cache_key,
)
from greenlight_ai.llm.client import (
    CallLog,
    CallRecord,
    LLMBudgetExceeded,
    LLMClient,
    LLMError,
    LLMResponseError,
    LLMResult,
    LLMTimeoutError,
)
from greenlight_ai.llm.factory import build_cache, build_client
from greenlight_ai.llm.mock import MockClient
from greenlight_ai.llm.openai_compat import OpenAIClient
from greenlight_ai.llm.settings import ConfigError, LLMSettings, Provider

__all__ = [
    "AnthropicClient",
    "BaseClient",
    "CacheBackend",
    "CacheEntry",
    "CallLog",
    "CallRecord",
    "ConfigError",
    "LLMBudgetExceeded",
    "LLMCache",
    "LLMClient",
    "LLMError",
    "LLMResponseError",
    "LLMResult",
    "LLMSettings",
    "LLMTimeoutError",
    "MemoryCache",
    "MockClient",
    "OpenAIClient",
    "Provider",
    "SqliteCache",
    "build_cache",
    "build_client",
    "cache_key",
    "extract_json",
]
