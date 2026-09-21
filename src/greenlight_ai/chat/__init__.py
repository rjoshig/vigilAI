"""Ask the frozen report: a read-only assistant that can see one run (Phase 8).

The chat is given a **context pack** that code assembles from the database, it answers
questions about that pack, it cites what it answered from, and it says so when the pack
does not contain the answer. It cannot change a decision, create a finding, re-open a
report, or see another run. It stores nothing. It is off until an administrator turns
it on.

**Why this is its own subpackage rather than a router helper.** `api/` never imports
`pipeline/` (`architecture.md`), and the context this needs is exactly the sort of
thing `pipeline/` already builds. Putting the builder here — imported by `api/` and
importing nothing above `db/`, `llm/` and `textfit` — is what keeps that rule true
transitively rather than only in the diff somebody reads.

Three modules:

- :mod:`~greenlight_ai.chat.pack` builds the pack from a run id and hashes it.
- :mod:`~greenlight_ai.chat.answer` runs one turn against it.
- :mod:`~greenlight_ai.chat.settings` resolves the nine console switches (ADR-023).
"""

from greenlight_ai.chat.pack import RunPack, build_pack, greeting, starters
from greenlight_ai.chat.settings import ChatSettings, chat_settings

__all__ = [
    "ChatSettings",
    "RunPack",
    "build_pack",
    "chat_settings",
    "greeting",
    "starters",
]
