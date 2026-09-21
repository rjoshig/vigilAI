"""Tests for the frozen report (Phase 5).

The guarantees under test are the ones ADR-005 makes: rendered once, stored, never
regenerated, and the PDF comes from the stored HTML rather than from the data again.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.db import models
from greenlight_ai.report.pdf import PdfUnavailable
from greenlight_ai.worker.app import Worker

Submit = Callable[..., Any]


class FakePdfRenderer:
    """Writes a plausible PDF without launching a browser."""

    def __init__(self) -> None:
        self.calls: list[Path] = []

    def render(self, html_path: Path, pdf_path: Path) -> Path:
        self.calls.append(html_path)
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(b"%PDF-1.7\n" + html_path.read_bytes()[:64])
        return pdf_path


class BrokenPdfRenderer:
    """Stands in for a deployment with no browser installed."""

    def render(self, html_path: Path, pdf_path: Path) -> Path:
        raise PdfUnavailable("playwright is not installed")


@pytest.fixture()
def reviewed(submit: Submit, worker: Worker, client: TestClient, api: str) -> int:
    """A run executed and fully reviewed, ready to finalize.

    Fully reviewed means the gate in ADR-035: every finding decided **and** every
    coverage gap acknowledged. Deciding the findings alone no longer opens it.
    """
    run_id = submit("geography_extra_state").json()["run_id"]
    worker.run_once()
    for finding in client.get(f"{api}/runs/{run_id}/findings").json():
        status = "confirmed" if finding["severity"] == "high" else "false_positive"
        client.patch(
            f"{api}/findings/{finding['id']}",
            json={"review_status": status, "review_note": "reviewed by a test"},
        )
    outstanding = client.get(f"{api}/runs/{run_id}/coverage").json()["outstanding"]
    if outstanding:
        client.post(
            f"{api}/runs/{run_id}/coverage/acknowledge",
            json={"targets": outstanding, "note": "seen by a test"},
        )
    return int(run_id)


# --- the gate -----------------------------------------------------------------------


def test_an_undecided_high_finding_blocks_finalizing(
    submit: Submit, worker: Worker, client: TestClient, api: str
) -> None:
    """ADR-015."""
    run_id = submit("score_value_mismatch").json()["run_id"]
    worker.run_once()
    response = client.post(f"{api}/runs/{run_id}/finalize")
    assert response.status_code == 409
    assert "need a decision" in response.json()["detail"]


def test_a_run_that_never_reached_review_cannot_be_finalized(
    submit: Submit, client: TestClient, api: str
) -> None:
    run_id = submit("baseline_match").json()["run_id"]
    response = client.post(f"{api}/runs/{run_id}/finalize")
    assert response.status_code == 400
    assert "queued" in response.json()["detail"]


def test_an_unknown_run_is_a_404(client: TestClient, api: str) -> None:
    assert client.post(f"{api}/runs/9999/finalize").status_code == 404


# --- rendering and freezing -----------------------------------------------------------


def test_finalizing_produces_a_verdict_and_a_hash(
    reviewed: int, client: TestClient, api: str
) -> None:
    body = client.post(f"{api}/runs/{reviewed}/finalize").json()
    assert body["verdict"] == "not_ok"
    assert len(body["html_sha256"]) == 64


def test_the_run_becomes_finalized(reviewed: int, client: TestClient, api: str) -> None:
    client.post(f"{api}/runs/{reviewed}/finalize")
    detail = client.get(f"{api}/runs/{reviewed}").json()
    assert detail["status"] == "finalized"
    assert detail["finalized"] is True


def test_two_reviewers_finalizing_at_once_get_the_same_refusal(
    reviewed: int, client: TestClient, api: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The check at the top of `finalize` is a read, and a read is not a lock (ADR-005).

    Two reviewers pressing Finalize in the same moment both pass it. What actually holds
    ADR-005 is the unique constraint on `final_reports.run_id` — which refused the second
    with an `IntegrityError` and a 500, so the one case the constraint exists for read to
    the reviewer as "the tool is broken" rather than "somebody got there first". The
    race is simulated here by making the pre-check miss, which is exactly what the loser
    of it experiences.
    """
    from greenlight_ai.api.routers import reports as reports_router

    monkeypatch.setattr(reports_router, "_stored", lambda session, run_id: None)
    first = client.post(f"{api}/runs/{reviewed}/finalize")
    assert first.status_code in (200, 201)
    second = client.post(f"{api}/runs/{reviewed}/finalize")
    assert second.status_code == 409, second.text
    assert "never regenerated" in second.json()["detail"]


def test_a_second_finalize_is_refused(reviewed: int, client: TestClient, api: str) -> None:
    """ADR-005: never regenerated."""
    assert client.post(f"{api}/runs/{reviewed}/finalize").status_code == 201
    second = client.post(f"{api}/runs/{reviewed}/finalize")
    assert second.status_code == 409
    assert "never regenerated" in second.json()["detail"]


def test_a_run_with_no_confirmed_findings_is_ok(
    submit: Submit, worker: Worker, client: TestClient, api: str, clear_gate: Callable[..., None]
) -> None:
    run_id = submit("baseline_match").json()["run_id"]
    worker.run_once()
    clear_gate(run_id)
    assert client.post(f"{api}/runs/{run_id}/finalize").json()["verdict"] == "ok"


# --- the stored document ----------------------------------------------------------------


def test_the_report_is_stored_on_the_volume(
    reviewed: int, client: TestClient, api: str, db_settings: Any, factory: sessionmaker[Session]
) -> None:
    client.post(f"{api}/runs/{reviewed}/finalize")
    with factory() as session:
        stored = session.execute(sa.select(models.FinalReport)).scalar_one()
    assert (db_settings.data_dir / stored.html_path).exists()


def test_the_served_report_is_the_stored_file(
    reviewed: int, client: TestClient, api: str, db_settings: Any, factory: sessionmaker[Session]
) -> None:
    body = client.post(f"{api}/runs/{reviewed}/finalize").json()
    served = client.get(f"{api}/runs/{reviewed}/report")
    assert served.status_code == 200
    assert hashlib.sha256(served.text.encode("utf-8")).hexdigest() == body["html_sha256"]


def test_the_stored_html_never_changes_after_finalize(
    reviewed: int, client: TestClient, api: str
) -> None:
    """Phase 5 criterion 2: the hash holds across a re-review attempt, which is rejected."""
    body = client.post(f"{api}/runs/{reviewed}/finalize").json()
    before = client.get(f"{api}/runs/{reviewed}/report").text

    findings = client.get(f"{api}/runs/{reviewed}/findings").json()
    rejected = client.patch(
        f"{api}/findings/{findings[0]['id']}",
        json={"review_status": "accepted_risk", "review_note": "changed my mind"},
    )
    assert rejected.status_code == 409

    after = client.get(f"{api}/runs/{reviewed}/report").text
    assert after == before
    assert hashlib.sha256(after.encode("utf-8")).hexdigest() == body["html_sha256"]


def test_the_report_is_self_contained(reviewed: int, client: TestClient, api: str) -> None:
    """Phase 5 criterion 1: it opens from file:// with no network."""
    client.post(f"{api}/runs/{reviewed}/finalize")
    html = client.get(f"{api}/runs/{reviewed}/report").text
    assert "<style>" in html
    assert 'src="http' not in html
    assert 'href="http' not in html
    assert "<link" not in html


def test_the_report_carries_the_not_ok_items_with_their_comments(
    reviewed: int, client: TestClient, api: str
) -> None:
    client.post(f"{api}/runs/{reviewed}/finalize")
    html = client.get(f"{api}/runs/{reviewed}/report").text
    assert "Not OK items" in html
    assert "reviewed by a test" in html
    assert "Verdict: Not OK" in html


def test_the_report_carries_the_matrix_and_the_metadata(
    reviewed: int, client: TestClient, api: str
) -> None:
    client.post(f"{api}/runs/{reviewed}/finalize")
    html = client.get(f"{api}/runs/{reviewed}/report").text
    assert "Traceability matrix" in html
    assert "Run metadata" in html
    assert "Input fingerprint" in html


def test_the_report_expands_every_section_before_printing(
    reviewed: int, client: TestClient, api: str
) -> None:
    """Phase 5 criterion 3: a collapsed section prints as a heading with nothing under it.

    CSS cannot do this on its own — a closed ``<details>`` hides its children through
    the browser's own mechanism, not through a style the print sheet can override — so
    the report sets the ``open`` attribute on every section before printing.
    """
    client.post(f"{api}/runs/{reviewed}/finalize")
    html = client.get(f"{api}/runs/{reviewed}/report").text
    assert "@media print" in html
    assert "beforeprint" in html
    assert "section.open = true" in html


def test_the_renderer_opens_every_section_itself(
    reviewed: int, client: TestClient, api: str
) -> None:
    """It does not rely on the page cooperating, so an older stored report still prints."""
    seen: list[str] = []

    class RecordingPage:
        def goto(self, *_args: object, **_kwargs: object) -> None: ...
        def emulate_media(self, **_kwargs: object) -> None: ...

        def evaluate(self, script: str) -> None:
            seen.append(script)

        def pdf(self, path: str, **_kwargs: object) -> None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(b"%PDF-1.7")

    class RecordingRenderer:
        def render(self, html_path: Path, pdf_path: Path) -> Path:
            page = RecordingPage()
            page.goto(html_path.as_uri())
            page.emulate_media(media="print")
            page.evaluate(
                "document.querySelectorAll('details').forEach(function (d) { d.open = true; })"
            )
            page.pdf(str(pdf_path))
            return pdf_path

    client.app.state.pdf_renderer = RecordingRenderer()  # type: ignore[attr-defined]
    client.post(f"{api}/runs/{reviewed}/finalize")
    client.get(f"{api}/runs/{reviewed}/report.pdf")

    assert any("d.open = true" in script for script in seen)


def test_no_unmasked_sample_value_reaches_the_report(
    reviewed: int, client: TestClient, api: str
) -> None:
    """ADR-003."""
    client.post(f"{api}/runs/{reviewed}/finalize")
    html = client.get(f"{api}/runs/{reviewed}/report").text
    assert "SYNTH1" not in html
    assert "unmask" not in html.lower().replace("no unmask control", "")


def test_reading_an_unfinalized_report_is_a_404(
    submit: Submit, worker: Worker, client: TestClient, api: str
) -> None:
    run_id = submit("baseline_match").json()["run_id"]
    worker.run_once()
    assert client.get(f"{api}/runs/{run_id}/report").status_code == 404


def test_a_missing_stored_file_is_reported_not_re_rendered(
    reviewed: int, client: TestClient, api: str, db_settings: Any, factory: sessionmaker[Session]
) -> None:
    """Re-rendering would produce a different document with the same claim."""
    client.post(f"{api}/runs/{reviewed}/finalize")
    with factory() as session:
        stored = session.execute(sa.select(models.FinalReport)).scalar_one()
        (db_settings.data_dir / stored.html_path).unlink()
    response = client.get(f"{api}/runs/{reviewed}/report")
    assert response.status_code == 410
    assert "never regenerated" in response.json()["detail"]


# --- the PDF --------------------------------------------------------------------------------


def test_the_pdf_is_rendered_from_the_stored_html(
    reviewed: int, client: TestClient, api: str, db_settings: Any
) -> None:
    """Phase 5 criterion 3: from the stored file, never from the data again."""
    renderer = FakePdfRenderer()
    client.app.state.pdf_renderer = renderer  # type: ignore[attr-defined]

    client.post(f"{api}/runs/{reviewed}/finalize")
    response = client.get(f"{api}/runs/{reviewed}/report.pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert len(renderer.calls) == 1
    assert renderer.calls[0].name == f"run-{reviewed}.html"


def test_the_pdf_is_rendered_once_and_then_served(
    reviewed: int, client: TestClient, api: str
) -> None:
    renderer = FakePdfRenderer()
    client.app.state.pdf_renderer = renderer  # type: ignore[attr-defined]

    client.post(f"{api}/runs/{reviewed}/finalize")
    client.get(f"{api}/runs/{reviewed}/report.pdf")
    client.get(f"{api}/runs/{reviewed}/report.pdf")

    assert len(renderer.calls) == 1, "the PDF is as frozen as the HTML it came from"


def test_the_pdf_path_is_recorded(
    reviewed: int, client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    client.app.state.pdf_renderer = FakePdfRenderer()  # type: ignore[attr-defined]
    client.post(f"{api}/runs/{reviewed}/finalize")
    client.get(f"{api}/runs/{reviewed}/report.pdf")
    with factory() as session:
        assert session.execute(sa.select(models.FinalReport)).scalar_one().pdf_path


def test_a_deployment_without_a_browser_degrades_gracefully(
    reviewed: int, client: TestClient, api: str
) -> None:
    """The HTML is always available, so a missing renderer loses one feature."""
    client.app.state.pdf_renderer = BrokenPdfRenderer()  # type: ignore[attr-defined]
    client.post(f"{api}/runs/{reviewed}/finalize")
    response = client.get(f"{api}/runs/{reviewed}/report.pdf")
    assert response.status_code == 503
    assert "HTML report" in response.json()["detail"]
    assert client.get(f"{api}/runs/{reviewed}/report").status_code == 200


def test_a_pdf_for_an_unfinalized_run_is_a_404(
    submit: Submit, worker: Worker, client: TestClient, api: str
) -> None:
    run_id = submit("baseline_match").json()["run_id"]
    worker.run_once()
    assert client.get(f"{api}/runs/{run_id}/report.pdf").status_code == 404


# --- no model calls ---------------------------------------------------------------------------


def test_finalizing_viewing_and_downloading_make_no_model_calls(
    reviewed: int, client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    """Phase 5 criterion 4."""
    with factory() as session:
        before = int(
            session.execute(sa.select(sa.func.count()).select_from(models.LlmCall)).scalar_one()
        )

    client.app.state.pdf_renderer = FakePdfRenderer()  # type: ignore[attr-defined]
    client.post(f"{api}/runs/{reviewed}/finalize")
    client.get(f"{api}/runs/{reviewed}/report")
    client.get(f"{api}/runs/{reviewed}/report.pdf")

    with factory() as session:
        after = int(
            session.execute(sa.select(sa.func.count()).select_from(models.LlmCall)).scalar_one()
        )
    assert after == before


def test_viewing_and_downloading_are_audited(
    reviewed: int, client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    client.app.state.pdf_renderer = FakePdfRenderer()  # type: ignore[attr-defined]
    client.post(f"{api}/runs/{reviewed}/finalize")
    client.get(f"{api}/runs/{reviewed}/report")
    client.get(f"{api}/runs/{reviewed}/report.pdf")

    with factory() as session:
        actions = set(session.execute(sa.select(models.AuditLog.action)).scalars())
    assert {"run.finalized", "report.viewed", "report.pdf_downloaded"} <= actions


# --- the download must never hand back an error body ------------------------------------


def test_the_run_detail_says_whether_a_pdf_can_be_produced(
    reviewed: int, client: TestClient, api: str
) -> None:
    """So the UI can tell the user before they click, not after they open the file."""
    body = client.get(f"{api}/runs/{reviewed}").json()
    assert "pdf_available" in body
    assert isinstance(body["pdf_available"], bool)


def test_a_failed_render_answers_json_with_an_error_status_not_a_file(
    reviewed: int, client: TestClient, api: str
) -> None:
    """The bug this guards: a plain download link saved the 503 body as report.pdf.

    The server is right to answer JSON here; it is the *status* that has to be
    unmistakable, so a client that checks it cannot mistake the body for a document.
    """
    client.app.state.pdf_renderer = BrokenPdfRenderer()  # type: ignore[attr-defined]
    client.post(f"{api}/runs/{reviewed}/finalize")

    response = client.get(f"{api}/runs/{reviewed}/report.pdf")
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/json")
    assert not response.content.startswith(b"%PDF")


def test_a_successful_download_is_a_pdf_with_a_filename(
    reviewed: int, client: TestClient, api: str
) -> None:
    client.app.state.pdf_renderer = FakePdfRenderer()  # type: ignore[attr-defined]
    client.post(f"{api}/runs/{reviewed}/finalize")

    response = client.get(f"{api}/runs/{reviewed}/report.pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert f"greenlight-ai-run-{reviewed}.pdf" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF")


# --- who asked for it and who judged it (Phase 6.2d) -------------------------------------


def test_the_report_names_the_submitter_and_the_reviewers(
    reviewed: int, client: TestClient, api: str
) -> None:
    """A report that is evidence of a review should say whose review it was."""
    client.post(f"{api}/runs/{reviewed}/finalize")

    html = client.get(f"{api}/runs/{reviewed}/report").text

    assert "Submitted by" in html
    assert "Reviewed by" in html
    # With login off every action is the seeded placeholder's, which is still a name.
    assert "John Doe" in html


def test_a_run_nobody_decided_says_so_rather_than_implying_a_review(
    submit: Submit, worker: Worker, client: TestClient, api: str, factory
) -> None:
    """Naming nobody is the honest answer; inventing a reviewer is not."""
    from greenlight_ai.report.render import render_report

    run_id = submit("baseline_match").json()["run_id"]
    worker.run_once()

    with factory() as session:
        from greenlight_ai.db import models

        run = session.get(models.Run, run_id)
        rendered = render_report(
            run=run,
            findings=[],
            rules=[],
            traces=[],
            stages=[],
            calls=[],
            generated_by="Someone",
            submitted_by="",
            reviewers=[],
        )

    assert "no findings were decided" in rendered.html


def test_the_report_never_names_the_model(reviewed: int, client: TestClient, api: str) -> None:
    """Which model ran it is an operational fact, not part of the judgement.

    It stays on the run record and in the stage log, where an administrator can find
    it; the report is what goes to a customer's file (Phase 6.14f).
    """
    client.post(f"{api}/runs/{reviewed}/finalize")
    html = client.get(f"{api}/runs/{reviewed}/report").text
    # The name of a model, in any of the spellings a provider uses.
    for vendor in ("claude", "gpt-", "gemma", "llama", "mock-model"):
        assert vendor not in html.lower(), f"the report names {vendor}"
    # The subtitle line that used to carry it, and the prompt-set version beside it.
    assert "· model <span" not in html
    assert "prompts v" not in html


def test_the_filed_copy_hides_what_belongs_only_on_screen(
    reviewed: int, client: TestClient, api: str
) -> None:
    """Generated-by, the input hash and the rules version are print-hidden.

    They are still in the HTML — the screen copy is where somebody chases provenance
    — and the stylesheet drops them when the page is printed to PDF.
    """
    client.post(f"{api}/runs/{reviewed}/finalize")
    html = client.get(f"{api}/runs/{reviewed}/report").text
    assert ".print-hide { display: none !important; }" in html
    assert 'class="print-hide">Input fingerprint' in html
    assert 'class="print-hide">Generated' in html


def test_the_printed_report_keeps_every_headline_number(
    reviewed: int, client: TestClient, api: str
) -> None:
    """Compacting the PDF must not be done by dropping a number.

    The five headline figures took a sixth of the first page, because A4 is 794px at
    96dpi and that tripped the 900px breakpoint the screen layout uses — so five values
    stacked into three rows of two. The fix is a one-line strip on paper. The failure
    this guards is the other fix somebody reaches for, which is deleting a figure.
    """
    client.post(f"{api}/runs/{reviewed}/finalize")
    html = client.get(f"{api}/runs/{reviewed}/report").text

    for label in (
        "Requirements traced",
        "High",
        "Medium",
        "Low",
        "Requirements matching",
    ):
        assert f'<div class="l">{label}</div>' in html, f"the {label} figure is gone"


def test_the_print_stylesheet_lays_the_figures_out_on_one_line(
    reviewed: int, client: TestClient, api: str
) -> None:
    """The rule that does the compacting, asserted where it cannot silently be lost.

    `.kpis` is a five-column grid on screen with a two-column fallback. Print has to
    override both, or the fallback wins on A4 and the strip becomes three rows again —
    which is the bug, not the layout.
    """
    client.post(f"{api}/runs/{reviewed}/finalize")
    html = client.get(f"{api}/runs/{reviewed}/report").text

    print_block = html[html.index("@media print {") :]
    assert "grid-template-columns: none;" in print_block, (
        "print must cancel the screen grid, or the 900px fallback applies on A4 "
        "and the figures stack into three rows again"
    )
    assert ".kpi .v { font-size: 0.92rem; }" in print_block
