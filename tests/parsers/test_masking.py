"""Tests for value masking (ADR-003)."""

from __future__ import annotations

import pytest

from greenlight_ai.parsers.masking import (
    DEFAULT_MASKED_COLUMNS,
    is_masked_column,
    mask_value,
    masked_headers,
)


@pytest.mark.parametrize(
    "header",
    ["SSN", "ssn", "SSN_LAST4", "First_Name", "first name", "EMAIL_ADDRESS", "addr_line_1", "DOB"],
)
def test_pii_headers_are_masked(header: str) -> None:
    assert is_masked_column(header)


@pytest.mark.parametrize("header", ["SCORE_V3", "AGE", "ST", "REV_UTIL", "OPEN_TRADES", "state"])
def test_analytic_headers_are_not_masked(header: str) -> None:
    assert not is_masked_column(header)


def test_prefix_patterns_match_suffixes() -> None:
    assert is_masked_column("address_line_2")
    assert is_masked_column("phone_mobile")
    assert not is_masked_column("addressable_market", ["address"])


def test_custom_pattern_list_replaces_the_default() -> None:
    assert is_masked_column("CUSTOM_FIELD", ["custom_field"])
    assert not is_masked_column("SSN", ["custom_field"])


def test_mask_value_keeps_shape_and_last_character() -> None:
    assert mask_value("123-45-6789") == "***-**-***9"
    assert mask_value("Jane") == "***e"


def test_mask_value_passes_through_empty_and_none() -> None:
    assert mask_value(None) is None
    assert mask_value("") == ""
    assert mask_value("   ") == "   "


def test_mask_value_handles_non_strings() -> None:
    assert mask_value(42) == "*2"


def test_masked_headers_returns_original_spellings() -> None:
    headers = ["ROW", "ST", "SSN_LAST4", "FIRST_NAME"]
    assert masked_headers(headers) == frozenset({"SSN_LAST4", "FIRST_NAME"})


def test_default_list_covers_the_obvious_identifiers() -> None:
    for name in ("ssn", "first_name", "last_name", "dob", "email*", "phone*"):
        assert name in DEFAULT_MASKED_COLUMNS
