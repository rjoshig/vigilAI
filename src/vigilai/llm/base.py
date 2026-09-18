"""Shared client behaviour: caching, budget, retry, and call recording.

Every provider inherits this, so the rules that must hold for all of them hold in one
place: check the cache before sending (ADR-005), stop at the run budget, retry once with
the validation error appended, and record a row per call carrying ids and counts only
(ADR-003).
"""

from __future__ import annotations

import json
import logging
import re
import time
from abc import ABC, abstractmethod
from typing import Final

from pydantic import BaseModel, ValidationError

from vigilai.llm.cache import LLMCache, MemoryCache
from vigilai.llm.client import (
    CallLog,
    CallRecord,
    LLMBudgetExceeded,
    LLMResponseError,
    LLMResult,
)
from vigilai.llm.settings import LLMSettings
from vigilai.llm.tripwire import assert_clean

__all__ = ["BaseClient", "extract_json"]

_LOG: Final = logging.getLogger(__name__)

#: Only one retry is permitted, with the validation error appended
#: (``docs/llm-privacy.md`` "The adapter contract").
MAX_RETRIES: Final[int] = 1

#: Matches a ```json fenced block, which mid-size models emit even when told not to.
_FENCE_RE: Final = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def extract_json(text: str) -> dict[str, object]:
    """Read a JSON object out of a model response.

    Mid-size models wrap JSON in prose or a code fence even when instructed not to.
    Recovering from that here is cheaper and more predictable than spending the single
    retry on it.

    Args:
        text: The raw response.

    Returns:
        The decoded object.

    Raises:
        LLMResponseError: When no JSON object can be found or it does not decode.
    """
    candidate = text.strip()
    fenced = _FENCE_RE.search(candidate)
    if fenced:
        candidate = fenced.group(1).strip()
    if not candidate.startswith("{"):
        start, end = candidate.find("{"), candidate.rfind("}")
        if start == -1 or end <= start:
            raise LLMResponseError("response contained no JSON object")
        candidate = candidate[start : end + 1]
    try:
        decoded = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise LLMResponseError(f"response was not valid JSON ({exc.msg})") from exc
    if not isinstance(decoded, dict):
        raise LLMResponseError("response JSON was not an object")
    return decoded


class BaseClient(ABC):
    """Cache, budget, retry, and recording around a provider-specific request.

    Attributes:
        settings: The validated adapter settings.
        cache: The stage cache, checked before every call.
        call_log: Where per-call statistics accumulate.
    """

    #: Name recorded on call rows, set by each subclass.
    provider_name: str = "base"

    def __init__(
        self,
        settings: LLMSettings,
        cache: LLMCache | None = None,
        call_log: CallLog | None = None,
    ) -> None:
        """Initialise the client.

        Args:
            settings: The validated settings.
            cache: The stage cache. Defaults to a fresh in-memory cache, which still
                satisfies "never send the same content twice" within one run.
            call_log: Where to record call statistics. Defaults to a fresh log.
        """
        self.settings = settings
        self.model = settings.model
        self.cache = cache or LLMCache(
            backend=MemoryCache(),
            model=settings.model,
            prompt_version=settings.prompt_version,
        )
        self.call_log = call_log or CallLog()

    # -- provider hook -------------------------------------------------------------

    @abstractmethod
    def _send(self, system: str, user: str) -> tuple[str, int, int]:
        """Perform one provider-specific request.

        Args:
            system: The system prompt.
            user: The user prompt.

        Returns:
            A ``(text, prompt_tokens, completion_tokens)`` triple.

        Raises:
            LLMError: When the request fails.
        """

    # -- the one public entry point -------------------------------------------------

    def complete(
        self,
        system: str,
        user: str,
        schema: type[BaseModel] | None = None,
        *,
        stage: str = "",
        prompt_version: str = "",
    ) -> LLMResult:
        """Send one narrow task, or serve it from the cache.

        Args:
            system: The system prompt.
            user: The user prompt.
            schema: The Pydantic model the answer must satisfy.
            stage: The pipeline stage, recorded on the call row.
            prompt_version: The prompt template's version, part of the cache key.

        Returns:
            The result.

        Raises:
            LLMBudgetExceeded: When the run's token budget is already spent.
            LLMResponseError: When the answer fails validation after the single retry.
            LLMError: When the transport fails.
        """
        version = prompt_version or self.settings.prompt_version

        # The backstop for ADR-003. Masking happens at parse time, so nothing should
        # reach here; this catches the case where a new stage, a fixture, or a parser
        # change lets something through. Checked before the cache, so the answer does
        # not depend on whether this content was seen before.
        if self.settings.pii_tripwire:
            assert_clean(f"{system}\n{user}", stage=stage)

        content = self._canonical(system, user, schema)

        cached = self.cache.lookup(content, version)
        if cached is not None:
            self.call_log.add(
                CallRecord(
                    stage=stage,
                    provider=self.provider_name,
                    model=self.model,
                    cached=True,
                    ok=True,
                )
            )
            return LLMResult(text=cached.text, data=cached.data, model=self.model, cached=True)

        self._check_budget(stage)
        if self.settings.log_prompts:
            # ADR-003: synthetic data on a developer machine only.
            _LOG.warning("LLM_LOG_PROMPTS is on; stage=%s system=%r user=%r", stage, system, user)

        result = self._send_with_retry(system, user, schema, stage, version)
        self.cache.store(content, stage, result.text, result.data, version)
        return result

    # -- internals -------------------------------------------------------------------

    def _canonical(self, system: str, user: str, schema: type[BaseModel] | None) -> str:
        """Build the canonical content string for the cache key.

        The schema name is included because the same prompt asked for a different output
        shape is a different call, and reusing the old answer would silently return the
        wrong shape.

        Args:
            system: The system prompt.
            user: The user prompt.
            schema: The requested output schema, if any.

        Returns:
            The canonical string.
        """
        return json.dumps(
            {
                "system": system,
                "user": user,
                "schema": schema.__name__ if schema is not None else None,
                "max_tokens": self.settings.max_tokens,
                "temperature": self.settings.temperature,
            },
            sort_keys=True,
            ensure_ascii=False,
        )

    def _check_budget(self, stage: str) -> None:
        """Stop the run when its token budget is spent.

        Args:
            stage: The stage about to call, named in the error.

        Raises:
            LLMBudgetExceeded: When the budget is already reached.
        """
        used = self.call_log.total_tokens
        if used >= self.settings.max_tokens_per_run:
            raise LLMBudgetExceeded(
                f"run token budget of {self.settings.max_tokens_per_run} reached "
                f"({used} used) before stage {stage or 'unknown'}"
            )

    def _send_with_retry(
        self,
        system: str,
        user: str,
        schema: type[BaseModel] | None,
        stage: str,
        version: str,
    ) -> LLMResult:
        """Send, validate, and retry once with the validation error appended.

        Args:
            system: The system prompt.
            user: The user prompt.
            schema: The output schema, if any.
            stage: The pipeline stage.
            version: The prompt version, recorded for debugging.

        Returns:
            The validated result.

        Raises:
            LLMResponseError: When validation still fails after the retry.
            LLMError: When the transport fails.
        """
        attempt_user = user
        last_error: str = ""
        for attempt in range(MAX_RETRIES + 1):
            started = time.monotonic()
            try:
                text, prompt_tokens, completion_tokens = self._send(system, attempt_user)
            except Exception as exc:
                self.call_log.add(
                    CallRecord(
                        stage=stage,
                        provider=self.provider_name,
                        model=self.model,
                        latency_ms=int((time.monotonic() - started) * 1000),
                        retries=attempt,
                        ok=False,
                        error=type(exc).__name__,
                    )
                )
                raise
            latency_ms = int((time.monotonic() - started) * 1000)

            data: dict[str, object] | None = None
            if schema is not None:
                try:
                    data = extract_json(text)
                    schema.model_validate(data)
                except (LLMResponseError, ValidationError) as exc:
                    last_error = _short_error(exc)
                    self.call_log.add(
                        CallRecord(
                            stage=stage,
                            provider=self.provider_name,
                            model=self.model,
                            prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens,
                            latency_ms=latency_ms,
                            retries=attempt,
                            ok=False,
                            error=type(exc).__name__,
                        )
                    )
                    if attempt >= MAX_RETRIES:
                        raise LLMResponseError(
                            f"stage {stage or 'unknown'} (prompt v{version}) returned JSON that "
                            f"failed validation after {attempt + 1} attempts: {last_error}"
                        ) from exc
                    _LOG.info(
                        "stage=%s schema validation failed, retrying once (attempt %d)",
                        stage,
                        attempt + 1,
                    )
                    attempt_user = (
                        f"{user}\n\nYour previous answer was rejected: {last_error}\n"
                        "Return only the corrected JSON object."
                    )
                    continue

            self.call_log.add(
                CallRecord(
                    stage=stage,
                    provider=self.provider_name,
                    model=self.model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    latency_ms=latency_ms,
                    retries=attempt,
                    ok=True,
                )
            )
            return LLMResult(
                text=text,
                data=data,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                model=self.model,
                retries=attempt,
            )
        raise LLMResponseError("unreachable: retry loop exited without a result")


def _short_error(exc: Exception) -> str:
    """Summarise a validation failure for the retry prompt.

    Kept short so the retry prompt stays small, and free of any response content beyond
    the field names that failed.

    Args:
        exc: The validation error.

    Returns:
        A one-line summary.
    """
    if isinstance(exc, ValidationError):
        parts = [
            f"{'.'.join(str(p) for p in error['loc'])}: {error['msg']}"
            for error in exc.errors()[:3]
        ]
        return "; ".join(parts)
    return str(exc)
