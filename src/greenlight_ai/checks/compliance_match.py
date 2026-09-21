"""Finding where a compliance rule is implemented, in code (Phase 6.15, option C).

A compliance rule names a configuration path that must exist. Until this module the
check was ``rule.json_path_contains in block.json_path`` — a substring match — and it
was measured against configurations implementing the same three controls under names a
different customer might use:

===========================================  ====================
configuration shape                          false HIGH findings
===========================================  ====================
exactly as the rules expect                  0
``opt_out`` where the rule says ``optout``   1
grouped under ``exclusions``                 3 of 3
vendor names (``sdn_screening``)             3 of 3
``suppressions.lists.ofac``                  3 of 3
===========================================  ====================

The last row is the one that matters most. ``suppressions.lists.ofac`` does not contain
the substring ``suppressions.ofac``, so **one extra level of nesting** turned three
correct controls into three high-severity findings that were wrong.

This module widens the test deterministically. Four ways to match, and a path counts
if **any** of them does — so nothing that matched before stops matching, and each one
removes a row from that table:

1. **Normalised substring.** What the old check did, with case, underscores and hyphens
   treated as noise. ``opt_out`` now finds ``optout``. This is listed first because it
   is what preserves every match the old behaviour made, including the accidental ones:
   ``suppressions.ofac`` found ``suppressions.ofac_sdn`` by luck of substring, and that
   happened to be the right answer.
2. **Segments in order.** The rule's segments as an ordered subsequence of the path's,
   so an extra level of nesting between two named keys does not break the match.
3. **Keys inside the block.** The parser groups a nested object into one block —
   ``{"suppressions": {"lists": {"ofac": true}}}`` is the single path
   ``suppressions.lists`` holding ``{"ofac": true}``. The control is real and it is in
   the *content*, so the content's keys are searched too. This is the row that cost
   three false high-severity findings.
4. **Alternates.** Other paths that also count, written by a person, for the case no
   amount of normalising reaches: a customer whose OFAC screening is called
   ``suppressions.sdn_screening``.

What it deliberately does **not** do is guess. An alternate is written by a person, and
a rule that matches nothing still reports that it matches nothing — this narrows the
gap between "absent" and "spelled differently" without pretending to close it. Closing
it is what the model is for, and that is the next step rather than this one.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Final, Iterable, Sequence

from greenlight_ai.resolve.normalize import squashed

__all__ = ["MatchedPath", "matches", "normalize_segment", "segments"]

_LOG: Final = logging.getLogger(__name__)

#: Array indices: ``rules[2]`` is the same key as ``rules``.
_INDEX: Final = re.compile(r"\[\d+\]")


@dataclass(frozen=True, slots=True)
class MatchedPath:
    """One configuration path a rule was found at.

    Attributes:
        json_path: The configuration path, verbatim.
        via: The rule path that matched it — the rule's own, or one of its alternates.
        exact: Whether the rule's path matched the whole of the configuration path's
            segments rather than a subsequence of them. An exact match is the ordinary
            case; a subsequence match means the control sits deeper than the rule says,
            which is worth being able to report.
    """

    json_path: str
    via: str
    exact: bool = True


def normalize_segment(value: str) -> str:
    """Reduce one path segment to a comparable form.

    Args:
        value: A key from a configuration path, e.g. ``"opt_out"`` or ``"rules[2]"``.

    Returns:
        Lowercased, array indices dropped, and separators removed — so ``opt_out``,
        ``optOut`` and ``OPT-OUT`` all compare alike. The removing is
        :func:`greenlight_ai.resolve.normalize.squashed`, which is the one
        implementation of it in the product (Phase 6.21a).
    """
    return squashed(_INDEX.sub("", value))


def segments(json_path: str) -> tuple[str, ...]:
    """Split a configuration path into normalised segments.

    Args:
        json_path: A path such as ``"suppressions.lists.ofac"``.

    Returns:
        The segments, normalised, with empty ones dropped.
    """
    return tuple(part for part in (normalize_segment(p) for p in json_path.split(".")) if part)


def _covers(wanted: Sequence[str], actual: Sequence[str]) -> bool:
    """Whether ``wanted`` appears in ``actual`` in order, not necessarily adjacently.

    A subsequence rather than a contiguous run, because the thing being tolerated is an
    extra level of nesting between two segments the rule names — a customer who groups
    their suppression flags under a ``lists`` key has not stopped applying them.

    Args:
        wanted: The rule's segments, normalised.
        actual: The configuration path's segments, normalised.

    Returns:
        True when every wanted segment is found in order.
    """
    if not wanted:
        return False
    index = 0
    for segment in actual:
        if segment == wanted[index]:
            index += 1
            if index == len(wanted):
                return True
    return False


def _content_keys(content: object, depth: int = 3) -> set[str]:
    """Every key inside a block's content, normalised.

    The parser groups a nested object into one block, so a control the rule names may
    be a key *inside* the block rather than part of its path. Bounded depth, because a
    configuration is not a search space and an unbounded walk over a large one is a
    cost nobody asked for.

    Args:
        content: The block's decoded content.
        depth: How far in to look.

    Returns:
        The normalised keys found.
    """
    if depth <= 0 or not isinstance(content, dict):
        return set()
    keys: set[str] = set()
    for key, value in content.items():
        keys.add(normalize_segment(str(key)))
        keys |= _content_keys(value, depth - 1)
    return keys


def matches(
    rule_path: str,
    blocks: Iterable[tuple[str, object]],
    alternates: Sequence[str] = (),
) -> tuple[MatchedPath, ...]:
    """Find every configuration block that implements a rule.

    Four tests, and a block counts if any of them passes, so nothing that matched
    before stops matching. See this module's documentation for why each exists.

    Args:
        rule_path: The path the rule names, e.g. ``"suppressions.ofac"``.
        blocks: ``(json_path, content)`` for every block in the parsed configuration.
        alternates: Other paths that also count, written by an administrator for the
            case no amount of normalising reaches.

    Returns:
        What matched, in the order given, each saying which rule path found it and
        whether it sat exactly where the rule said. Empty when nothing implements the
        rule — which is a real answer, and still a finding.
    """
    candidates = [path for path in (rule_path, *alternates) if path and path.strip()]
    if not candidates:
        return ()

    found: list[MatchedPath] = []
    for json_path, content in blocks:
        actual = segments(json_path)
        flat = "".join(actual)
        keys = _content_keys(content)
        for candidate in candidates:
            wanted = segments(candidate)
            if not wanted:
                continue
            by_substring = "".join(wanted) in flat
            by_segments = _covers(wanted, actual)
            # The rule's leading segments locate the block; its last names the control,
            # which may be a key inside rather than part of the path.
            by_content = bool(keys) and wanted[-1] in keys and _covers(wanted[:-1], actual)
            if by_substring or by_segments or by_content:
                found.append(
                    MatchedPath(
                        json_path=json_path,
                        via=candidate,
                        exact=by_substring and actual[-len(wanted) :] == wanted,
                    )
                )
                break

    if found and found[0].via != rule_path:
        _LOG.info("compliance %r matched via alternate %r", rule_path, found[0].via)
    return tuple(found)
