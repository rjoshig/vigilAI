"""Product codes, and expanding one into the attributes it stands for (Phase 6.22c).

An OSL says either *"deliver AT01, AT02, ST"* or *"deliver all attributes from ABC"*.
Both mean the same thing and both have to reach the same check, so somewhere the second
has to become the first. That expansion is the whole of this module, and where it
happens is the decision worth stating:

**Expansion is code, never the model.** The model's only job is *reading* that a
requirement names a product code — which is reading meaning, and exactly what ADR-001
gives it. Looking the code up, deciding which attributes it contains and checking that
the code exists at all are lookups and comparisons, which ADR-001 keeps in code. A model
asked "what is in ABC?" would answer plausibly and be believed, and a delivery would be
validated against a list nobody wrote.

**An attribute shared by two codes is one term with one output name.** If ABC and DEF
both carry ``SCORE_V3`` they carry the *same* ``SCORE_V3``, delivered under one name.
A catalogue where they disagree is not two opinions to choose between; it is a defect,
and :meth:`ProductCatalogue.conflicts` names it rather than picking a winner — the same
rule the ladder follows when two candidates tie.

**A code nobody defined does not silently expand to nothing.** Expanding an unknown code
to an empty attribute list would turn "check everything ABC contains" into "check
nothing", and the run would pass. :class:`Expansion` keeps the unknown codes separate so
the caller raises a finding instead.

Nothing here touches the database or a model. The catalogue is a value object the
repository builds, exactly as :class:`~greenlight_ai.rules.normalize.AliasTable` is.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Final, Iterable, Mapping, Sequence

from greenlight_ai.resolve import squashed

__all__ = [
    "Expansion",
    "ProductCatalogue",
    "ProductCodeEntry",
    "ProductMember",
]

_LOG: Final = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProductMember:
    """One attribute a product code contains.

    Attributes:
        attribute: The attribute as the catalogue names it, which is what the OSL is
            expected to say and what the checks ask for.
        output_name: What the delivered file calls it, when that differs. Empty means
            it is delivered under its own name, which is the ordinary case.
        sort_order: Position within the code, so a console lists them the way the
            person who entered them meant.
    """

    attribute: str
    output_name: str = ""
    sort_order: int = 0

    @property
    def delivered_as(self) -> str:
        """The name the delivery is expected to use.

        Returns:
            The output name when the catalogue gives one, otherwise the attribute.
        """
        return self.output_name or self.attribute


@dataclass(frozen=True, slots=True)
class ProductCodeEntry:
    """One product code and everything it stands for.

    Attributes:
        code: The code as written, e.g. ``"ABC"``.
        label: What a person calls it.
        description: What the code is, in a sentence.
        members: The attributes it contains, in catalogue order.
        scope: Where this definition applies, in the ADR-037 vocabulary.
    """

    code: str
    label: str = ""
    description: str = ""
    members: tuple[ProductMember, ...] = ()
    scope: str = "everywhere"

    @property
    def attributes(self) -> tuple[str, ...]:
        """Every attribute this code contains, in catalogue order."""
        return tuple(member.attribute for member in self.members)

    @property
    def delivered_names(self) -> tuple[str, ...]:
        """What the delivery is expected to call each of them."""
        return tuple(member.delivered_as for member in self.members)


@dataclass(frozen=True, slots=True)
class Expansion:
    """What a set of product codes expanded to.

    Attributes:
        attributes: Every attribute the named codes contain, de-duplicated and in the
            order the codes list them. An attribute two codes share appears once.
        by_code: Which code contributed which attributes, for a finding that needs to
            say where a name came from.
        unknown: Codes the catalogue does not define. Kept separate so a caller never
            mistakes "this code expanded to nothing" for "this code asked for nothing".
    """

    attributes: tuple[str, ...] = ()
    by_code: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    unknown: tuple[str, ...] = ()

    @property
    def expanded(self) -> bool:
        """Whether any code resolved to at least one attribute."""
        return bool(self.attributes)

    def code_for(self, attribute: str) -> str:
        """Which code an expanded attribute came from.

        Args:
            attribute: The attribute name, as the expansion produced it.

        Returns:
            The first code that contains it, or an empty string when none does. First
            rather than all: a finding names where to look, and an attribute two codes
            share is the same attribute either way.
        """
        for code, names in self.by_code.items():
            if attribute in names:
                return code
        return ""


@dataclass(frozen=True, slots=True)
class ProductCatalogue:
    """The product codes in force for one run.

    An empty catalogue is a working catalogue: every OSL that names attributes directly
    is checked exactly as it was before product codes existed, and a requirement that
    names a code the catalogue does not hold produces a finding rather than a silent
    pass.

    Attributes:
        entries: The codes, keyed by their squashed form so ``abc`` and ``ABC`` are one
            code and a hyphenated ``A-BC`` reaches ``ABC`` — the same tolerance the
            ladder's second rung gives every other name.
    """

    entries: Mapping[str, ProductCodeEntry] = field(default_factory=dict)

    @classmethod
    def from_entries(cls, entries: Iterable[ProductCodeEntry]) -> "ProductCatalogue":
        """Build a catalogue from its codes.

        Args:
            entries: The codes, in the order they should be offered. The first
                definition of a code wins, which is what lets a caller pass the
                most specifically scoped rows first.

        Returns:
            The catalogue.
        """
        by_key: dict[str, ProductCodeEntry] = {}
        for entry in entries:
            key = squashed(entry.code)
            if key and key not in by_key:
                by_key[key] = entry
        return cls(entries=by_key)

    @property
    def codes(self) -> tuple[str, ...]:
        """Every code the catalogue defines, spelled as it defines them."""
        return tuple(entry.code for entry in self.entries.values())

    def get(self, code: str) -> ProductCodeEntry | None:
        """The entry for one code.

        Args:
            code: The code as the OSL wrote it.

        Returns:
            The entry, or ``None`` when the catalogue does not define it.
        """
        return self.entries.get(squashed(code))

    def knows(self, code: str) -> bool:
        """Whether the catalogue defines this code.

        Args:
            code: The code as the OSL wrote it.

        Returns:
            ``True`` when it does. This is the check that stops a model-read code from
            being believed on its own: what it read is a string, and code decides
            whether that string names anything.
        """
        return self.get(code) is not None

    def expand(self, codes: Sequence[str]) -> Expansion:
        """Turn product codes into the attributes they stand for.

        Args:
            codes: The codes a requirement names, as the OSL wrote them.

        Returns:
            The expansion. Unknown codes are reported rather than dropped, because a
            code that expands to nothing would turn "check everything in ABC" into
            "check nothing" and the delivery would pass.
        """
        attributes: list[str] = []
        seen: set[str] = set()
        by_code: dict[str, tuple[str, ...]] = {}
        unknown: dict[str, str] = {}

        for code in codes:
            asked = code.strip()
            if not asked:
                continue
            entry = self.get(asked)
            if entry is None:
                # Keyed on the squashed form, like the lookup a line above: ``ABC`` and
                # ``abc`` are one code, and reporting both would raise two findings
                # about one missing definition.
                unknown.setdefault(squashed(asked), asked)
                continue
            by_code.setdefault(entry.code, entry.attributes)
            for name in entry.attributes:
                # Squashed, like every other identity question in this module. Matching
                # on the exact string made ``SCORE_V3`` in one code and ``score-v3`` in
                # another two attributes, which is the one thing this module's opening
                # paragraph says they are not: a requirement naming both codes expanded
                # to a duplicate, and one attribute could raise two findings. The first
                # code's spelling wins, as the first definition of a code does.
                key = squashed(name)
                if key and key not in seen:
                    seen.add(key)
                    attributes.append(name)

        if unknown:
            _LOG.info("product codes: %d code(s) the catalogue does not define", len(unknown))
        return Expansion(
            attributes=tuple(attributes), by_code=by_code, unknown=tuple(unknown.values())
        )

    def beyond(self, codes: Sequence[str], delivered: Sequence[str]) -> tuple[str, ...]:
        """Attributes a delivery carries that the named codes never asked for.

        Not a failure — a delivery may legitimately carry a technical field — but worth
        a note, and worth one for two reasons rather than one: the order may be wrong,
        and **a field nobody asked for may be PII** (ADR-003).

        Matched on the name up the ladder's second rung, so a code listing ``opt_out``
        does not make a delivered ``OPT-OUT`` look like an extra field.

        Args:
            codes: The codes the requirement names.
            delivered: What the delivery actually carries, spelled as it spells them.

        Returns:
            The delivered names no named code accounts for, in delivery order. Empty
            when no named code is known, because a catalogue that cannot say what was
            asked for cannot say what was extra either.
        """
        expansion = self.expand(codes)
        if not expansion.expanded:
            return ()

        wanted: set[str] = set()
        for code in expansion.by_code:
            entry = self.get(code)
            if entry is None:  # pragma: no cover - by_code keys come from the catalogue
                continue
            for member in entry.members:
                wanted.add(squashed(member.attribute))
                wanted.add(squashed(member.delivered_as))

        return tuple(
            dict.fromkeys(
                name for name in delivered if name.strip() and squashed(name) not in wanted
            )
        )

    def conflicts(self) -> tuple[str, ...]:
        """Attributes two codes carry under different delivered names.

        Not something to resolve by picking one: a shared attribute is *one* term with
        one output name, and two codes disagreeing is a defect in the catalogue. Naming
        it is what lets an administrator fix it; choosing between them would be the
        comparison ADR-001 keeps out of a guess's hands.

        Returns:
            One line per conflicting attribute, naming the codes and both spellings,
            sorted so the answer is stable.
        """
        seen: dict[str, tuple[str, str]] = {}
        found: list[str] = []
        for entry in self.entries.values():
            for member in entry.members:
                key = squashed(member.attribute)
                if not key:
                    continue
                if key not in seen:
                    seen[key] = (entry.code, member.delivered_as)
                    continue
                other_code, other_name = seen[key]
                if squashed(other_name) != squashed(member.delivered_as):
                    found.append(
                        f"{member.attribute}: {other_code} delivers it as {other_name!r}, "
                        f"{entry.code} as {member.delivered_as!r}"
                    )
        return tuple(sorted(set(found)))
