"""The failure at length, for somebody trying to trace it (Phase 6.19).

A failed run carries two accounts of what went wrong, and they answer different
questions. ``Run.error`` is one line — *what happened* — and it is what the runs list
shows and what somebody skims. ``Run.error_detail`` is *where it happened*: the stage,
the attempt, and the traceback through this codebase. Nobody reads it on the way past,
so it lives behind a disclosure on the run itself and never in the list.

**Why a traceback is allowed here at all.** ADR-003 keeps delivery content out of logs
and prompts, and a traceback is the one place that rule could be broken by accident: a
frame's message can quote whatever was being parsed. It is safe because of how the
pipeline raises — ``PipelineError`` carries a stage and a reason written in counts and
ids, never a value from a workbook — and because nothing here formats local variables.
What is stored is frames, an exception type, and that reason.

**It is bounded, at both ends.** Where the text is over the cap the **oldest** frames
go, because the innermost call and the exception are at the end and that is the part
somebody needs. The header's copy of the exception message is capped separately: a
message running to thousands of characters would otherwise consume the whole budget and
leave a detail with no frames in it at all.
"""

from __future__ import annotations

import traceback
from typing import Final

from greenlight_ai.db.types import utcnow

__all__ = ["MAX_DETAIL_CHARS", "describe_failure"]

#: What `Run.error_detail` will hold. Generous enough for a deep traceback, small
#: enough that a pathological one cannot bloat the row.
MAX_DETAIL_CHARS: Final[int] = 8000

#: Marks where frames were dropped, so a reader is never shown a trimmed traceback
#: that looks complete.
_ELIDED: Final[str] = "… earlier frames dropped; the innermost call is below …\n\n"

#: How much of the exception message the header repeats. The whole of it is in the
#: traceback below; this line exists to be read at a glance, and a message that runs to
#: thousands of characters would otherwise leave no budget for a single frame.
_MAX_HEADER_MESSAGE: Final[int] = 500


def describe_failure(
    exc: BaseException,
    *,
    run_id: int,
    stage: str = "",
    attempt: int = 0,
    attempts: int = 0,
) -> str:
    """Describe a failed run in enough detail to trace it.

    Args:
        exc: What was raised.
        run_id: The run that failed, so a copied detail identifies itself.
        stage: The pipeline stage, where one is known.
        attempt: Which attempt this was, counting from one. Zero when it does not apply.
        attempts: How many attempts the job is allowed. Zero when it does not apply.

    Returns:
        A header naming the run, stage, time and exception, then the traceback,
        capped at `MAX_DETAIL_CHARS` with the oldest frames dropped first.
    """
    message = str(exc)
    if len(message) > _MAX_HEADER_MESSAGE:
        message = message[:_MAX_HEADER_MESSAGE] + "…"
    header = [
        f"Run {run_id}",
        f"Stage: {stage or 'not reached'}",
        f"Failed at: {utcnow().isoformat(timespec='seconds')}",
        f"Exception: {type(exc).__name__}: {message}",
    ]
    # An attempt of "1 of 1" says the job was not retried, which is worth knowing; a
    # path with no retry policy says nothing rather than inventing one.
    if attempts:
        header.append(f"Attempt: {attempt} of {attempts}")

    trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    preamble = "\n".join(header) + "\n\n"
    budget = MAX_DETAIL_CHARS - len(preamble)
    if len(trace) > budget:
        trace = _ELIDED + trace[-max(0, budget - len(_ELIDED)) :]
    return preamble + trace
