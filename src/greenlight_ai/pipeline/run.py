"""The orchestrator: runs the stages in order, records each, and supports resume.

Each stage writes status and duration, so a retried job restarts at the last good stage
rather than repeating work (``docs/design.md`` "Processing pipeline"). Re-check after a
user edit reruns only stages 5 to 7, none of which calls a model.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Final, Mapping, Sequence

from greenlight_ai.llm.client import LLMBudgetExceeded
from greenlight_ai.pipeline import (
    s1_parse,
    s2_extract,
    s3_describe,
    s4_trace,
    s5_compare,
    s6_reverse,
    s7_reports,
    s8_verify,
    s9_summarize,
)
from greenlight_ai.pipeline.context import (
    RECHECK_STAGES,
    STAGE_ORDER,
    RunContext,
    StageName,
)

__all__ = ["run_pipeline", "recheck", "STAGES", "PipelineError"]

_LOG: Final = logging.getLogger(__name__)

Stage = Callable[[RunContext], None]


class PipelineError(Exception):
    """A stage failed and the run cannot continue.

    Carries the stage name so the UI can show where it stopped and the worker knows
    where a retry resumes.
    """

    # B042 wants every argument forwarded to ``super().__init__``; forwarding alone
    # does not make the round-trip work when the signature differs from the stored
    # args, so ``__reduce__`` below does it and a test asserts it.
    def __init__(self, stage: StageName, reason: str) -> None:  # noqa: B042
        """Initialise the error.

        Args:
            stage: The stage that failed.
            reason: Why, with no file content in the message (ADR-003).
        """
        super().__init__(f"{stage}: {reason}")
        self.stage = stage
        self.reason = reason

    def __reduce__(self) -> tuple[type[PipelineError], tuple[StageName, str]]:
        """Support pickling, since the worker carries failures across processes.

        Returns:
            The callable and arguments needed to rebuild the error.
        """
        return (type(self), (self.stage, self.reason))


#: Every stage, by name.
STAGES: Final[Mapping[StageName, Stage]] = {
    "s1_parse": s1_parse.run,
    "s2_extract": s2_extract.run,
    "s3_describe": s3_describe.run,
    "s4_trace": s4_trace.run,
    "s5_compare": s5_compare.run,
    "s6_reverse": s6_reverse.run,
    "s7_reports": s7_reports.run,
    "s8_verify": s8_verify.run,
    "s9_summarize": s9_summarize.run,
}


def run_pipeline(
    context: RunContext,
    stages: Sequence[StageName] = STAGE_ORDER,
    resume: bool = False,
) -> RunContext:
    """Run the pipeline over a context.

    Args:
        context: The run context.
        stages: Which stages to run, in order. Defaults to all nine.
        resume: When true, stages already marked ``done`` are skipped, so a retried job
            restarts at the last good stage.

    Returns:
        The same context, now carrying rules, elements, traces, and findings.

    Raises:
        PipelineError: When a stage fails. The stage is recorded as failed first, so the
            run's own record says where it stopped.
    """
    for name in stages:
        record = context.record(name)
        if resume and record.status == "done":
            _LOG.info("run %s: skipping %s (already done)", context.run_id, name)
            continue

        stage = STAGES[name]
        record.status = "running"
        log = context.client.call_log  # type: ignore[attr-defined]
        calls_before = len(log.records)
        tokens_before = log.total_tokens
        hits_before = log.cache_hits
        started = time.monotonic()

        try:
            stage(context)
        except NotImplementedError as exc:
            record.status = "skipped"
            record.error = str(exc)
            _LOG.info("run %s: %s skipped (%s)", context.run_id, name, exc)
            continue
        except LLMBudgetExceeded as exc:
            record.status = "failed"
            record.error = str(exc)
            record.duration_ms = int((time.monotonic() - started) * 1000)
            raise PipelineError(name, str(exc)) from exc
        except Exception as exc:
            record.status = "failed"
            record.error = f"{type(exc).__name__}: {exc}"
            record.duration_ms = int((time.monotonic() - started) * 1000)
            _LOG.error("run %s: stage %s failed (%s)", context.run_id, name, type(exc).__name__)
            raise PipelineError(name, record.error) from exc

        record.status = "done"
        record.duration_ms = int((time.monotonic() - started) * 1000)
        record.llm_calls = len(log.records) - calls_before
        record.tokens = log.total_tokens - tokens_before
        record.cache_hits = log.cache_hits - hits_before
        _LOG.info(
            "run %s: %s done in %dms (%d calls, %d cache hits, %d tokens)",
            context.run_id,
            name,
            record.duration_ms,
            record.llm_calls,
            record.cache_hits,
            record.tokens,
        )

    return context


def recheck(context: RunContext) -> RunContext:
    """Rerun only the stages a user edit affects.

    Editing a requirement or a trace link changes what the comparisons see but not what
    the model read, so stages 5 to 7 rerun and the re-check is free
    (``docs/design.md`` "Re-check path").

    **What "free" means, precisely** (ADR-054). Stages 6 and 7 each grew a model call
    after this function was written: the compliance locator (6.15), the programme
    reading (6.18f), a judgment check, and the name locator (6.21a). Every one of them
    is asked only where code failed, and every one is keyed on the artifacts, which a
    re-check does not touch — so on a re-check each is a cache hit (ADR-005). The
    guard below therefore counts **tokens**, not rows: a cache hit is a row in the
    call log and costs nothing, and a guard that counted rows fired on a re-check that
    had behaved perfectly.

    Args:
        context: The run context, with edited rules or traces.

    Returns:
        The context with findings rebuilt.

    Raises:
        PipelineError: When a rerun stage fails.
    """
    log = context.client.call_log  # type: ignore[attr-defined]
    tokens_before = log.total_tokens
    context.findings = [f for f in context.findings if f.review_status != "undecided"]
    context.rules_version += 1

    for name in RECHECK_STAGES:
        context.record(name).status = "pending"
    run_pipeline(context, stages=RECHECK_STAGES)

    spent = log.total_tokens - tokens_before
    if spent:
        # Not a cache hit, so something a re-check reran sent content the first pass
        # did not. That is a defect wherever it comes from: the inputs have not
        # changed, so neither should what is asked of the model.
        _LOG.warning("re-check spent %d tokens; every call it makes must be cached", spent)
    return context
