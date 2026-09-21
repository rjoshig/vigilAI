"""Trying a setup against the samples (Phase 6.21f).

An administrator could define an artifact type, write a guide, confirm meaning entries
and author checks, and the only way to find out whether any of it fired was for
somebody else to submit a real delivery. This closes that loop.

What these pin down is the honesty of it. A rehearsal that overstated what it knew
would be worse than none: it answers *is this wired up*, it says so, and it never
calls a model or stores anything — which is what makes it safe to press while editing.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.db import catalog, models
from greenlight_ai.db.settings import DbSettings


@pytest.fixture()
def data_dir(db_settings: DbSettings) -> Path:
    """The shared volume the API serves from, so a sample is where the endpoint looks."""
    db_settings.data_dir.mkdir(parents=True, exist_ok=True)
    return db_settings.data_dir


@pytest.fixture()
def session(factory: sessionmaker[Session]) -> Iterator[Session]:
    with factory() as open_session:
        catalog.seed_defaults(open_session)
        open_session.commit()
        yield open_session


def _sample(
    session: Session,
    data_dir: Path,
    key: str,
    source: Path,
    scope_code: str = "",
) -> None:
    """Store one sample workbook against an artifact type, as the API does."""
    artifact = session.query(models.ArtifactType).filter_by(key=key).one()
    stored = Path("samples") / f"{key}-{scope_code or 'all'}.xlsx"
    (data_dir / stored).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(source, data_dir / stored)
    session.add(
        models.ArtifactSample(
            artifact_type_id=artifact.id,
            scope_code=scope_code,
            filename=source.name,
            storage_path=str(stored),
            sha256="x" * 64,
            size_bytes=(data_dir / stored).stat().st_size,
        )
    )
    session.flush()


def _report(fixtures_root: Path, cases: dict[str, Any], kind: str) -> Path:
    return fixtures_root / cases["baseline_match"]["reports"][kind]


def test_it_says_what_it_read(
    client: TestClient,
    api: str,
    session: Session,
    data_dir: Path,
    fixtures_root: Path,
    cases: dict[str, Any],
) -> None:
    """The first question a setup has: can the tool open these files at all."""
    _sample(session, data_dir, "dirt", _report(fixtures_root, cases, "dirt"))
    session.commit()

    result = client.get(f"{api}/admin/rehearsal").json()
    dirt = next(entry for entry in result["artifacts"] if entry["key"] == "dirt")

    assert dirt["error"] == ""
    assert dirt["sample_count"] == 1
    assert "Attributes" in dirt["sheets"]
    assert dirt["resolved"]["Attributes"] == "Attributes"


def test_a_drifted_layout_shows_what_it_was_read_as(
    client: TestClient,
    api: str,
    session: Session,
    data_dir: Path,
    fixtures_root: Path,
    cases: dict[str, Any],
) -> None:
    """The whole of 6.21a, visible before a real delivery meets it."""
    _sample(session, data_dir, "dirt", fixtures_root / cases["layout_drift"]["reports"]["dirt"])
    session.commit()

    result = client.get(f"{api}/admin/rehearsal").json()
    dirt = next(entry for entry in result["artifacts"] if entry["key"] == "dirt")

    assert dirt["resolved"]["Attributes"] == "Attribute Summary"
    assert dirt["unresolved"] == [], "the one sheet the DIRT checks need resolves in code"


def test_a_sheet_no_rung_reaches_is_listed_rather_than_hidden(
    client: TestClient,
    api: str,
    session: Session,
    data_dir: Path,
    fixtures_root: Path,
    cases: dict[str, Any],
) -> None:
    """The state finder should show the gap before a reviewer meets it as a non-answer."""
    # A DIRT filed as the state distribution: the wrong workbook in the right slot,
    # which is exactly what a rehearsal should catch before a reviewer does.
    _sample(session, data_dir, "state_distribution", _report(fixtures_root, cases, "dirt"))
    session.commit()

    result = client.get(f"{api}/admin/rehearsal").json()
    states = next(entry for entry in result["artifacts"] if entry["key"] == "state_distribution")
    assert "States" in states["unresolved"]


def test_a_pointer_that_resolves_shows_what_it_found(
    client: TestClient,
    api: str,
    session: Session,
    data_dir: Path,
    fixtures_root: Path,
    cases: dict[str, Any],
) -> None:
    _sample(session, data_dir, "counts", _report(fixtures_root, cases, "counts"))
    session.add(
        models.NamedValueRow(
            name="accepts_count",
            report_type="counts",
            sheet="Flow",
            locator={"kind": "label", "label": "Accepts", "value_column": 3},
            description="Accepted records",
        )
    )
    session.commit()

    result = client.get(f"{api}/admin/rehearsal").json()
    pointer = next(entry for entry in result["named_values"] if entry["name"] == "accepts_count")

    assert pointer["found"] is True
    assert pointer["value"] != ""
    assert pointer["description"] == "Accepted records"


def test_a_pointer_that_resolves_to_nothing_says_so(
    client: TestClient, api: str, session: Session
) -> None:
    """With no sample there is nothing to resolve against, and that is the answer."""
    session.add(
        models.NamedValueRow(
            name="missing_count",
            report_type="counts",
            sheet="Flow",
            locator={"kind": "label", "label": "Nothing here"},
            description="",
        )
    )
    session.commit()

    result = client.get(f"{api}/admin/rehearsal").json()
    assert result["named_values"][0]["found"] is False


def test_a_check_is_evaluated_over_the_samples(
    client: TestClient,
    api: str,
    session: Session,
    data_dir: Path,
    fixtures_root: Path,
    cases: dict[str, Any],
) -> None:
    """The design doc's own example, run before anybody submits anything."""
    _sample(session, data_dir, "counts", _report(fixtures_root, cases, "counts"))
    for name, label in (("accepts_count", "Accepts"), ("rejects_count", "Rejects")):
        session.add(
            models.NamedValueRow(
                name=name,
                report_type="counts",
                sheet="Flow",
                locator={"kind": "label", "label": label, "value_column": 3},
            )
        )
    session.add(
        models.CheckDefinitionRow(
            name="accepts_below_rejects",
            version=1,
            kind="expression",
            expression="accepts_count <= rejects_count",
            reasoning="Most of a prescreen is rejected.",
            severity="medium",
            state="active",
        )
    )
    session.commit()

    result = client.get(f"{api}/admin/rehearsal").json()
    check = next(entry for entry in result["checks"] if entry["name"] == "accepts_below_rejects")

    assert check["passed"] is True
    assert "accepts_count" in check["detail"], "it shows what it read, not just a verdict"


def test_a_check_missing_a_value_reports_it_as_the_run_would(
    client: TestClient, api: str, session: Session
) -> None:
    """``None``, not ``False``: a check that could not run has found nothing."""
    session.add(
        models.CheckDefinitionRow(
            name="cannot_run",
            version=1,
            kind="expression",
            expression="nowhere_count <= 10",
            reasoning="",
            severity="medium",
            state="active",
        )
    )
    session.commit()

    check = client.get(f"{api}/admin/rehearsal").json()["checks"][0]
    assert check["passed"] is None
    assert "could not evaluate" in check["detail"]


def test_a_judgment_check_says_why_it_cannot_be_rehearsed(
    client: TestClient, api: str, session: Session
) -> None:
    """Because rehearsing it would spend a model call, which this never does."""
    session.add(
        models.CheckDefinitionRow(
            name="a_judgment",
            version=1,
            kind="judgment",
            instruction="Is the delivery plausible?",
            value_names=["accepts_count"],
            reasoning="",
            severity="review",
            state="active",
        )
    )
    session.commit()

    check = client.get(f"{api}/admin/rehearsal").json()["checks"][0]
    assert check["passed"] is None
    assert "without spending a call" in check["detail"]


def test_a_retired_check_is_not_rehearsed(client: TestClient, api: str, session: Session) -> None:
    session.add(
        models.CheckDefinitionRow(
            name="gone",
            version=1,
            kind="expression",
            expression="1 <= 2",
            reasoning="",
            severity="low",
            state="retired",
        )
    )
    session.commit()
    assert client.get(f"{api}/admin/rehearsal").json()["checks"] == []


def test_it_says_what_it_cannot_tell_anybody(client: TestClient, api: str) -> None:
    """A rehearsal that overstated what it knew would be worse than none."""
    notes = " ".join(client.get(f"{api}/admin/rehearsal").json()["notes"])

    assert "No model was called and nothing was stored" in notes
    assert "not whether it asks the right questions" in notes
    assert "No sample could be read" in notes, "with nothing uploaded it must say so"


def test_a_shadow_check_is_marked_as_one(client: TestClient, api: str, session: Session) -> None:
    """A passing check nobody sees must not read as one that is live."""
    session.add(
        models.CheckDefinitionRow(
            name="in_shadow",
            version=1,
            kind="expression",
            expression="1 <= 2",
            reasoning="",
            severity="low",
            state="shadow",
        )
    )
    session.commit()

    assert client.get(f"{api}/admin/rehearsal").json()["checks"][0]["shadow"] is True
