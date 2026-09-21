"""One turn of the report chat: stream the prose, then check the citations (Phase 8c).

The shape of this module is decided by one sentence: **code cannot check a citation it
has already displayed.** So the model writes the answer as prose containing no
identifiers, then a delimited tail naming what it answered from. The prose reaches the
panel as it arrives; the tail is validated against the pack when the stream closes, and
only the citations that resolve become chips.

That makes a fabricated id impossible to show. Not briefly, not dimmed, not at all.

**A failed tail keeps the answer.** The prose is what the person asked for and stands on
its own. Pulling text somebody is mid-way through reading looks like a malfunction even
when it is correct, so the panel says *the citations could not be verified for this
answer* rather than showing chips or replacing anything. This is the one place the
adapter's single-retry contract deliberately does not apply, and it is written down here
rather than discovered later.

**Nothing is stored.** Not the question, not the answer, not the transcript. The turn
exists for as long as it takes to yield it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Final, Iterator, Sequence

from greenlight_ai.chat.pack import Citable, RunPack
from greenlight_ai.chat.settings import ChatSettings
from greenlight_ai.llm.client import LLMClient
from greenlight_ai.llm.prompts import chat_answer as prompt_module
from greenlight_ai.llm.prompts.chat_answer import CHAT_ANSWER_PROMPT, CITATION_MARKER

__all__ = ["Answer", "STAGE", "answer_turn", "split_answer"]

_LOG: Final = logging.getLogger(__name__)

#: The stage name on every chat call row, so the usage screens and the per-person
#: counts include the chat without a second accounting path (Phase 8f).
STAGE: Final[str] = "chat_answer"

#: What the model writes when the answer rests on nothing in particular — because it is
#: declining, or saying it cannot tell. An empty tail and a deliberate "nothing" are
#: different facts, and only the first is a failure.
_NONE: Final[str] = "NONE"


@dataclass(slots=True)
class Answer:
    """What one turn produced, once the stream has closed.

    Attributes:
        prose: What the person read. Already delivered piece by piece; repeated here
            whole so a caller that wants the finished text does not reassemble it.
        citations: The citations that resolved against the pack, in the order the
            model named them. Everything that did not resolve is absent.
        unverified: True when the tail was missing or unreadable, or when the model
            named only identifiers that do not exist. The answer still stands.
        discarded: How many identifiers were thrown away because nothing in the pack
            had them. Logged and returned rather than hidden: a model that fabricates
            regularly is something an administrator should be able to find out.
    """

    prose: str = ""
    citations: list[Citable] = field(default_factory=list)
    unverified: bool = False
    discarded: int = 0


def split_answer(raw: str) -> tuple[str, list[str], bool]:
    """Separate the prose from the citation tail.

    Args:
        raw: The whole answer as it arrived.

    Returns:
        The prose, the identifiers as written, and whether the tail was unusable. A
        missing marker is unusable; a marker followed by ``NONE`` is not — the model
        said the answer rests on nothing in particular, which is a real answer and the
        right one for a refusal.
    """
    if CITATION_MARKER not in raw:
        return raw.strip(), [], True
    prose, _, tail = raw.partition(CITATION_MARKER)
    cleaned = tail.strip()
    if not cleaned:
        return prose.strip(), [], True
    if cleaned.upper().startswith(_NONE):
        return prose.strip(), [], False
    ids = [piece.strip() for piece in cleaned.replace("\n", ",").split(",") if piece.strip()]
    return prose.strip(), ids, not ids


def _prompt(
    pack: RunPack,
    question: str,
    turns: Sequence[tuple[str, str]],
    settings: ChatSettings,
) -> tuple[str, str]:
    """Render the system and user prompts for one turn.

    Args:
        pack: The server-built pack. Everything the model is told comes from here.
        question: What the person asked.
        turns: Earlier turns, oldest first.
        settings: The chat settings, for the transcript cap.

    Returns:
        The system prompt and the user prompt.
    """
    kept = list(turns)[-settings.max_turns :] if settings.max_turns > 0 else []
    return (
        CHAT_ANSWER_PROMPT.system,
        CHAT_ANSWER_PROMPT.render(
            pack=pack.rendered(),
            transcript=prompt_module.transcript_block(kept),
            question=question.strip(),
        ),
    )


def answer_turn(
    client: LLMClient,
    pack: RunPack,
    question: str,
    turns: Sequence[tuple[str, str]] = (),
    settings: ChatSettings | None = None,
) -> Iterator[str | Answer]:
    """Run one turn, yielding prose as it arrives and the checked answer last.

    The generator yields `str` pieces — the prose, as the model produces it — and
    finally exactly one :class:`Answer`, once the stream has closed and the citations
    have been checked. A caller can therefore write the strings straight to the wire
    and treat the last item as the thing that decides what chips to draw.

    **The tail never reaches the caller as prose.** Everything after
    :data:`~greenlight_ai.llm.prompts.chat_answer.CITATION_MARKER` is withheld, so the
    person never sees a list of raw identifiers appear and then vanish. That means a
    piece containing the marker is split, and pieces after it are swallowed.

    Args:
        client: The adapter. Streaming lives there, so the tripwire, the cache check,
            the budget stop and the call record all still happen in one place.
        pack: The pack, built on the server from the run id (Phase 8d).
        question: What the person asked.
        turns: Earlier turns as ``(who, text)``, oldest first. Treated as data by the
            prompt, never as instructions.
        settings: The chat settings. Omitted, the defaults apply.

    Yields:
        Prose pieces, then one :class:`Answer`.
    """
    chat = settings or ChatSettings()
    system, user = _prompt(pack, question, turns, chat)

    raw: list[str] = []
    #: How many characters of the answer the caller has already been given. Counted
    #: rather than re-joined, because every index below is an offset into the text
    #: **as it streamed** and the count is the only thing that keeps them honest.
    shown = 0
    tail_started = False
    for piece in client.stream(
        system,
        user,
        stage=STAGE,
        prompt_version=f"{CHAT_ANSWER_PROMPT.version}:{pack.sha256[:12]}",
    ):
        raw.append(piece)
        if tail_started:
            continue
        joined = "".join(raw)
        if CITATION_MARKER in joined:
            tail_started = True
            prose_so_far = joined.partition(CITATION_MARKER)[0]
            remaining = prose_so_far[shown:]
            if remaining:
                shown += len(remaining)
                yield remaining
            continue
        # Hold back as much as the marker is long, so a marker split across two
        # pieces is never half-shown. A person watching an answer appear must not
        # see the seam of the mechanism that checks it.
        safe = joined[: max(0, len(joined) - len(CITATION_MARKER))]
        remaining = safe[shown:]
        if remaining:
            shown += len(remaining)
            yield remaining

    whole = "".join(raw)
    prose, ids, unusable = split_answer(whole)
    # The held-back tail is released against the text **as it streamed**, never against
    # `prose`. `split_answer` strips, and `shown` counts raw characters: indexing a
    # stripped string by a raw count skips exactly as many characters as the strip
    # removed from the front, so an answer that began with a newline and never produced
    # a marker reached the reader with characters missing from its middle — "consistent
    # with the spec" as "consistent wth the spec". Silent, and on the very path that
    # exists to keep a citation-less answer readable.
    streamed = whole.partition(CITATION_MARKER)[0] if CITATION_MARKER in whole else whole
    remaining = streamed[shown:]
    if remaining:
        yield remaining

    resolved: list[Citable] = []
    discarded = 0
    for cite_id in ids:
        found = pack.resolve(cite_id)
        if found is None:
            discarded += 1
            continue
        if found not in resolved:
            resolved.append(found)
    if discarded:
        # Counted rather than named: the identifier the model invented is not worth
        # putting in a log, and how often it happens is.
        _LOG.info(
            "chat: %d citation(s) on run %s did not resolve against the pack and were discarded",
            discarded,
            pack.run_id,
        )

    yield Answer(
        prose=prose,
        citations=resolved,
        # Unverified means "the model did not tell us what this rests on", not "it
        # rests on nothing". A deliberate NONE is a verified answer with no citations.
        unverified=unusable or (bool(ids) and not resolved),
        discarded=discarded,
    )
