"""Tests for the ETL config parser."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from greenlight_ai.parsers import JsonConfigParser, ParseError, is_technical


@pytest.fixture()
def parser() -> JsonConfigParser:
    return JsonConfigParser()


def test_parses_a_generated_config(
    parser: JsonConfigParser, fixtures_root: Path, cases: dict[str, Any]
) -> None:
    document = parser.parse(fixtures_root / cases["baseline_match"]["config"])
    assert document.configuration_id == "CFG-SYNTH-BASELINE-01"
    assert document.last_modified == "2026-09-01T12:00:00Z"
    assert document.blocks


def test_list_elements_become_one_block_each(
    parser: JsonConfigParser, fixtures_root: Path, cases: dict[str, Any]
) -> None:
    document = parser.parse(fixtures_root / cases["geography_extra_state"]["config"])
    block = document.block("filters[0]")
    assert block is not None
    assert block.kind == "filters"
    assert block.content == {"field": "ST", "op": "in", "value": ["IL", "AZ", "TX"]}


def test_rule_mappings_become_one_block_each(
    parser: JsonConfigParser, fixtures_root: Path, cases: dict[str, Any]
) -> None:
    document = parser.parse(fixtures_root / cases["baseline_match"]["config"])
    block = document.block("rules.score_v3")
    assert block is not None
    assert block.content == {"field": "SCORE_V3", "op": ">=", "min": 755.0}


def test_missing_rule_produces_no_block(
    parser: JsonConfigParser, fixtures_root: Path, cases: dict[str, Any]
) -> None:
    document = parser.parse(fixtures_root / cases["rule_missing_in_config"]["config"])
    assert document.block("rules.score_v3") is None
    assert document.block("rules.age") is not None


def test_scalars_are_grouped_into_one_metadata_block(
    parser: JsonConfigParser, fixtures_root: Path, cases: dict[str, Any]
) -> None:
    document = parser.parse(fixtures_root / cases["baseline_match"]["config"])
    metadata = document.block("(metadata)")
    assert metadata is not None
    assert metadata.content["customer"] == "Acme Card Services"  # type: ignore[index]


def test_technical_blocks_are_recognised(
    parser: JsonConfigParser, fixtures_root: Path, cases: dict[str, Any]
) -> None:
    document = parser.parse(fixtures_root / cases["baseline_match"]["config"])
    logging_block = document.block("logging")
    filter_block = document.block("filters[0]")
    assert logging_block is not None and is_technical(logging_block)
    assert filter_block is not None and not is_technical(filter_block)


def test_suppressions_split_one_block_per_rule(
    parser: JsonConfigParser, fixtures_root: Path, cases: dict[str, Any]
) -> None:
    """Each suppression is one decision, so stage 4 can trace a compliance rule to it."""
    document = parser.parse(fixtures_root / cases["baseline_match"]["config"])
    assert document.block("suppressions") is None
    ofac = document.block("suppressions.ofac")
    assert ofac is not None
    assert ofac.kind == "suppressions"
    assert ofac.content is True


def test_block_as_text_is_stable(
    parser: JsonConfigParser, fixtures_root: Path, cases: dict[str, Any]
) -> None:
    document = parser.parse(fixtures_root / cases["baseline_match"]["config"])
    block = document.block("dedupe")
    assert block is not None
    assert block.as_text() == 'dedupe = {"key": ["SSN", "ZIP"]}'


def test_invalid_json_raises_parse_error(parser: JsonConfigParser, tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ParseError, match="not valid JSON"):
        parser.parse(path)


def test_missing_configuration_id_raises_parse_error(
    parser: JsonConfigParser, tmp_path: Path
) -> None:
    path = tmp_path / "no_id.json"
    path.write_text(json.dumps({"filters": []}), encoding="utf-8")
    with pytest.raises(ParseError, match="configuration_id"):
        parser.parse(path)


def test_non_object_top_level_raises_parse_error(parser: JsonConfigParser, tmp_path: Path) -> None:
    path = tmp_path / "list.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ParseError, match="JSON object"):
        parser.parse(path)


def test_missing_file_raises_parse_error(parser: JsonConfigParser, tmp_path: Path) -> None:
    with pytest.raises(ParseError):
        parser.parse(tmp_path / "absent.json")
