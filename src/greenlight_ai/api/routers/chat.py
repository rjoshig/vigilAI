"""Ask the frozen report: two endpoints, one run, nothing stored (Phase 8).

`GET /runs/{id}/chat` says what the panel may show before it is asked anything — the
greeting code writes, the starter questions code builds from this run's pack, the caps
in force and how much of them is left. It costs no model call.

`POST /runs/{id}/chat` answers one question. The prose streams; the citations are
checked against the pack when the stream closes and only the ones that resolve are sent.

**Five independent things keep one person's context out of another's conversation**
(Phase 8d), and each one would be enough on its own:

1. **The pack is built here, from the run id.** The client sends a question and a
   transcript. Neither can add a fact, because facts come only from the pack.
2. **The endpoint refuses anyone who may not read that run**, by the same dependency
   that already guards the report.
3. **Nothing is stored**, so there is no cross-person store to leak from.
4. **A cache hit cannot cross a boundary.** The cache is content-addressed and the
   pack's hash is part of the prompt version, so a hit requires the question *and* the
   pack to be byte-identical — the same run and the same data the asker could see.
5. **The transcript is component state in the browser**, cleared when the panel
   unmounts, so a shared machine does not hand the next person the last one's
   questions.

The one real injection surface is named rather than left implicit: a client can forge a
transcript. It buys nothing. Forged text arrives inside a block labelled as a record of
what was said, and the facts it might contradict were assembled by code from the
database — which the prompt says wins.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any, Final, Iterator

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from greenlight_ai.api.deps import CurrentUser, current_user, get_data_dir, get_session
from greenlight_ai.chat import answer as answer_module
from greenlight_ai.chat.pack import RunPack, build_pack, greeting, starters
from greenlight_ai.chat.settings import ChatSettings, chat_settings
from greenlight_ai.db import cache as call_cache
from greenlight_ai.db import models
from greenlight_ai.db.types import utcnow
from greenlight_ai.llm.cache import LLMCache
from greenlight_ai.llm.client import CallLog, LLMError
from greenlight_ai.llm.factory import build_client
from greenlight_ai.llm.settings import resolved_llm_settings

__all__ = ["router"]

_LOG: Final = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

#: The one thing the panel is told it cannot see, in the words it shows a person.
#: Stated here rather than in the UI so the sentence and the rule cannot drift.
CANNOT_SEE: Final[str] = (
    "It reads what the tool derived from your files — findings, coverage, rules and "
    "counts — never the rows or the cell values in them."
)

#: What the panel says about what it changes and what it keeps, for the same reason.
CHANGES_NOTHING: Final[str] = (
    "It cannot change a decision, raise a finding or re-open this report; everything "
    "it does is read."
)
NOT_SAVED: Final[str] = (
    "The conversation is not saved. It is gone when you close this panel, so copy "
    "anything you want to keep."
)


class ChatQuestion(BaseModel):
    """One question and the conversation it belongs to.

    The transcript comes from the browser because nothing is stored server-side, and its
    length is capped here as well as in the panel so an oversized body is refused before
    anything is assembled.

    **The per-run question cap is not counted from it.** Counting the transcript meant
    counting what the client chose to send: an empty one reset the conversation's count
    and the cap meant nothing. It is counted from `llm_calls` instead, against this run
    and this person — the same rows the daily cap already uses, which are written by the
    server and cannot be argued with.
    """

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2000)
    #: Earlier turns as ``{"who": "You"|"Assistant", "text": ...}``, oldest first.
    transcript: list[dict[str, str]] = Field(default_factory=list, max_length=60)


class ChatCitation(BaseModel):
    """One checked citation, as the panel draws it."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    label: str
    anchor: str = ""


class ChatOpening(BaseModel):
    """What the panel shows before anybody asks anything.

    Every field is produced by code. A greeting written by the model would be the
    first thing a person read and the one sentence nothing had checked.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    #: Why not, when it is available to the deployment but not to this run or person.
    unavailable_reason: str = ""
    greeting: str = ""
    starters: list[str] = Field(default_factory=list)
    cannot_see: str = CANNOT_SEE
    changes_nothing: str = CHANGES_NOTHING
    not_saved: str = NOT_SAVED
    #: What was left out of the context to fit, said rather than hidden.
    trimmed: list[str] = Field(default_factory=list)
    aggregates_included: bool = False
    max_questions_per_run: int = 0
    #: How many of those are left for this person on this run, so the panel can say so
    #: before somebody writes a question it will refuse.
    questions_left_on_this_run: int = 0
    questions_left_today: int = 0


def _run_or_404(session: Session, run_id: int) -> models.Run:
    """Fetch a run or refuse.

    Args:
        session: The request's session.
        run_id: The run.

    Returns:
        The run row.

    Raises:
        HTTPException: 404 when it does not exist — the same refusal the report gives,
            so a run somebody may not read is indistinguishable from one that is not
            there.
    """
    run = session.get(models.Run, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"run {run_id} not found")
    return run


def _frozen_or_refuse(session: Session, run: models.Run) -> None:
    """Refuse a run whose report has not been frozen.

    Only frozen runs. A conversation whose context shifts as decisions are made would
    produce answers that were true when given and are not now, and a model that
    appeared to advise a verdict is exactly what this tool keeps to people and code.

    Args:
        session: The request's session.
        run: The run.

    Raises:
        HTTPException: 409 when there is no frozen report.
    """
    exists = session.execute(
        sa.select(sa.func.count())
        .select_from(models.FinalReport)
        .where(models.FinalReport.run_id == run.id)
    ).scalar_one()
    if not exists:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"run {run.id} has no frozen report; the chat answers about finished reports only",
        )


def _asked_about(session: Session, run_id: int, user_id: int | None) -> int:
    """How many questions this person has already asked about this run.

    Read from `llm_calls` rather than from the transcript the browser sent. The
    transcript was the client's own account of how long the conversation was, so a
    client that sent an empty one started again from zero and the per-run cap an
    administrator set was a suggestion. These rows are the server's.

    Nothing is stored about a conversation and nothing here changes that: a call row
    already exists for every call in the product, and it says which run and which person
    without saying anything about what was asked (ADR-070).

    Args:
        session: The request's session.
        run_id: The run being asked about.
        user_id: The asker.

    Returns:
        The count, cache hits included, for the same reason the daily count includes
        them: a question answered from the cache still used the feature.
    """
    if user_id is None:
        return 0
    return int(
        session.execute(
            sa.select(sa.func.count())
            .select_from(models.LlmCall)
            .where(
                models.LlmCall.stage == answer_module.STAGE,
                models.LlmCall.run_id == run_id,
                models.LlmCall.user_id == user_id,
            )
        ).scalar_one()
    )


def _asked_today(session: Session, user_id: int | None) -> int:
    """How many questions this person has asked in the last day.

    Counted from `llm_calls`, which is where every call in the product is already
    recorded, rather than from a store of its own — a second count is a second thing
    that can be wrong about the same fact.

    Args:
        session: The request's session.
        user_id: The asker.

    Returns:
        The count. Cache hits are included: a question answered from the cache still
        used the feature, and a person who could ask the same thing fifty times for
        free would find the cap does not mean what it says.
    """
    if user_id is None:
        return 0
    since = utcnow() - dt.timedelta(days=1)
    return int(
        session.execute(
            sa.select(sa.func.count())
            .select_from(models.LlmCall)
            .where(
                models.LlmCall.stage == answer_module.STAGE,
                models.LlmCall.user_id == user_id,
                models.LlmCall.created_at >= since,
            )
        ).scalar_one()
    )


def _pack_for(session: Session, run: models.Run, settings: ChatSettings, data_dir: Any) -> RunPack:
    """Build the pack, here and nowhere else.

    Args:
        session: The request's session.
        run: The run.
        settings: The chat settings, which decide whether 8g's aggregates are in it.
        data_dir: The shared volume, so the frozen report's own text can be quoted.

    Returns:
        The pack.
    """
    return build_pack(session, run.id, settings, data_dir)


@router.get("/runs/{run_id}/chat", response_model=ChatOpening)
def chat_opening(
    run_id: int,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
    data_dir: Any = Depends(get_data_dir),
) -> ChatOpening:
    """What the panel shows before anybody asks anything.

    Costs no model call. A deployment with the chat off gets ``enabled: false`` and
    nothing else, so a client that draws the launcher from this cannot draw one for a
    feature that is turned off.

    Args:
        run_id: The run.
        session: The request's session.
        user: The caller.
        data_dir: The shared volume.

    Returns:
        The greeting, the starters, and what the panel must say about its own limits.
    """
    settings = chat_settings(session)
    if not settings.enabled:
        return ChatOpening(enabled=False, unavailable_reason="The report chat is switched off.")

    run = _run_or_404(session, run_id)
    frozen = session.execute(
        sa.select(sa.func.count())
        .select_from(models.FinalReport)
        .where(models.FinalReport.run_id == run.id)
    ).scalar_one()
    if not frozen:
        return ChatOpening(
            enabled=False,
            unavailable_reason="This run has no frozen report yet.",
        )

    left = max(0, settings.max_questions_per_day - _asked_today(session, user.id))
    if settings.max_questions_per_day == 0 or left == 0:
        return ChatOpening(
            enabled=False,
            unavailable_reason=(
                "The report chat is not available to you yet."
                if settings.max_questions_per_day == 0
                else "You have reached today's limit of questions."
            ),
            questions_left_today=0,
        )

    # The per-run cap is answerable here now that it is counted from the call rows
    # rather than from a transcript only the POST body carries. Its own help line says
    # "reached, the panel says so rather than failing" — which was not true of a cap the
    # opening could not see: the launcher appeared, the person typed, and the refusal
    # arrived after they had written the question.
    asked_here = _asked_about(session, run.id, user.id)
    if asked_here >= settings.max_questions_per_run:
        return ChatOpening(
            enabled=False,
            unavailable_reason=(
                f"You have asked {settings.max_questions_per_run} questions about this "
                "report, which is the limit an administrator has set."
            ),
            questions_left_today=left,
        )

    pack = _pack_for(session, run, settings, data_dir)
    return ChatOpening(
        enabled=True,
        greeting=greeting(pack),
        starters=starters(pack),
        trimmed=list(pack.trimmed),
        aggregates_included=pack.aggregates_included,
        max_questions_per_run=settings.max_questions_per_run,
        questions_left_on_this_run=max(0, settings.max_questions_per_run - asked_here),
        questions_left_today=left,
    )


def _events(
    session: Session,
    run: models.Run,
    payload: ChatQuestion,
    settings: ChatSettings,
    user: CurrentUser,
    data_dir: Any,
    cache_backend: Any,
) -> Iterator[bytes]:
    """Stream one answer as newline-delimited JSON events.

    Newline-delimited JSON rather than server-sent events: the panel is a `fetch`
    reading a body, not an `EventSource`, and NDJSON needs no framing rules of its own
    to get wrong. Two kinds of event — `delta` for prose and one `done` at the end —
    plus `error`, which is an event rather than a status because by the time a stream
    fails the status line is long gone.

    Args:
        session: The request's session.
        run: The run.
        payload: The question and the transcript.
        settings: The chat settings.
        user: The asker.
        data_dir: The shared volume.
        cache_backend: The shared cache store, so an identical question about an
            identical pack is served whole from it and makes no network call.

    Yields:
        One JSON object per line.
    """
    pack = _pack_for(session, run, settings, data_dir)
    call_log = CallLog()
    llm = resolved_llm_settings(session)
    if settings.model:
        llm = llm.model_copy(update={"model": settings.model})
    llm = llm.model_copy(
        update={
            "max_tokens": settings.max_tokens,
            "temperature": settings.temperature,
            "timeout_s": float(settings.timeout_s),
            # A fresh log means a fresh budget, so a conversation can never spend a
            # run's allowance — a finalized run's remaining budget is a meaningless
            # denominator, and a long conversation must not be able to starve a run.
            "max_tokens_per_run": max(settings.max_tokens * 4, settings.max_tokens + 1),
        }
    )
    client = build_client(
        llm,
        cache=LLMCache(
            backend=cache_backend,
            model=llm.model,
            prompt_version=llm.prompt_version,
        ),
        call_log=call_log,
    )

    turns = [
        (str(turn.get("who", "")).strip() or "You", str(turn.get("text", "")).strip())
        for turn in payload.transcript
        if str(turn.get("text", "")).strip()
    ]

    try:
        for piece in answer_module.answer_turn(client, pack, payload.question, turns, settings):
            if isinstance(piece, str):
                yield json.dumps({"type": "delta", "text": piece}).encode() + b"\n"
                continue
            yield json.dumps(
                {
                    "type": "done",
                    "citations": [
                        ChatCitation(
                            id=c.cite_id, kind=c.kind, label=c.label, anchor=c.anchor
                        ).model_dump()
                        for c in piece.citations
                    ],
                    "unverified": piece.unverified,
                }
            ).encode() + b"\n"
    except LLMError as exc:
        _LOG.info("chat: run %s could not be answered (%s)", run.id, type(exc).__name__)
        yield json.dumps(
            {
                "type": "error",
                "message": "The model could not be reached. Nothing was changed or saved.",
            }
        ).encode() + b"\n"
    finally:
        # Recorded like every other call, so the usage screens and the per-person
        # counts include the chat without a second accounting path. An abandoned
        # stream records whatever it managed, which is also what it spent.
        call_cache.record_calls(session, call_log, run.id, user.id)
        session.commit()


@router.post("/runs/{run_id}/chat")
def chat_answer(
    run_id: int,
    payload: ChatQuestion,
    request: Request,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
    data_dir: Any = Depends(get_data_dir),
) -> StreamingResponse:
    """Answer one question about a frozen report.

    Args:
        run_id: The run. The chat can see this one and no other.
        payload: The question and the transcript the browser is holding.
        request: The incoming request, for the shared cache store.
        session: The request's session.
        user: The asker.
        data_dir: The shared volume.

    Returns:
        A newline-delimited JSON stream: `delta` events carrying prose, then one
        `done` carrying the citations that resolved.

    Raises:
        HTTPException: 403 when the feature is off or the asker is over their daily
            cap, 404 when the run does not exist, 409 when it has no frozen report,
            422 when the conversation is longer than the per-run cap allows.
    """
    settings = chat_settings(session)
    if not settings.enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "the report chat is switched off")

    run = _run_or_404(session, run_id)
    _frozen_or_refuse(session, run)

    if settings.max_questions_per_day == 0:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "the report chat is not available to you yet"
        )
    if _asked_today(session, user.id) >= settings.max_questions_per_day:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"you have asked {settings.max_questions_per_day} questions today, "
            "which is the limit an administrator has set",
        )

    if _asked_about(session, run.id, user.id) >= settings.max_questions_per_run:
        raise HTTPException(
            422,
            f"you have asked {settings.max_questions_per_run} questions about this "
            "report, which is the limit an administrator has set. Reopening the panel "
            "does not reset it; the report and the run screens show everything the "
            "answers were built from.",
        )

    return StreamingResponse(
        _events(
            session,
            run,
            payload,
            settings,
            user,
            data_dir,
            request.app.state.llm_cache_backend,
        ),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store"},
    )
