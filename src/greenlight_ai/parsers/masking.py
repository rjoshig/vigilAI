"""Masking of report values at parse time.

Sample rows and PII never reach a prompt, a log, a fixture, or a commit (ADR-003).
Masking therefore happens here, in the parser layer, before any value is available to
the pipeline: a value that is never unmasked in memory cannot leak downstream. There is
no unmask path in v1 because there is no login (ADR-008).
"""

from __future__ import annotations

import re
from typing import Final, Iterable, Sequence

__all__ = ["DEFAULT_MASKED_COLUMNS", "is_masked_column", "mask_value"]

#: Columns masked unless the admin list says otherwise. Patterns are matched against the
#: header text case-insensitively; a trailing ``*`` matches any suffix.
DEFAULT_MASKED_COLUMNS: Final[tuple[str, ...]] = (
    "ssn",
    "ssn_last4",
    "social_security*",
    "first_name",
    "last_name",
    "middle_name",
    "full_name",
    "name",
    "address*",
    "addr*",
    "street*",
    "city",
    "zip",
    "zipcode",
    "postal*",
    "phone*",
    "email*",
    "dob",
    "date_of_birth",
    "account*",
    "acct*",
)

#: How many trailing characters a masked value keeps, so reviewers can still tell rows
#: apart without seeing the value.
_KEEP_TRAILING: Final[int] = 1

_MASK_CHAR: Final[str] = "*"


def _normalise(header: str) -> str:
    """Reduce a header to a comparable form.

    Args:
        header: The raw header text.

    Returns:
        Lowercased, stripped, with spaces and hyphens collapsed to underscores.
    """
    return re.sub(r"[\s\-]+", "_", header.strip().lower())


def is_masked_column(header: str, patterns: Sequence[str] = DEFAULT_MASKED_COLUMNS) -> bool:
    """Decide whether a column's values must be masked.

    Args:
        header: The column header as it appears in the report.
        patterns: Masked-column patterns, from the admin-ui Reference data screen. A
            trailing ``*`` makes the pattern a prefix match; everything else is exact.

    Returns:
        ``True`` when the column matches any pattern.
    """
    name = _normalise(header)
    for raw in patterns:
        pattern = _normalise(raw)
        if pattern.endswith(_MASK_CHAR):
            if name.startswith(pattern[:-1]):
                return True
        elif name == pattern:
            return True
    return False


def mask_value(value: object) -> object:
    """Replace a value with a masked stand-in of the same shape.

    Digits and letters become ``*``; separators such as ``-`` and ``@`` are kept so the
    shape of the original is still recognisable in evidence panels. The last character is
    kept so a reviewer can distinguish adjacent rows.

    Args:
        value: The value read from the report.

    Returns:
        The masked value. ``None`` and empty strings pass through unchanged, because
        masking them would invent data that is not there.
    """
    if value is None:
        return None
    text = str(value)
    if not text.strip():
        return value
    keep = _KEEP_TRAILING if len(text) > _KEEP_TRAILING else 0
    head, tail = (text[:-keep], text[-keep:]) if keep else (text, "")
    masked = "".join(_MASK_CHAR if ch.isalnum() else ch for ch in head)
    return masked + tail


def masked_headers(
    headers: Iterable[str], patterns: Sequence[str] = DEFAULT_MASKED_COLUMNS
) -> frozenset[str]:
    """Return the subset of headers that will be masked.

    Args:
        headers: The report's header row.
        patterns: Masked-column patterns.

    Returns:
        The matching headers, exactly as they appear in the report.
    """
    return frozenset(h for h in headers if is_masked_column(h, patterns))
