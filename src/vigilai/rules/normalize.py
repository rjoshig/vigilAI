"""Normalizers: turn what a document says into what code can compare.

Stage 2 and stage 3 read meaning; everything here is deterministic (ADR-001). State
names become codes, prose ranges become intervals, lists become sets, and attribute
names become canonical via the alias table. Normalising once, here, is what allows
stage 5 to be a set of small comparisons rather than a pile of special cases.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Iterable, Mapping, Sequence

__all__ = [
    "STATE_CODES",
    "Interval",
    "normalize_state",
    "normalize_states",
    "normalize_field_name",
    "AliasTable",
    "interval_from_condition",
    "parse_number",
]

#: US states, DC, and the territories that appear in credit data. Kept here rather than
#: pulled from a package so the mapping is auditable and stable across environments.
STATE_CODES: Final[dict[str, str]] = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "district of columbia": "DC",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
    "puerto rico": "PR",
    "guam": "GU",
    "virgin islands": "VI",
    "american samoa": "AS",
    "northern mariana islands": "MP",
}

#: Every valid two-letter code, for validating input that is already a code.
_VALID_CODES: Final[frozenset[str]] = frozenset(STATE_CODES.values())

_NUMBER_RE: Final = re.compile(r"-?\d+(?:\.\d+)?")


def normalize_state(value: str) -> str | None:
    """Convert a state name or code to its two-letter code.

    Args:
        value: A state name (``"Illinois"``) or code (``"IL"``), any case.

    Returns:
        The uppercase code, or ``None`` when the value is not a recognised state. The
        caller decides what an unrecognised state means; silently dropping it would hide
        a real finding.
    """
    text = value.strip()
    if not text:
        return None
    upper = text.upper()
    if len(upper) == 2 and upper in _VALID_CODES:
        return upper
    return STATE_CODES.get(text.lower())


def normalize_states(values: Iterable[str]) -> tuple[frozenset[str], tuple[str, ...]]:
    """Normalise a collection of states, keeping the ones that failed.

    Args:
        values: State names or codes.

    Returns:
        A pair of ``(codes, unrecognised)``. The unrecognised values are returned rather
        than dropped so the pipeline can raise a finding about them.
    """
    codes: set[str] = set()
    unrecognised: list[str] = []
    for value in values:
        code = normalize_state(value)
        if code is None:
            unrecognised.append(value)
        else:
            codes.add(code)
    return frozenset(codes), tuple(unrecognised)


def normalize_field_name(name: str) -> str:
    """Reduce an attribute name to a comparable form.

    Args:
        name: The attribute name as written in any of the three artefacts.

    Returns:
        Lowercased, with runs of spaces, hyphens, and underscores collapsed to a single
        underscore, and surrounding punctuation removed.
    """
    text = name.strip().lower()
    text = re.sub(r"[^\w\s\-]", "", text)
    return re.sub(r"[\s\-_]+", "_", text).strip("_")


@dataclass(frozen=True, slots=True)
class AliasTable:
    """Maps the many names one attribute goes by onto a canonical name.

    The table is maintained in the admin-ui (Reference data) and seeded per customer.
    Lookups are normalised on both sides, so ``"V3 score"``, ``"v3_score"``, and
    ``"V3-Score"`` all resolve alike.

    Attributes:
        canonical_by_alias: Normalised alias to canonical name.
    """

    canonical_by_alias: Mapping[str, str]

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Sequence[str]]) -> AliasTable:
        """Build a table from canonical name to its aliases.

        Args:
            mapping: Canonical name to the names it is also known by. The canonical name
                is registered as an alias of itself, so lookups always succeed for it.

        Returns:
            The table.
        """
        table: dict[str, str] = {}
        for canonical, aliases in mapping.items():
            table[normalize_field_name(canonical)] = canonical
            for alias in aliases:
                table[normalize_field_name(alias)] = canonical
        return cls(canonical_by_alias=table)

    def resolve(self, name: str) -> str:
        """Resolve a name to its canonical form.

        Args:
            name: The attribute name as written.

        Returns:
            The canonical name when the alias is known, otherwise the normalised input.
            Returning the input rather than raising keeps an unknown attribute visible:
            it will fail to match and become a finding, which is the correct outcome.
        """
        key = normalize_field_name(name)
        return self.canonical_by_alias.get(key, key)

    def knows(self, name: str) -> bool:
        """Whether the table has an entry for a name.

        Args:
            name: The attribute name as written.

        Returns:
            ``True`` when the alias is registered.
        """
        return normalize_field_name(name) in self.canonical_by_alias


@dataclass(frozen=True, slots=True)
class Interval:
    """A numeric range with explicit boundary inclusion.

    Operator differences are a finding type of their own (``docs/design.md``
    "Findings": "Operator mismatch"), so ``>= 21`` and ``> 21`` must stay distinguishable
    all the way through comparison. That is why inclusivity is carried explicitly rather
    than folded into the bound.

    Attributes:
        lower: The lower bound, or ``None`` when unbounded below.
        upper: The upper bound, or ``None`` when unbounded above.
        lower_inclusive: Whether the lower bound itself satisfies the rule.
        upper_inclusive: Whether the upper bound itself satisfies the rule.
    """

    lower: float | None = None
    upper: float | None = None
    lower_inclusive: bool = True
    upper_inclusive: bool = True

    def contains(self, value: float) -> bool:
        """Test a value against the interval.

        Args:
            value: The number to test.

        Returns:
            ``True`` when the value satisfies both bounds.
        """
        if self.lower is not None:
            if self.lower_inclusive:
                if value < self.lower:
                    return False
            elif value <= self.lower:
                return False
        if self.upper is not None:
            if self.upper_inclusive:
                if value > self.upper:
                    return False
            elif value >= self.upper:
                return False
        return True

    def same_bounds_as(self, other: Interval) -> bool:
        """Compare only the numbers, ignoring inclusivity.

        Used to tell a value mismatch (``755`` vs ``750``) from an operator mismatch
        (``>`` vs ``>=``), which are separate finding types.

        Args:
            other: The interval to compare with.

        Returns:
            ``True`` when both bounds are numerically equal.
        """
        return self.lower == other.lower and self.upper == other.upper

    def __str__(self) -> str:
        """Render the interval in standard mathematical notation.

        Returns:
            E.g. ``"[21, ∞)"`` or ``"(-∞, 0.6)"``.
        """
        left = "[" if self.lower_inclusive and self.lower is not None else "("
        right = "]" if self.upper_inclusive and self.upper is not None else ")"
        low = "-∞" if self.lower is None else f"{self.lower:g}"
        high = "∞" if self.upper is None else f"{self.upper:g}"
        return f"{left}{low}, {high}{right}"


#: Maps an operator to the interval of values that *satisfy* it.
_INTERVAL_BY_OPERATOR: Final[dict[str, tuple[str, bool]]] = {
    ">=": ("lower", True),
    ">": ("lower", False),
    "<=": ("upper", True),
    "<": ("upper", False),
}


def interval_from_condition(operator: str, value: object) -> Interval | None:
    """Build the interval of values a condition accepts.

    Args:
        operator: One of the numeric operators, or ``between``, or ``=``.
        value: The comparison value; a two-element sequence for ``between``.

    Returns:
        The interval, or ``None`` when the operator is not a range comparison (``in``,
        ``is_null``, and the like have no interval).

    Raises:
        ValueError: When the value cannot be read as a number, or ``between`` does not
            carry exactly two bounds.
    """
    if operator == "between":
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ValueError("operator 'between' requires exactly two bounds")
        low, high = parse_number(value[0]), parse_number(value[1])
        return Interval(lower=low, upper=high, lower_inclusive=True, upper_inclusive=True)
    if operator == "=":
        number = parse_number(value)
        return Interval(lower=number, upper=number, lower_inclusive=True, upper_inclusive=True)
    if operator not in _INTERVAL_BY_OPERATOR:
        return None
    side, inclusive = _INTERVAL_BY_OPERATOR[operator]
    number = parse_number(value)
    if side == "lower":
        return Interval(lower=number, lower_inclusive=inclusive)
    return Interval(upper=number, upper_inclusive=inclusive)


def parse_number(value: object) -> float:
    """Read a number out of whatever the document wrote.

    Handles the forms specifications actually use: ``755``, ``"755"``, ``"1,000,000"``,
    ``"60%"``, ``"$40,000"``.

    Args:
        value: The value as parsed from a document.

    Returns:
        The number. A percentage is converted to its fractional value, because that is
        how the config and the reports express it.

    Raises:
        ValueError: When no number can be read.
    """
    if isinstance(value, bool):
        raise ValueError(f"expected a number, got the boolean {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    is_percent = text.endswith("%")
    cleaned = text.replace(",", "").replace("$", "").rstrip("%").strip()
    match = _NUMBER_RE.search(cleaned)
    if match is None:
        raise ValueError(f"no number found in {value!r}")
    number = float(match.group())
    return number / 100.0 if is_percent else number
