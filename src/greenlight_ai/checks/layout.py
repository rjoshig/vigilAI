"""What a delivery calls each sheet, column and row label (Phase 6.21b).

The fixed report checks name what they look for — ``Attributes``, ``States``,
``Accepts`` — and until Phase 6.21 those names were Python constants matched exactly.
Adapting to a customer's DIRT meant editing `checks/reports.py` and deploying, which
is the one thing this product was designed to avoid: everything else an administrator
needs to teach it is data.

So the names are data too. An entry says, for one scope, that a kind of thing the
checks ask for is spelled some other way here:

    scope ``programme:AM`` · sheet ``Attributes`` → ``Attribute Summary``

The ladder reads them as its **fourth rung** (ADR-054), which is the one a person
writes. That placement is the whole design: an entry never overrules the name actually
asked for, it is reached only after normalising and token matching have failed, and it
costs no model call — so recording one turns a delivery the model had to reason about
into a delivery code resolves.

**Nothing here is applied on its own.** An entry exists because an administrator wrote
it or accepted a suggestion, and a suggestion exists because the ladder's fifth rung
resolved a name and said so on the run (ADR-021 is unchanged: nothing activates without
a person approving it).
"""

from __future__ import annotations

import logging
from typing import Final, Iterable, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from greenlight_ai import scopes
from greenlight_ai.resolve.layout import alternates_key

__all__ = [
    "KINDS",
    "LayoutEntry",
    "LayoutSuggestion",
    "entry_id",
    "load_map",
    "merge_suggestions",
]

_LOG: Final = logging.getLogger(__name__)

#: What an entry can name. The same closed set the resolver uses, so a typo cannot
#: invent a kind that nothing ever reads.
KINDS: Final[tuple[str, ...]] = ("sheet", "column", "label")


class LayoutEntry(BaseModel):
    """One name this delivery spells differently.

    Attributes:
        scope: Which runs it covers, in the one scope vocabulary (ADR-037). Empty
            means everywhere.
        kind: ``sheet``, ``column`` or ``label``.
        wanted: The name the fixed checks ask for, e.g. ``Attributes``.
        names: What this delivery calls it. Several, because one artifact type can be
            delivered by customers who each word it differently.
        note: Why, for whoever reads it next.
        added_by: Who recorded it.
    """

    model_config = ConfigDict(extra="forbid")

    scope: str = ""
    kind: str = "sheet"
    wanted: str = Field(min_length=1, max_length=120)
    names: tuple[str, ...] = ()
    note: str = ""
    added_by: str = ""

    @property
    def id(self) -> str:
        """A stable identity for this entry within its artifact type."""
        return entry_id(self.scope, self.kind, self.wanted)


class LayoutSuggestion(BaseModel):
    """A name the model read, offered to an administrator (ADR-054).

    Attributes:
        artifact: Which artifact type it was read from.
        kind: ``sheet``, ``column`` or ``label``.
        wanted: The name the checks asked for.
        found: What the model said it is here.
        confidence: The model's own number, already past the floor.
        reason: Its one line, so the offer can be judged rather than taken on trust.
    """

    model_config = ConfigDict(extra="forbid")

    artifact: str = ""
    kind: str = "sheet"
    wanted: str = ""
    found: str = ""
    confidence: float = 0.0
    reason: str = ""


def entry_id(scope: str, kind: str, wanted: str) -> str:
    """The identity of one entry, for de-duplicating and for the console.

    Args:
        scope: The scope token.
        kind: ``sheet``, ``column`` or ``label``.
        wanted: The name the checks ask for.

    Returns:
        A stable string. Two entries with the same identity are the same entry however
        the spelling of ``wanted`` differs, which is what stops a console accumulating
        ``Attributes`` and ``attributes`` as separate rows.
    """
    return alternates_key(scopes.token(scope), kind, wanted)


def load_map(
    artifacts: Iterable[tuple[str, Sequence[Mapping[str, object]]]],
    customer: str = "",
    programme_code: str = "",
    configuration_id: str = "",
) -> dict[str, tuple[str, ...]]:
    """Build the alternates map one run's resolver reads.

    Args:
        artifacts: ``(artifact key, stored entries)`` for every type.
        customer: The run's customer.
        programme_code: The run's delivery programme.
        configuration_id: The run's ETL configuration.

    Returns:
        :func:`greenlight_ai.resolve.layout.alternates_key` to the spellings in force,
        with a narrower scope's names first. An entry whose scope does not cover this
        run is left out rather than loaded and never matched.
    """
    built: dict[str, list[str]] = {}
    for key, stored in artifacts:
        for raw in stored or ():
            try:
                entry = LayoutEntry.model_validate(raw)
            except ValueError:
                _LOG.info("artifact %s: a layout entry could not be read and was skipped", key)
                continue
            if entry.kind not in KINDS or not entry.names:
                continue
            if not scopes.covers(
                entry.scope,
                customer=customer,
                programme_code=programme_code,
                configuration_id=configuration_id,
            ):
                continue
            slot = built.setdefault(alternates_key(key, entry.kind, entry.wanted), [])
            for name in entry.names:
                if name and name not in slot:
                    slot.append(name)
    return {key: tuple(names) for key, names in built.items()}


def merge_suggestions(
    existing: Sequence[Mapping[str, object]],
    offered: Iterable[LayoutSuggestion],
) -> list[dict[str, object]]:
    """Fold a run's newly read names into what a type already suggests.

    Args:
        existing: What is already recorded, as stored.
        offered: What this run's resolver reached.

    Returns:
        The merged list. The same wanted name read the same way twice is one
        suggestion: an administrator should see *what to decide*, not how many runs
        met it — the count is in the runs.
    """
    merged: dict[tuple[str, str, str, str], dict[str, object]] = {}
    for raw in existing or ():
        try:
            entry = LayoutSuggestion.model_validate(raw)
        except ValueError:
            continue
        merged[(entry.artifact, entry.kind, entry.wanted, entry.found)] = entry.model_dump()
    for suggestion in offered:
        merged[(suggestion.artifact, suggestion.kind, suggestion.wanted, suggestion.found)] = (
            suggestion.model_dump()
        )
    return list(merged.values())
