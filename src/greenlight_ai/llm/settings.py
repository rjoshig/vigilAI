"""LLM settings, loaded from the environment and validated at load time.

Configuration fails loudly on bad input, naming the offending key
(standards/python.md). Provider, base URL, model, and limits all come from ``.env``
(ADR-004), so switching environments never edits code.
"""

from __future__ import annotations

import os
from typing import Any, Final, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = ["Provider", "LLMSettings", "ConfigError", "resolved_llm_settings"]

Provider = Literal["openai", "anthropic", "mock"]

#: Whether the answer's schema is sent with the request (Phase 6.21e).
GuidedJson = Literal["off", "auto", "on"]
GUIDED_JSON: Final[tuple[GuidedJson, ...]] = ("off", "auto", "on")

#: Defaults mirror ``.env.example``. Temperature is 0 because extraction must be
#: reproducible: the same inputs must produce the same findings. It *is* part of the
#: cache key — ``BaseClient._canonical`` puts it in the hashed content — so changing it
#: re-asks everything rather than silently mixing settings.
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
    "LLM_GUIDED_JSON": "auto",
    "LLM_LOG_PROMPTS": "false",
    "LLM_PII_TRIPWIRE": "true",
    "LLM_PROMPT_VERSION": "1",
    # Stage 8 reads a high-severity finding through these lenses, independently
    # (Phase 6.11e). "single" is the one second opinion the tool has always made, and
    # it stays the default until the benchmark harness (6.11b) measures the three
    # against it on the golden set: a change to what reviewers see has to be a
    # measured change. An empty value turns verification off entirely, which the run
    # reports as a notice rather than passing over in silence.
    "LLM_VERIFY_LENSES": "single",
    "LLM_MAX_LENS_CALLS_PER_RUN": "150",
    "LLM_MAX_ATTRIBUTE_CALLS_PER_RUN": "20",
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
        guided_json: Whether to send the answer's schema with the request so the
            endpoint decodes against it (Phase 6.21e). ``auto`` degrades silently
            on an endpoint that refuses it.
        log_prompts: Whether prompt text may be logged. False except for synthetic data
            on a developer machine (ADR-003).
        pii_tripwire: Whether to scan every assembled prompt for personal data and
            refuse to send it on a match. On by default and left on: it is the backstop
            for masking, and a prompt already sent cannot be recalled.
        prompt_version: The global prompt-set version, part of every cache key.
        verify_lenses: Which lenses read a high-severity finding in stage 8
            (Phase 6.11e). ``("single",)`` is the one second opinion the tool has
            always made; naming lenses (``delivery``, ``compliance``,
            ``requirements``) has each read the same evidence independently and code
            merge the answers. Empty turns verification off, which the run reports.
        max_attribute_calls_per_run: A soft ceiling on attribute lookups. Past it the
            run stops asking and says what it did not look for.
        max_lens_calls_per_run: A ceiling on lens calls, beside the token budget. Past
            it the remaining findings are left unverified and the run says so.
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
    pii_tripwire: bool = True
    guided_json: GuidedJson = "auto"
    prompt_version: str = "1"
    verify_lenses: tuple[str, ...] = ("single",)
    max_lens_calls_per_run: int = Field(default=150, ge=0)
    #: How many times a run may ask the model which column an attribute is
    #: (Phase 6.22d). A soft limit inside the token ceiling: past it the run stops
    #: asking and names what it did not look for, and nothing is refused.
    max_attribute_calls_per_run: int = Field(default=20, ge=0)

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

        def lenses(key: str) -> tuple[str, ...]:
            return parse_lenses(get(key), key)

        def guided(key: str) -> GuidedJson:
            raw = get(key).lower()
            if raw not in GUIDED_JSON:
                raise ConfigError(f"{key} must be one of {', '.join(GUIDED_JSON)}; got {raw!r}")
            return raw

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
                pii_tripwire=boolean("LLM_PII_TRIPWIRE"),
                guided_json=guided("LLM_GUIDED_JSON"),
                prompt_version=get("LLM_PROMPT_VERSION"),
                verify_lenses=lenses("LLM_VERIFY_LENSES"),
                max_lens_calls_per_run=integer("LLM_MAX_LENS_CALLS_PER_RUN"),
                max_attribute_calls_per_run=integer("LLM_MAX_ATTRIBUTE_CALLS_PER_RUN"),
            )
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc


#: The lenses a deployment may switch on (Phase 6.11e). ``single`` is the one-prompt
#: second opinion and stands alone.
LENS_NAMES: Final[frozenset[str]] = frozenset({"single", "delivery", "compliance", "requirements"})


def _guided(value: object) -> GuidedJson:
    """Read the console's setting, falling back rather than failing.

    Args:
        value: Whatever the settings store holds for ``llm.guided_json``.

    Returns:
        The mode. An unrecognised value reads as ``"auto"``: a setting nobody can spell
        is not a reason to stop a run, and ``auto`` degrades on its own.
    """
    raw = str(value).strip().lower()
    return raw if raw in GUIDED_JSON else "auto"


def parse_lenses(raw: str, key: str = "LLM_VERIFY_LENSES") -> tuple[str, ...]:
    """Read a comma-separated lens list, from the environment or the console.

    One parser for both layers, because the console and ``.env`` must agree on what a
    valid value is: a lens list the console accepted and the worker refused would be a
    setting that lies (ADR-023).

    Args:
        raw: The value as written, e.g. ``"delivery,compliance"``.
        key: What to call it in an error.

    Returns:
        The lens names, in the order given. Empty when nothing was written, which stage 8
        reads as verification switched off.

    Raises:
        ConfigError: When a name is unknown, or ``single`` is combined with another.
    """
    lowered = raw.strip().lower()
    if not lowered:
        return ()
    names = tuple(part.strip() for part in lowered.split(",") if part.strip())
    unknown = [name for name in names if name not in LENS_NAMES]
    if unknown:
        raise ConfigError(
            f"{key} may name only {', '.join(sorted(LENS_NAMES))}; got {', '.join(unknown)}"
        )
    if "single" in names and len(names) > 1:
        raise ConfigError(f"{key}: 'single' is the one-prompt mode and stands alone")
    return names


def resolved_llm_settings(session: Any, environ: Mapping[str, str] | None = None) -> LLMSettings:
    """Build adapter settings with the admin console's overrides applied (ADR-023).

    Precedence is the console, then the environment, then the built-in default. This
    is a function rather than a module constant on purpose: a value read once at
    import time is fixed for the life of the process, which is the usual reason a
    runtime setting turns out not to be one.

    Args:
        session: An open database session.
        environ: The environment to read, defaulting to the real one.

    Returns:
        The validated settings.
    """
    from greenlight_ai.config.store import read_secret, resolve

    def value(key: str) -> Any:
        return resolve(session, key, environ).value

    return LLMSettings(
        provider=value("llm.provider"),
        base_url=str(value("llm.base_url")),
        api_key=read_secret(session, "llm.api_key", environ),
        model=str(value("llm.model")),
        max_tokens=int(value("llm.max_tokens")),
        temperature=float(value("llm.temperature_pct")) / 100.0,
        timeout_s=float(value("llm.timeout_s")),
        max_concurrency=int(value("llm.max_concurrency")),
        max_tokens_per_run=int(value("llm.max_tokens_per_run")),
        log_prompts=bool(value("llm.log_prompts")),
        pii_tripwire=bool(value("llm.pii_tripwire")),
        guided_json=_guided(value("llm.guided_json")),
        prompt_version=LLMSettings.from_env(environ).prompt_version,
        # Both were built in 6.11e and dropped here, so a deployment with the database
        # reachable ran with the lenses pinned to ``single`` whatever ``.env`` said.
        verify_lenses=parse_lenses(str(value("llm.verify_lenses")), "llm.verify_lenses"),
        max_lens_calls_per_run=int(value("llm.max_lens_calls_per_run")),
        max_attribute_calls_per_run=int(value("llm.max_attribute_calls_per_run")),
    )
