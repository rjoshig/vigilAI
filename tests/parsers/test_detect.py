"""Tests for working out what a workbook is (phase 6.1d).

What these pin down: the fingerprint ignores punctuation and case, a workbook of a
known layout is recognised, an unrelated workbook is refused rather than guessed at,
two equally plausible types produce a question, and each tab of a multi-tab file is
placed on its own.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from greenlight_ai.db import models
from greenlight_ai.llm.prompts.schemas import NameLocation
from greenlight_ai.db.session import create_all, create_engine, session_factory
from greenlight_ai.db.settings import DbSettings
from greenlight_ai.parsers.detect import (
    CONFIDENT_SCORE,
    Fingerprint,
    detect,
    detect_sheets,
    fingerprint_samples,
    fingerprint_workbook,
    score,
)


@pytest.fixture()
def session(tmp_path: Path) -> Session:
    """A session against a fresh SQLite file."""
    engine = create_engine(DbSettings(url=f"sqlite+pysqlite:///{tmp_path / 'detect.db'}"))
    create_all(engine)
    return session_factory(engine)()


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    """The shared volume the samples are stored under."""
    path = tmp_path / "data"
    path.mkdir()
    return path


def _report(fixtures_root: Path, cases: dict[str, Any], kind: str) -> Path:
    """The generated workbook of one report kind."""
    case = cases["geography_extra_state"]
    return fixtures_root / case["reports"][kind]


def _add_sample(
    session: Session, data_dir: Path, key: str, source: Path, type_key: str | None = None
) -> None:
    """Store one workbook as a sample of an artifact type, creating the type."""
    row = models.ArtifactType(key=key, label=key.replace("_", " ").title(), kind="report")
    session.add(row)
    session.flush()
    stored = f"samples/{key}.xlsx"
    (data_dir / "samples").mkdir(exist_ok=True)
    shutil.copyfile(source, data_dir / stored)
    session.add(
        models.ArtifactSample(
            artifact_type_id=row.id,
            label="fixture",
            filename=source.name,
            storage_path=stored,
            sheets=[sheet.name for sheet in _sheet_names(source)],
        )
    )
    session.flush()


def _sheet_names(path: Path) -> Any:
    """The parsed sheets of a workbook, for filling the stored sheet list."""
    from greenlight_ai.parsers.reports.xlsx import GenericReportParser

    return GenericReportParser("unknown").parse(path).sheets


# --- the fingerprint ----------------------------------------------------------------


def test_normalization_makes_spelling_variants_match() -> None:
    """ "Field Distribution " and "field_distribution" are the same tab name."""
    assert not Fingerprint()
    a = fingerprint_from(["Field Distribution "], ["Null %"])
    b = fingerprint_from(["field_distribution"], ["NULL---%"])
    assert a.sheets == b.sheets
    assert a.headers == b.headers
    assert score(a, b) == 1.0


def fingerprint_from(sheets: list[str], headers: list[str]) -> Fingerprint:
    """Build a fingerprint the way the parser would, without a file."""
    from greenlight_ai.parsers.base import ReportSheet
    from greenlight_ai.parsers.detect import fingerprint_sheet

    result = Fingerprint()
    for name in sheets:
        result = result.merge(
            fingerprint_sheet(ReportSheet(name=name, header=tuple(headers), rows=()))
        )
    return result


def test_sheet_and_column_evidence_is_kept_apart() -> None:
    """A tab called "State" is not the same evidence as a column called "State"."""
    as_sheet = fingerprint_from(["State"], [])
    as_header = fingerprint_from([""], ["State"])
    assert score(as_sheet, as_header) == 0.0


def test_an_empty_side_scores_zero() -> None:
    """Nothing to compare is not a match."""
    assert score(Fingerprint(), fingerprint_from(["States"], ["State"])) == 0.0


# --- detection against stored samples -----------------------------------------------


def test_a_workbook_of_a_stored_layout_is_recognised(
    session: Session, data_dir: Path, fixtures_root: Path, cases: dict[str, Any]
) -> None:
    """The whole point: the user does not have to know what their file is called."""
    _add_sample(session, data_dir, "counts", _report(fixtures_root, cases, "counts"))
    _add_sample(session, data_dir, "dirt", _report(fixtures_root, cases, "dirt"))

    result = detect(session, _report(fixtures_root, cases, "counts"), data_dir)
    assert result.verdict == "confident"
    assert result.best is not None
    assert result.best.key == "counts"
    assert result.best.score >= CONFIDENT_SCORE


def test_an_unrelated_workbook_is_unknown(
    session: Session, data_dir: Path, fixtures_root: Path, cases: dict[str, Any]
) -> None:
    """A wrong silent assignment is worse than admitting ignorance."""
    _add_sample(session, data_dir, "dirt", _report(fixtures_root, cases, "dirt"))

    result = detect(session, _report(fixtures_root, cases, "state_distribution"), data_dir)
    assert result.verdict == "unknown"
    assert result.best is None
    assert "does not resemble" in result.reason


def test_nothing_stored_means_nothing_detected(
    session: Session, data_dir: Path, fixtures_root: Path, cases: dict[str, Any]
) -> None:
    """With no samples there is no honest guess to make."""
    result = detect(session, _report(fixtures_root, cases, "counts"), data_dir)
    assert result.verdict == "unknown"
    assert detect_sheets(session, _report(fixtures_root, cases, "counts"), data_dir) == {}


def test_two_plausible_types_produce_a_question(
    session: Session, data_dir: Path, fixtures_root: Path, cases: dict[str, Any]
) -> None:
    """Two types sharing a layout must be asked about, not chosen between."""
    source = _report(fixtures_root, cases, "field_distribution")
    _add_sample(session, data_dir, "field_distribution", source)
    _add_sample(session, data_dir, "field_distribution_v2", source)

    result = detect(session, source, data_dir)
    assert result.verdict == "ambiguous"
    assert [c.key for c in result.candidates][:2] == [
        "field_distribution",
        "field_distribution_v2",
    ]
    assert "pick the right one" in result.reason


def test_each_tab_of_a_workbook_is_placed_on_its_own(
    session: Session, data_dir: Path, fixtures_root: Path, cases: dict[str, Any]
) -> None:
    """A field distribution can arrive as several tabs, and the DIRT holds three."""
    dirt = _report(fixtures_root, cases, "dirt")
    _add_sample(session, data_dir, "dirt", dirt)
    _add_sample(session, data_dir, "counts", _report(fixtures_root, cases, "counts"))

    per_sheet = detect_sheets(session, dirt, data_dir)
    assert len(per_sheet) > 1
    assert all(r.best is not None and r.best.key == "dirt" for r in per_sheet.values())

    flow = detect_sheets(session, _report(fixtures_root, cases, "counts"), data_dir)
    assert [r.best.key for r in flow.values() if r.best] == ["counts"]


def test_the_stored_sheet_list_carries_the_fingerprint(
    session: Session, data_dir: Path, fixtures_root: Path, cases: dict[str, Any]
) -> None:
    """Sheet names come from the column filled in at upload, not from the file."""
    source = _report(fixtures_root, cases, "counts")
    _add_sample(session, data_dir, "counts", source)
    (data_dir / "samples" / "counts.xlsx").unlink()

    prints = fingerprint_samples(session, data_dir)
    assert prints["counts"].sheets == {"flow"}
    assert prints["counts"].headers == frozenset()


def test_a_workbook_fingerprint_pools_every_sheet(
    fixtures_root: Path, cases: dict[str, Any]
) -> None:
    """The DIRT's three tabs all contribute."""
    print_ = fingerprint_workbook(_report(fixtures_root, cases, "dirt"))
    assert {"summary", "attributes", "sample"} <= print_.sheets
    assert "attribute" in print_.headers


# --- the tiebreak (Phase 6.21e) --------------------------------------------------------


class _Chooser:
    """Answers the locator with a fixed label, and keeps what it was shown."""

    def __init__(self, name: str, confidence: float = 0.85) -> None:
        self.name = name
        self.confidence = confidence
        self.user = ""
        self.calls = 0

    def complete(self, system: str, user: str, schema: Any, **kwargs: Any) -> Any:
        self.calls += 1
        self.user = user
        answer = NameLocation(
            verdict="found" if self.name else "unsure",
            name=self.name,
            reason="the sheet names read like that type.",
            confidence=self.confidence,
        )

        class _Result:
            def parsed(self, _schema: Any) -> Any:
                return answer

        return _Result()


def _tie(session: Session, data_dir: Path, fixtures_root: Path, cases: dict[str, Any]) -> Path:
    """Two types sharing one layout, which is what makes a tie."""
    source = _report(fixtures_root, cases, "field_distribution")
    _add_sample(session, data_dir, "field_distribution", source)
    _add_sample(session, data_dir, "field_distribution_v2", source)
    return source


def test_a_tie_can_be_broken_by_the_model(
    session: Session, data_dir: Path, fixtures_root: Path, cases: dict[str, Any]
) -> None:
    """The tiebreak the phase doc allowed and 6.1d deliberately left unbuilt."""
    source = _tie(session, data_dir, fixtures_root, cases)
    client = _Chooser("field_distribution_v2")

    result = detect(session, source, data_dir, client)

    assert result.verdict == "reasoned"
    assert result.best is not None and result.best.key == "field_distribution_v2"
    assert "Check that before you submit" in result.reason


def test_the_tiebreak_is_shown_sheet_names_and_type_labels_only(
    session: Session, data_dir: Path, fixtures_root: Path, cases: dict[str, Any]
) -> None:
    """ADR-003: it reads what the workbook is called, never what is in it."""
    source = _tie(session, data_dir, fixtures_root, cases)
    client = _Chooser("field_distribution_v2")
    detect(session, source, data_dir, client)

    # Labels, because a key says nothing about what a type is.
    assert "Field Distribution V2" in client.user
    assert "which report type this workbook is" in client.user
    assert "its sheets are named" in client.user.lower()


def test_the_tiebreak_can_only_narrow_the_shortlist(
    session: Session, data_dir: Path, fixtures_root: Path, cases: dict[str, Any]
) -> None:
    """A type code did not shortlist cannot be introduced by an answer."""
    source = _tie(session, data_dir, fixtures_root, cases)
    client = _Chooser("something else entirely")

    result = detect(session, source, data_dir, client)
    assert result.verdict == "ambiguous"


def test_an_unsure_answer_leaves_the_question_with_the_person(
    session: Session, data_dir: Path, fixtures_root: Path, cases: dict[str, Any]
) -> None:
    source = _tie(session, data_dir, fixtures_root, cases)

    result = detect(session, source, data_dir, _Chooser(""))
    assert result.verdict == "ambiguous"
    assert "pick the right one" in result.reason


def test_a_confident_detection_never_costs_a_call(
    session: Session, data_dir: Path, fixtures_root: Path, cases: dict[str, Any]
) -> None:
    """The tiebreak attaches to ties only, so the ordinary upload is unchanged."""
    source = _report(fixtures_root, cases, "dirt")
    _add_sample(session, data_dir, "dirt", source)
    client = _Chooser("dirt")

    result = detect(session, source, data_dir, client)
    assert result.verdict == "confident"
    assert client.calls == 0


def test_no_client_leaves_the_tie_a_tie(
    session: Session, data_dir: Path, fixtures_root: Path, cases: dict[str, Any]
) -> None:
    """Which is the behaviour before this phase, and is never an error."""
    source = _tie(session, data_dir, fixtures_root, cases)
    assert detect(session, source, data_dir, None).verdict == "ambiguous"
