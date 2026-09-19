"""The single LLM interface and its value objects.

Only :mod:`greenlight_ai.llm` makes network calls to a model (ADR-004). Everything else in the
codebase depends on :class:`LLMClient` and nothing more, which is what allows the
provider to change with a ``.env`` edit and a worker restart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol, Type, TypeVar

from pydantic import BaseModel

__all__ = [
    "LLMError",
    "LLMTimeoutError",
    "LLMResponseError",
    "LLMBudgetExceeded",
    "LLMResult",
    "LLMClient",
    "ModelT",
]

ModelT = TypeVar("ModelT", bound=BaseModel)


class LLMError(Exception):
    """A call to the model failed.

    Never carries prompt text, because an error message reaches the logs and prompts do
    not (ADR-003).
    """


class LLMTimeoutError(LLMError):
    """The model did not answer within ``LLM_TIMEOUT_S``."""


class LLMResponseError(LLMError):
    """The model answered, but the answer could not be used.

    Raised when the transport succeeded and the body was malformed, the schema did not
    validate after the single permitted retry, or the provider returned an error status.
    """


class LLMBudgetExceeded(LLMError):
    """The run's token budget is spent.

    ``LLM_MAX_TOKENS_PER_RUN`` stops a runaway run rather than letting it consume an
    unbounded number of tokens (``docs/design.md`` "LLM cost controls").
    """


@dataclass(frozen=True, slots=True)
class LLMResult:
    """What one completed call returned.

    Attributes:
        text: The raw response text.
        data: The parsed JSON object, when a schema was requested.
        prompt_tokens: Tokens consumed by the prompt, 0 when the provider omits it.
        completion_tokens: Tokens produced, 0 when the provider omits it.
        latency_ms: Wall-clock duration of the call, 0 for a cache hit.
        model: The model that answered.
        cached: Whether this came from the cache instead of the network.
        retries: How many retries were needed; at most 1 (one retry with the validation
            error appended, per ``docs/llm-privacy.md``).
    """

    text: str
    data: Mapping[str, object] | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    model: str = ""
    cached: bool = False
    retries: int = 0

    @property
    def total_tokens(self) -> int:
        """Tokens attributable to this call.

        Returns:
            Prompt plus completion tokens. A cache hit reports 0, because nothing was
            sent, which is what makes the cache visible in the usage numbers.
        """
        return 0 if self.cached else self.prompt_tokens + self.completion_tokens

    def parsed(self, schema: Type[ModelT]) -> ModelT:
        """Validate the parsed JSON against a schema.

        Args:
            schema: The Pydantic model the response must satisfy.

        Returns:
            The validated model instance.

        Raises:
            LLMResponseError: When the call returned no JSON object.
        """
        if self.data is None:
            raise LLMResponseError("response carried no JSON object")
        return schema.model_validate(self.data)


@dataclass(frozen=True, slots=True)
class CallRecord:
    """One row of per-call statistics (the ``llm_calls`` table).

    Carries ids and counts only; never prompt or response text (ADR-003).

    Attributes:
        stage: Which pipeline stage made the call.
        provider: Which client class served it.
        model: The model name.
        prompt_tokens: Tokens consumed by the prompt.
        completion_tokens: Tokens produced.
        latency_ms: Wall-clock duration.
        retries: Retries needed.
        ok: Whether the call ultimately succeeded.
        cached: Whether the cache served it.
        error: The exception class name when it failed, never a message body.
    """

    stage: str
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    retries: int = 0
    ok: bool = True
    cached: bool = False
    error: str = ""


class LLMClient(Protocol):
    """The one interface the pipeline calls.

    Implementations must check the cache before sending anything (ADR-005) and must not
    log prompt text unless ``LLM_LOG_PROMPTS`` is set, which is for synthetic data on a
    developer machine only (ADR-003).
    """

    model: str

    def complete(
        self,
        system: str,
        user: str,
        schema: type[BaseModel] | None = None,
        *,
        stage: str = "",
        prompt_version: str = "",
    ) -> LLMResult:
        """Send one narrow task to the model.

        Args:
            system: The system prompt.
            user: The user prompt: one OSL section, one config block, one pair, one
                finding. Small in, small out (``docs/llm-privacy.md``).
            schema: The Pydantic model the answer must satisfy. When given, the answer is
                JSON-only and is retried once with the validation error appended.
            stage: The pipeline stage, recorded on the call row.
            prompt_version: The prompt template's version, part of the cache key.

        Returns:
            The result, whether it came from the cache or the network.

        Raises:
            LLMError: When the call cannot be completed.
        """
        ...


@dataclass
class CallLog:
    """Collects :class:`CallRecord` rows for one run.

    Phase 2 keeps these in memory behind the same shape the ``llm_calls`` table will
    take in Phase 3, so the pipeline code does not change when the database arrives.

    Attributes:
        records: The rows, in call order.
    """

    records: list[CallRecord] = field(default_factory=list)

    def add(self, record: CallRecord) -> None:
        """Record one call.

        Args:
            record: The row to append.
        """
        self.records.append(record)

    @property
    def total_tokens(self) -> int:
        """Tokens used across every non-cached call.

        Returns:
            The sum of prompt and completion tokens.
        """
        return sum(r.prompt_tokens + r.completion_tokens for r in self.records if not r.cached)

    @property
    def cache_hits(self) -> int:
        """How many calls the cache served.

        Returns:
            The count of cached rows.
        """
        return sum(1 for r in self.records if r.cached)
