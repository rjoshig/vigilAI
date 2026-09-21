"""The long form of a failure: enough to trace it, bounded, and free of delivery data."""

from __future__ import annotations

from greenlight_ai.pipeline.run import PipelineError
from greenlight_ai.worker.diagnostics import MAX_DETAIL_CHARS, describe_failure


def _raised() -> PipelineError:
    """A PipelineError with a real traceback behind it.

    Returns:
        The error, caught rather than constructed, so it carries frames.
    """
    try:
        raise PipelineError("s4_trace", "3 requirements did not resolve")
    except PipelineError as exc:
        return exc


def test_it_names_the_run_the_stage_and_the_exception() -> None:
    """The four things somebody needs before they read a single frame."""
    detail = describe_failure(_raised(), run_id=42, stage="s4_trace")

    assert "Run 42" in detail
    assert "Stage: s4_trace" in detail
    assert "PipelineError" in detail
    assert "3 requirements did not resolve" in detail


def test_it_carries_the_traceback_through_this_codebase() -> None:
    """Which is the whole point: the one-line error already said what happened."""
    detail = describe_failure(_raised(), run_id=1, stage="s4_trace")

    assert "Traceback (most recent call last)" in detail
    assert "test_diagnostics.py" in detail


def test_the_attempt_is_shown_only_where_there_is_a_retry_policy() -> None:
    """ "Attempt 1 of 1" is worth knowing; an invented attempt is not."""
    with_retries = describe_failure(_raised(), run_id=1, stage="s1_parse", attempt=2, attempts=3)
    without = describe_failure(_raised(), run_id=1, stage="s1_parse")

    assert "Attempt: 2 of 3" in with_retries
    assert "Attempt" not in without


def test_a_stage_that_was_never_reached_says_so_rather_than_being_blank() -> None:
    """A blank field reads as a bug in the console rather than as a fact."""
    assert "Stage: not reached" in describe_failure(_raised(), run_id=1)


def test_it_is_capped_and_keeps_the_end_where_it_has_to_choose() -> None:
    """A parser that quotes what it choked on can raise something enormous.

    The end is what matters — the innermost call and the exception are there — so a
    detail over the cap loses its oldest frames and says that it did.
    """
    try:
        raise PipelineError("s1_parse", "x" * (MAX_DETAIL_CHARS * 2))
    except PipelineError as exc:
        detail = describe_failure(exc, run_id=7, stage="s1_parse")

    assert len(detail) <= MAX_DETAIL_CHARS
    # The header survives whole, which is the part read at a glance.
    assert "Run 7" in detail
    assert "Stage: s1_parse" in detail
    # The reader is told rather than shown a trimmed traceback that looks complete.
    assert "earlier frames dropped" in detail


def test_a_vast_exception_message_cannot_crowd_out_the_frames() -> None:
    """The header quotes the message; the message must not become the whole detail."""
    try:
        raise PipelineError("s1_parse", "y" * (MAX_DETAIL_CHARS * 2))
    except PipelineError as exc:
        detail = describe_failure(exc, run_id=7, stage="s1_parse")

    header = detail.split("\n\n", 1)[0]
    assert len(header) < 1000, "the header must stay readable whatever was raised"
    assert detail.count("y") > 100, "and the message itself is still there to read"
