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
from typing import Final, Iterator

from pydantic import BaseModel, ValidationError

from greenlight_ai.llm.cache import LLMCache, MemoryCache
from greenlight_ai.llm.client import (
    Sent,
    CallLog,
    CallRecord,
    LLMBudgetExceeded,
    LLMResponseError,
    LLMResult,
)
from greenlight_ai.llm.settings import LLMSettings
from greenlight_ai.llm.tripwire import assert_clean

__all__ = ["BaseClient", "extract_json"]

_LOG: Final = logging.getLogger(__name__)

#: Only one retry is permitted, with the validation error appended
#: (``docs/llm-privacy.md`` "The adapter contract").
MAX_RETRIES: Final[int] = 1

#: Roughly four characters to a token, which is what every provider's own counter
#: approximates for English prose. Used only on the streaming path, where a chunked
#: response carries no usage block: a spend figure that is approximately right is worth
#: more than a zero that is precisely wrong (Phase 8c).
_CHARS_PER_TOKEN: Final[int] = 4


def _estimate_tokens(text: str) -> int:
    """Approximate a token count for text a provider did not count for us.

    Args:
        text: The prompt or the answer.

    Returns:
        The estimate, at least one for any non-empty text so a call never records zero
        tokens and reads as a cache hit in the usage figures.
    """
    if not text:
        return 0
    return max(1, len(text) // _CHARS_PER_TOKEN)


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
        # Latched off by a provider whose endpoint refused a guided request, so a
        # gateway that has never heard of the field costs one wasted call rather than
        # one per stage (Phase 6.21e).
        self._guided_refused = False

    def _guided_wanted(self, schema: type[BaseModel] | None) -> bool:
        """Whether this request should carry the answer's schema.

        Args:
            schema: The answer's shape, when the caller wants one.

        Returns:
            True when there is a schema to send, the setting asks for it, and the
            endpoint has not already refused one this process.
        """
        if schema is None or self.settings.guided_json == "off":
            return False
        return self.settings.guided_json == "on" or not self._guided_refused

    def _guided_refusal(self) -> None:
        """Note that the endpoint refused a guided request.

        Under ``auto`` this stops the client trying again until the next restart; under
        ``on`` an administrator has said they want it, so nothing is latched and the
        refusal surfaces as the error it is.
        """
        if self.settings.guided_json == "auto":
            self._guided_refused = True
            _LOG.info("endpoint refused a schema-guided request; falling back for this process")

    # -- provider hook -------------------------------------------------------------

    @abstractmethod
    def _send(self, system: str, user: str, schema: type[BaseModel] | None = None) -> Sent:
        """Perform one provider-specific request.

        Args:
            system: The system prompt.
            user: The user prompt.
            schema: The answer's shape, when the caller wants one. A provider that can
                ask its endpoint to decode against a schema does so here and says it
                did; one that cannot ignores it and the answer is validated after the
                fact exactly as before (Phase 6.21e).

        Returns:
            What came back, and whether the endpoint was given the schema.

        Raises:
            LLMError: When the request fails.
        """

    def _send_stream(self, system: str, user: str) -> Iterator[str]:
        """Perform one provider-specific request, yielding the answer as it arrives.

        The default sends the ordinary request and yields the whole answer once. That
        is a correct stream of one chunk: every caller sees the same text in the same
        order, and a provider that has no streaming transport is not made to pretend.
        A provider that can stream overrides this.

        Args:
            system: The system prompt.
            user: The user prompt.

        Yields:
            Pieces of the answer, in order.

        Raises:
            LLMError: When the request fails.
        """
        yield self._send(system, user, None).text

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

    def stream(
        self,
        system: str,
        user: str,
        *,
        stage: str = "",
        prompt_version: str = "",
    ) -> Iterator[str]:
        """Send one prose task, yielding the answer as it arrives (Phase 8c).

        **Beside `complete`, not beside the adapter.** The tripwire, the cache check,
        the budget stop and the per-call record are the four things that must happen
        for every call in the product (ADR-004, ADR-005, ADR-018); a second network
        path in `api/` or `chat/` would put all four somewhere they can be forgotten.
        So the only difference between this and :meth:`complete` is that the answer
        arrives in pieces.

        Three consequences worth stating, because each one is a decision:

        - **A cache hit is served whole and immediately.** The cache is checked before
          the stream opens, as it is before every call. A hit yields the stored answer
          in one piece and makes no network call.
        - **A partial answer is never cached.** The result is stored only when the
          generator runs to completion; a caller that stops reading, or a stream that
          raises, leaves nothing behind to be served to the next person.
        - **No schema, and no retry.** This path is for prose. Guided decoding would
          force JSON, and the single-retry contract exists to fix a *validation*
          failure — there is nothing to re-validate here, and re-asking after the
          person has begun reading would replace text on screen.

        Args:
            system: The system prompt.
            user: The user prompt.
            stage: The stage, recorded on the call row.
            prompt_version: The prompt template's version, part of the cache key.

        Yields:
            Pieces of the answer, in order. Concatenated, they are the whole answer.

        Raises:
            LLMBudgetExceeded: When the token budget is already spent.
            LLMError: When the transport fails.
        """
        version = prompt_version or self.settings.prompt_version

        if self.settings.pii_tripwire:
            assert_clean(f"{system}\n{user}", stage=stage)

        content = self._canonical(system, user, None)

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
            yield cached.text
            return

        self._check_budget(stage)
        started = time.time()
        pieces: list[str] = []
        for piece in self._send_stream(system, user):
            pieces.append(piece)
            yield piece

        text = "".join(pieces)
        # Reached only when the generator ran to completion, which is what makes
        # "a partial answer is never cached" a property of the control flow rather
        # than of a flag somebody has to remember to set.
        self.call_log.add(
            CallRecord(
                stage=stage,
                provider=self.provider_name,
                model=self.model,
                prompt_tokens=_estimate_tokens(system) + _estimate_tokens(user),
                completion_tokens=_estimate_tokens(text),
                latency_ms=int((time.time() - started) * 1000),
                cached=False,
                ok=True,
            )
        )
        self.cache.store(content, stage, text, None, version)

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
                sent = self._send(system, attempt_user, schema)
                text = sent.text
                prompt_tokens = sent.prompt_tokens
                completion_tokens = sent.completion_tokens
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
                    guided=sent.guided,
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
