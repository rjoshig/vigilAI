"""LLM settings, loaded from the environment and validated at load time.

Configuration fails loudly on bad input, naming the offending key
(standards/python.md). Provider, base URL, model, and limits all come from ``.env``
(ADR-004), so switching environments never edits code.
"""

from __future__ import annotations

import os
from typing import Final, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = ["Provider", "LLMSettings", "ConfigError"]

Provider = Literal["openai", "anthropic", "mock"]

#: Defaults mirror ``.env.example``. Temperature is 0 because extraction must be
#: reproducible: the cache key does not include it, so a varying temperature would make
#: cached and fresh results disagree.
_DEFAULTS: Final[Mapping[str, str]] = {
    "LLM_PROVIDER": "mock",
    "LLM_BASE_URL": "",
    "LLM_API_KEY": "",
    "LLM_MODEL": "mock-model",
    "LLM_MAX_TOKENS": "2000",
    "LLM_TEMPERATURE": "0",
    "LLM_TIMEOUT_S": "120",
    "LLM_MAX_CONCURRENCY": "4",
    "LLM_MAX_TOKENS_PER_RUN": "400000",
    "LLM_LOG_PROMPTS": "false",
    "LLM_PROMPT_VERSION": "1",
}


class ConfigError(Exception):
    """A setting is missing or invalid. Names the key so the fix is obvious."""


class LLMSettings(BaseModel):
    """Everything the adapter needs, validated.

    Attributes:
        provider: Which client to build.
        base_url: The provider's base URL; required for real providers.
        api_key: The credential; never logged.
        model: The model name, part of every cache key.
        max_tokens: Cap on a single completion.
        temperature: Sampling temperature; 0 for reproducibility.
        timeout_s: Per-call timeout.
        max_concurrency: Calls in flight per worker.
        max_tokens_per_run: The run budget; exceeding it stops the run.
        log_prompts: Whether prompt text may be logged. False except for synthetic data
            on a developer machine (ADR-003).
        prompt_version: The global prompt-set version, part of every cache key.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", protected_namespaces=())

    provider: Provider = "mock"
    base_url: str = ""
    api_key: str = ""
    model: str = "mock-model"
    max_tokens: int = Field(default=2000, gt=0)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    timeout_s: float = Field(default=120.0, gt=0)
    max_concurrency: int = Field(default=4, gt=0)
    max_tokens_per_run: int = Field(default=400_000, gt=0)
    log_prompts: bool = False
    prompt_version: str = "1"

    @field_validator("base_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        """Normalise the base URL so path joining is predictable.

        Args:
            value: The configured URL.

        Returns:
            The URL without a trailing slash.
        """
        return value.rstrip("/")

    @model_validator(mode="after")
    def _real_providers_need_an_endpoint(self) -> LLMSettings:
        """Fail at load time rather than on the first call.

        Returns:
            The validated settings.

        Raises:
            ValueError: When a real provider has no base URL or no model.
        """
        if self.provider != "mock":
            if not self.base_url:
                raise ValueError(f"LLM_BASE_URL is required when LLM_PROVIDER={self.provider}")
            if not self.model:
                raise ValueError(f"LLM_MODEL is required when LLM_PROVIDER={self.provider}")
        return self

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> LLMSettings:
        """Build settings from environment variables.

        Args:
            environ: The mapping to read, defaulting to ``os.environ``. Injectable so
                tests never mutate the real environment.

        Returns:
            The validated settings.

        Raises:
            ConfigError: When a value is missing or cannot be parsed, naming the key.
        """
        source = os.environ if environ is None else environ

        def get(key: str) -> str:
            return source.get(key, _DEFAULTS[key]).strip()

        def integer(key: str) -> int:
            raw = get(key)
            try:
                return int(raw)
            except ValueError as exc:
                raise ConfigError(f"{key} must be an integer, got {raw!r}") from exc

        def number(key: str) -> float:
            raw = get(key)
            try:
                return float(raw)
            except ValueError as exc:
                raise ConfigError(f"{key} must be a number, got {raw!r}") from exc

        def boolean(key: str) -> bool:
            raw = get(key).lower()
            if raw in ("true", "1", "yes", "on"):
                return True
            if raw in ("false", "0", "no", "off", ""):
                return False
            raise ConfigError(f"{key} must be a boolean, got {raw!r}")

        provider = get("LLM_PROVIDER").lower()
        if provider not in ("openai", "anthropic", "mock"):
            raise ConfigError(
                f"LLM_PROVIDER must be one of openai, anthropic, mock; got {provider!r}"
            )

        try:
            return cls(
                provider=provider,  # type: ignore[arg-type]
                base_url=get("LLM_BASE_URL"),
                api_key=get("LLM_API_KEY"),
                model=get("LLM_MODEL"),
                max_tokens=integer("LLM_MAX_TOKENS"),
                temperature=number("LLM_TEMPERATURE"),
                timeout_s=number("LLM_TIMEOUT_S"),
                max_concurrency=integer("LLM_MAX_CONCURRENCY"),
                max_tokens_per_run=integer("LLM_MAX_TOKENS_PER_RUN"),
                log_prompts=boolean("LLM_LOG_PROMPTS"),
                prompt_version=get("LLM_PROMPT_VERSION"),
            )
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
