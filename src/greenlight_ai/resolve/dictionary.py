"""The attribute dictionary: the ladder's fourth rung, as data (Phase 6.22d).

Rung 4 has existed since 6.21a and has never had anything to read. It takes
``alternates`` — *other names that also mean this one* — and the only caller that ever
filled it was the layout map, which holds sheets, columns and row labels: a handful of
names per artifact, kept in a JSON column. An attribute dictionary is not that shape. A
real delivery has hundreds of attributes and a credit bureau's vocabulary runs to
thousands, each with a spelling per artifact, each with provenance. That belongs in
tables, and what reaches the ladder is this value object built from them.

What the dictionary knows is one thing said two ways:

**One canonical attribute, many spellings.** ``AT01`` is the term; ``AT01``,
``debsc_burs_atyrt_at01_1`` and ``at_01_bureau`` are spellings of it. A lookup for any
of them reaches the term, and the term's other spellings become the alternates the
ladder is given. That is what turns 6.22a's honest *"could not tell which column is
AT01"* into an answer.

**A spelling may belong to one artifact.** The DIRT and the record layout need not agree
with each other, and a spelling recorded against the DIRT should not be offered as a
record-layout heading. A spelling with no artifact means *anywhere*, which is the
ordinary case and the one an administrator writes by hand.

Two rules keep it honest:

* **It never picks.** The dictionary produces alternates; the *ladder* decides, and it
  still refuses to answer when two candidates tie. A dictionary entry is a stronger
  claim than any amount of normalising — which is exactly why it is rung 4 and not
  rung 1 — but it is still evidence offered to code, not a verdict.
* **Nothing that matched before stops matching.** The legacy ``attribute_aliases`` rows
  are read alongside the dictionary (ADR-062), so a deployment that seeded aliases
  behaves as it always did while the dictionary fills up beside them.

Nothing here touches the database or a model.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Final, Iterable, Mapping, Sequence

from greenlight_ai.resolve.normalize import squashed

__all__ = [
    "ANY_ARTIFACT",
    "AttributeDictionary",
    "AttributeSpellingEntry",
    "AttributeTermEntry",
]

_LOG: Final = logging.getLogger(__name__)

#: A spelling that belongs to no particular artifact, and so is offered for all of them.
#: The ordinary case, and the one an administrator writes by hand.
ANY_ARTIFACT: Final[str] = ""


@dataclass(frozen=True, slots=True)
class AttributeSpellingEntry:
    """One way an artifact writes an attribute.

    Attributes:
        spelling: The name as that artifact writes it.
        artifact: Which artifact it was seen in, e.g. ``"dirt"`` or ``"record_layout"``.
            :data:`ANY_ARTIFACT` means it is offered everywhere.
        origin: Where it came from — ``"admin"`` for a person, ``"record_layout"`` for a
            spelling read out of an uploaded layout, ``"model"`` for one the ladder's
            fifth rung reached and somebody confirmed, ``"observation"`` for one a
            reviewer proposed. Provenance is on the spelling rather than the term
            because it is the spelling somebody vouched for.
        origin_run_id: The run it was learned from, when it was learned from one.
    """

    spelling: str
    artifact: str = ANY_ARTIFACT
    origin: str = "admin"
    origin_run_id: int = 0


@dataclass(frozen=True, slots=True)
class AttributeTermEntry:
    """One attribute, and every name it goes by.

    Attributes:
        canonical: The one name the tool uses, which is what the OSL is expected to say
            and what a check asks for.
        label: What a person calls it, for a console.
        description: What the attribute is, in a sentence.
        spellings: Every way an artifact writes it.
        scope: Where this term applies, in the ADR-037 vocabulary.
    """

    canonical: str
    label: str = ""
    description: str = ""
    spellings: tuple[AttributeSpellingEntry, ...] = ()
    scope: str = "everywhere"

    def names(self, artifact: str = ANY_ARTIFACT) -> tuple[str, ...]:
        """Every name this term goes by in one artifact, canonical first.

        Args:
            artifact: Which artifact to answer for. :data:`ANY_ARTIFACT` returns every
                spelling regardless of which artifact it was recorded against.

        Returns:
            The canonical name and the spellings that apply, de-duplicated and in a
            stable order — the canonical first, because it is the strongest claim.
        """
        wanted = artifact.strip().lower()
        found = [self.canonical]
        for spelling in self.spellings:
            if not spelling.spelling.strip():
                continue
            if wanted and spelling.artifact and spelling.artifact != wanted:
                continue
            found.append(spelling.spelling)
        return tuple(dict.fromkeys(found))


@dataclass(frozen=True, slots=True)
class AttributeDictionary:
    """Every attribute term in force for one run, indexed by every name it goes by.

    An empty dictionary is a working dictionary: it offers no alternates, the ladder
    stops at rung 3, and every check answers exactly as it did before 6.22d — which is
    the state the product ships in.

    Attributes:
        terms: The terms, in the order they should be offered.
        by_name: Every squashed name — canonical or spelling — to the term it belongs
            to. The first term to claim a name keeps it, which is what lets a caller
            pass the most specifically scoped terms first.
    """

    terms: tuple[AttributeTermEntry, ...] = ()
    by_name: Mapping[str, AttributeTermEntry] = field(default_factory=dict)

    @classmethod
    def from_terms(cls, terms: Iterable[AttributeTermEntry]) -> "AttributeDictionary":
        """Build a dictionary from its terms.

        Args:
            terms: The terms, narrowest scope first. The first term to claim a name
                keeps it, so a configuration's own spelling of ``SCORE`` wins over a
                customer's and a customer's over a global one — the same resolution
                every other scoped definition uses (ADR-037).

        Returns:
            The dictionary.
        """
        ordered = tuple(terms)
        index: dict[str, AttributeTermEntry] = {}
        for term in ordered:
            for name in term.names():
                key = squashed(name)
                if key:
                    index.setdefault(key, term)
        return cls(terms=ordered, by_name=index)

    def term(self, name: str) -> AttributeTermEntry | None:
        """The term one name belongs to.

        Args:
            name: A canonical name or any spelling of one.

        Returns:
            The term, or ``None`` when the dictionary does not know the name. Matched
            on the squashed form, so ``opt_out`` and ``OPT-OUT`` reach the same term —
            the same tolerance the ladder's second rung gives every other name.
        """
        return self.by_name.get(squashed(name))

    def canonical(self, name: str) -> str:
        """The canonical name for whatever a caller was given.

        Args:
            name: A canonical name or any spelling of one.

        Returns:
            The term's canonical name, or ``name`` unchanged when the dictionary does
            not know it. Unchanged rather than empty: a name the dictionary has never
            seen is still that name, and a caller must be able to go on using it.
        """
        found = self.term(name)
        return found.canonical if found is not None else name

    def alternates(self, wanted: str, artifact: str = ANY_ARTIFACT) -> tuple[str, ...]:
        """The other names ``wanted`` goes by, for the ladder's fourth rung.

        Args:
            wanted: The attribute as the check asks for it.
            artifact: Which artifact is being read, so a spelling recorded against the
                DIRT is not offered as a record-layout heading.

        Returns:
            Every other name, the wanted one excluded because rungs 1 to 3 have already
            tried it. Empty when the dictionary does not know the name, which leaves the
            ladder exactly where it was before this existed.
        """
        found = self.term(wanted)
        if found is None:
            return ()
        key = squashed(wanted)
        return tuple(name for name in found.names(artifact) if squashed(name) != key)

    def shortlist(self, wanted: str, candidates: Sequence[str]) -> tuple[str, ...]:
        """Candidates the dictionary can rule *out*, removed.

        The deterministic narrowing that happens before any model call. A candidate the
        dictionary already assigns to a **different** term is not what ``wanted`` means,
        whatever it looks like — so offering it to the model is offering a distraction
        somebody has already answered.

        This only ever removes. It never promotes a candidate, because a dictionary
        entry that matched would have been settled at rung 4 and never reached here.

        Args:
            wanted: The attribute as the check asks for it.
            candidates: The names the artifact offers, already narrowed by
                :func:`greenlight_ai.resolve.attributes.near_names`.

        Returns:
            The candidates that survive, in the order given. When that would be empty,
            the candidates unchanged: ruling everything out tells the model nothing and
            would turn a shortlist into a refusal the caller never asked for.
        """
        if not self.by_name:
            return tuple(candidates)
        mine = self.term(wanted)
        kept: list[str] = []
        for candidate in candidates:
            owner = self.term(candidate)
            if owner is not None and owner is not mine:
                _LOG.debug("dictionary: %r is %r, not %r", candidate, owner.canonical, wanted)
                continue
            kept.append(candidate)
        return tuple(kept) if kept else tuple(candidates)

    def merged(self, other: "AttributeDictionary") -> "AttributeDictionary":
        """This dictionary with another's terms behind it.

        Used to read the legacy ``attribute_aliases`` table alongside the dictionary
        (ADR-062): the dictionary's own terms come first and win, and an alias somebody
        seeded years ago still resolves. Nothing that matched before stops matching.

        Args:
            other: The terms to fall back on.

        Returns:
            A dictionary holding both, this one's terms first.
        """
        return AttributeDictionary.from_terms(self.terms + other.terms)
