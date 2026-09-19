"""The single LLM adapter (ADR-004).

Only this package makes network calls to a model. Everything else calls
:class:`~vigilai.llm.client.LLMClient` and gets an
:class:`~vigilai.llm.client.LLMResult`. The cache is checked before every call
(ADR-005) and prompts never carry sample rows (ADR-003).
"""

from vigilai.llm.anthropic import AnthropicClient
from vigilai.llm.base import BaseClient, extract_json
from vigilai.llm.cache import (
    CacheBackend,
    CacheEntry,
    LLMCache,
    MemoryCache,
    SqliteCache,
    cache_key,
)
from vigilai.llm.client import (
    CallLog,
    CallRecord,
    LLMBudgetExceeded,
    LLMClient,
    LLMError,
    LLMResponseError,
    LLMResult,
    LLMTimeoutError,
)
from vigilai.llm.factory import build_cache, build_client
from vigilai.llm.mock import MockClient
from vigilai.llm.openai_compat import OpenAIClient
from vigilai.llm.settings import ConfigError, LLMSettings, Provider

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
