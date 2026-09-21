"""The ladder, held together for one run (Phase 6.21a).

A run asks the same question many times — every derived check that needs the DIRT's
attribute sheet asks for it again — and the expensive rung must not be paid for twice.
So the ladder is wrapped in an object with three jobs:

* **Answer.** Four deterministic rungs, then the model where they failed.
* **Remember.** One model call per *distinct name per run*, not one per check that
  referenced it. Cached here as well as in the adapter, because two lookups in the same
  run of a name the model said was absent should cost one call, not two cache reads and
  certainly not two calls.
* **Report.** Every name the model reached is kept, so stage 7 can raise the
  review-severity record a person confirms, and so an administrator can be offered the
  answer as a layout-map entry that makes the next run deterministic (Phase 6.21b).

The resolver knows nothing about workbooks. It takes names and returns names, which is
what keeps :mod:`greenlight_ai.resolve` below :mod:`greenlight_ai.parsers` and
:mod:`greenlight_ai.checks` rather than beside them.

**A resolver with no client is a working resolver.** It runs the four deterministic
rungs and returns ``None`` where they fail, which is exactly the behaviour the product
had before this package existed. Every caller is written so that path is the ordinary
one, not a degraded one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Final, Mapping, Sequence

from greenlight_ai.llm.client import LLMClient
from greenlight_ai.llm.examples import LibraryExample
from greenlight_ai.resolve.dictionary import AttributeDictionary
from greenlight_ai.resolve.ladder import Resolution, resolve
from greenlight_ai.resolve.locate import locate
from greenlight_ai.resolve.normalize import squashed

__all__ = ["ATTRIBUTE", "LayoutResolver", "ReasonedName", "alternates_key"]

_LOG: Final = logging.getLogger(__name__)

#: What kind of name was being resolved. Used in the key of the alternates map, in the
#: wording of a finding, and to group suggestions on the admin screen. ``attribute``
#: joined the three in Phase 6.22d: an attribute name reaches the same five rungs as a
#: sheet name, and what the model had to reason about is offered to a person the same
#: way. Its *alternates* come from the dictionary rather than the layout map, because a
#: dictionary is thousands of rows and a JSON column is the wrong home (ADR-062).
_KINDS: Final[frozenset[str]] = frozenset({"sheet", "column", "label", "attribute"})

#: The kind whose alternates and cap come from the dictionary rather than the map.
ATTRIBUTE: Final[str] = "attribute"


def alternates_key(artifact: str, kind: str, wanted: str) -> str:
    """The key a layout map entry is stored and looked up under.

    Args:
        artifact: Which artifact type, e.g. ``"dirt"``. Empty for a name that is not
            tied to one.
        kind: ``"sheet"``, ``"column"`` or ``"label"``.
        wanted: The name the tool looks for.

    Returns:
        A stable key. Squashed on the wanted name so a layout map written against
        ``Attribute`` answers a lookup for ``attributes``, which is the same tolerance
        the ladder's second rung gives every other comparison.
    """
    return f"{artifact.strip().lower()}:{kind.strip().lower()}:{squashed(wanted)}"


@dataclass(frozen=True, slots=True)
class ReasonedName:
    """A name the model reached, which a person must confirm.

    Attributes:
        artifact: Which artifact it was read from, e.g. ``"dirt"``.
        kind: ``"sheet"``, ``"column"`` or ``"label"``.
        wanted: What the tool looked for.
        found: What it used instead.
        confidence: The model's own number, already past the floor.
        reason: The model's one line, for the finding's detail.
    """

    artifact: str
    kind: str
    wanted: str
    found: str
    confidence: float
    reason: str

    @property
    def title(self) -> str:
        """One line for a finding's title.

        Returns:
            What was expected and what was read instead, named so a reviewer can
            disagree with the resolution rather than only with the finding.
        """
        where = f"{self.artifact} " if self.artifact else ""
        return f"The {where}{self.kind} {self.wanted!r} was read as {self.found!r}"


@dataclass
class LayoutResolver:
    """Resolves names for one run, deterministically first.

    Attributes:
        client: The adapter, or ``None`` when this run may not spend a model call. A
            resolver without one is fully functional and stops at the fourth rung.
        alternates: The layout map in force, keyed by :func:`alternates_key`
            (Phase 6.21b). Empty is the ordinary state on a new deployment.
        preamble: The run's context block, so this call carries the same background as
            every other one.
        examples: Library examples for the ``name_locate`` stage.
        dictionary: The attribute dictionary in force (Phase 6.22d). Supplies rung 4
            for ``attribute`` names and narrows the shortlist rung 5 is shown. Empty is
            the ordinary state and leaves the ladder stopping at rung 3.
        max_attribute_calls: How many model calls this run may spend asking which
            column an attribute is. A **soft** limit inside the existing token
            ceiling: past it the resolver stops asking and the run says so, and nothing
            is refused. Zero means never ask.
        reasoned: Every name the model reached this run, in the order it reached them.
            Read by stage 7 to raise the review records and offer the suggestions.
        attribute_calls: How many attribute locate calls were actually spent, counted
            so the cap can be measured rather than claimed.
        capped: Attribute names the cap stopped this run from asking about, so the run
            can say what it did not look for rather than leaving the gap silent.
    """

    client: LLMClient | None = None
    alternates: Mapping[str, Sequence[str]] = field(default_factory=dict)
    dictionary: AttributeDictionary = field(default_factory=AttributeDictionary)
    max_attribute_calls: int = 0
    preamble: str = ""
    examples: Sequence[LibraryExample] = ()
    reasoned: list[ReasonedName] = field(default_factory=list)
    attribute_calls: int = 0
    capped: list[str] = field(default_factory=list)
    _cache: dict[tuple[str, str, str, tuple[str, ...]], Resolution | None] = field(
        default_factory=dict, repr=False
    )

    def name(
        self,
        wanted: str,
        candidates: Sequence[str],
        *,
        kind: str = "sheet",
        artifact: str = "",
        description: str = "",
    ) -> Resolution | None:
        """Work out which candidate ``wanted`` refers to.

        Args:
            wanted: The name the tool is looking for.
            candidates: The names the artifact carries, spelled as it spells them.
            kind: ``"sheet"``, ``"column"`` or ``"label"``.
            artifact: Which artifact type, for the finding's wording and the layout map
                key.
            description: One line saying what the name is for, shown to the model
                because it sees names and nothing else. Defaults to a plain sentence
                built from ``kind`` and ``wanted``.

        Returns:
            The resolution, or ``None`` when neither code nor the model could say. A
            resolution whose ``reasoned`` is ``True`` has already been recorded in
            :attr:`reasoned`.
        """
        asked = wanted.strip()
        offered = tuple(c for c in candidates if c is not None)
        if not asked or not offered:
            return None
        if kind not in _KINDS:  # pragma: no cover - a typo in a call site, not a state
            raise ValueError(f"unknown name kind {kind!r}")

        key = (artifact, kind, asked.lower(), offered)
        if key in self._cache:
            return self._cache[key]

        # Rung 4's data comes from the layout map for a sheet, column or label, and
        # from the dictionary for an attribute (ADR-062). Both are "other names that
        # also mean this one"; only their storage differs.
        known = (
            self.dictionary.alternates(asked, artifact)
            if kind == ATTRIBUTE
            else self.alternates.get(alternates_key(artifact, kind, asked), ())
        )
        found = resolve(asked, offered, known)
        if found is None:
            found = self._ask(asked, offered, kind, artifact, description)

        self._cache[key] = found
        return found

    def _ask(
        self,
        wanted: str,
        candidates: Sequence[str],
        kind: str,
        artifact: str,
        description: str,
    ) -> Resolution | None:
        """Spend the fifth rung, and record it when it answers.

        Args:
            wanted: The name the tool is looking for.
            candidates: The names the artifact carries.
            kind: ``"sheet"``, ``"column"`` or ``"label"``.
            artifact: Which artifact type.
            description: What the name is for, in one line.

        Returns:
            The model's resolution once code has checked it, or ``None``.
        """
        if kind == ATTRIBUTE:
            if self.attribute_calls >= self.max_attribute_calls:
                # Soft: the run goes on and says what it did not look for. A refusal
                # here would fail a delivery over a budget, which is never the answer
                # (the precedent is `s6_reverse._may_locate`).
                if wanted not in self.capped:
                    self.capped.append(wanted)
                _LOG.info(
                    "attribute %r: not asked; the run's cap of %d locate call(s) is spent",
                    wanted,
                    self.max_attribute_calls,
                )
                return None
            self.attribute_calls += 1
            # Everything the dictionary can already rule out, removed before the model
            # sees it: a candidate it assigns to a *different* term is not what this
            # name means, whatever it looks like.
            candidates = self.dictionary.shortlist(wanted, candidates)

        said = locate(
            self.client,
            wanted,
            description or f"a {kind} called {wanted!r}",
            candidates,
            preamble=self.preamble,
            examples=self.examples,
        )
        if said is None:
            return None

        self.reasoned.append(
            ReasonedName(
                artifact=artifact,
                kind=kind,
                wanted=wanted,
                found=said.value,
                confidence=said.confidence,
                reason=said.reason,
            )
        )
        _LOG.info("layout: %s %r read as %r (%.2f)", kind, wanted, said.value, said.confidence)
        return said
