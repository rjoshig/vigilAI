"""Finalize, and serve the frozen report and its PDF.

The report is rendered once from the reviewed findings and stored; a second finalize is
a 409, and re-reviewing a finalized run is refused, so the stored file always matches
the decisions it was generated from (ADR-005).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Final

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.orm import Session

from greenlight_ai.api.deps import CurrentUser, current_user, get_data_dir, get_session
from greenlight_ai.db import models, repository, drift
from greenlight_ai.report.pdf import PdfUnavailable, render_pdf, renderer_available
from greenlight_ai.report.render import render_report, write_report

__all__ = ["router"]

_LOG: Final = logging.getLogger(__name__)

router = APIRouter(prefix="/runs", tags=["report"])


def _run(session: Session, run_id: int) -> models.Run:
    """Load a run or raise 404.

    Args:
        session: An open session.
        run_id: The run.

    Returns:
        The run row.

    Raises:
        HTTPException: 404 when it does not exist.
    """
    run = session.get(models.Run, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"run {run_id} not found")
    return run


def _stored(session: Session, run_id: int) -> models.FinalReport | None:
    """Look up a run's frozen report.

    Args:
        session: An open session.
        run_id: The run.

    Returns:
        The stored report, or ``None``.
    """
    return session.execute(
        sa.select(models.FinalReport).where(models.FinalReport.run_id == run_id)
    ).scalar_one_or_none()


@router.post("/{run_id}/finalize", status_code=status.HTTP_201_CREATED)
def finalize(
    run_id: int,
    session: Session = Depends(get_session),
    data_dir: Path = Depends(get_data_dir),
    user: CurrentUser = Depends(current_user),
) -> dict[str, object]:
    """Render and freeze the final report.

    Args:
        run_id: The run.
        session: The request's session.
        data_dir: The shared volume.
        user: The caller.

    Returns:
        The verdict and the stored file's hash.

    Raises:
        HTTPException: 409 when the run is already finalized or the gate is not
            satisfied, 400 when the run never reached review.
    """
    run = _run(session, run_id)

    if _stored(session, run_id) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"run {run_id} is already finalized; the report is frozen and is never regenerated",
        )
    if run.status not in ("needs_review", "finalized"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"run {run_id} is {run.status}; only a reviewed run can be finalized",
        )

    undecided = int(
        session.execute(
            sa.select(sa.func.count())
            .select_from(models.Finding)
            .where(
                models.Finding.run_id == run_id,
                models.Finding.severity == "high",
                models.Finding.review_status == "undecided",
                models.Finding.shadow.is_(False),
            )
        ).scalar_one()
    )
    if undecided:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{undecided} high-severity finding(s) still need a decision before this run "
            "can be finalized",
        )

    findings = list(
        session.execute(
            sa.select(models.Finding)
            # Never on the frozen record: a shadow finding is shown to nobody (ADR-021).
            .where(models.Finding.run_id == run_id, models.Finding.shadow.is_(False)).order_by(
                sa.case(
                    {"high": 0, "medium": 1, "low": 2, "review": 3},
                    value=models.Finding.severity,
                    else_=9,
                ),
                models.Finding.id,
            )
        ).scalars()
    )
    rendered = render_report(
        run=run,
        findings=findings,
        rules=repository.load_rules(session, run_id),
        traces=list(
            session.execute(sa.select(models.Trace).where(models.Trace.run_id == run_id)).scalars()
        ),
        stages=list(
            session.execute(
                sa.select(models.RunStage).where(models.RunStage.run_id == run_id)
            ).scalars()
        ),
        calls=list(
            session.execute(
                sa.select(models.LlmCall).where(models.LlmCall.run_id == run_id)
            ).scalars()
        ),
        generated_by=user.name,
        drift=drift.compute_drift(session, run),
    )

    storage_key = write_report(rendered.html, data_dir, run_id)
    session.add(
        models.FinalReport(
            run_id=run_id,
            html_path=storage_key,
            html_sha256=rendered.sha256,
            verdict=rendered.verdict,
            generated_by=user.name,
            generated_by_user_id=user.id,
        )
    )
    run.status = "finalized"
    repository.audit(
        session,
        "run.finalized",
        run_id,
        rendered.verdict,
        user_id=user.id,
        actor=user.name,
    )
    _LOG.info("run %d finalized: %s", run_id, rendered.verdict)

    return {
        "run_id": run_id,
        "verdict": rendered.verdict,
        "html_sha256": rendered.sha256,
        "pdf_available": renderer_available(),
    }


@router.get("/{run_id}/report", response_class=HTMLResponse)
def get_report(
    run_id: int,
    session: Session = Depends(get_session),
    data_dir: Path = Depends(get_data_dir),
    _user: CurrentUser = Depends(current_user),
) -> HTMLResponse:
    """Serve the stored report.

    Served from the file rather than re-rendered, which is the whole point of freezing
    it (ADR-005).

    Args:
        run_id: The run.
        session: The request's session.
        data_dir: The shared volume.
        _user: The caller.

    Returns:
        The stored HTML.

    Raises:
        HTTPException: 404 when the run has no report, 410 when the stored file is
            gone, which means the volume lost it and re-rendering would be a different
            document.
    """
    _run(session, run_id)
    stored = _stored(session, run_id)
    if stored is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"run {run_id} has not been finalized yet")

    path = data_dir / stored.html_path
    if not path.exists():
        raise HTTPException(
            status.HTTP_410_GONE,
            f"the frozen report for run {run_id} is missing from storage and is never regenerated",
        )

    repository.audit(session, "report.viewed", run_id)
    return HTMLResponse(content=path.read_text(encoding="utf-8"))


@router.get("/{run_id}/report.pdf")
def get_report_pdf(
    run_id: int,
    request: Request,
    session: Session = Depends(get_session),
    data_dir: Path = Depends(get_data_dir),
    _user: CurrentUser = Depends(current_user),
) -> Response:
    """Serve the PDF, rendering it from the stored HTML on first request.

    Args:
        run_id: The run.
        request: The incoming request, which may carry an injected renderer.
        session: The request's session.
        data_dir: The shared volume.
        _user: The caller.

    Returns:
        The PDF.

    Raises:
        HTTPException: 404 when the run has no report, 503 when this deployment cannot
            render PDFs. The HTML is always available, so a missing renderer degrades
            one feature rather than the report.
    """
    _run(session, run_id)
    stored = _stored(session, run_id)
    if stored is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"run {run_id} has not been finalized yet")

    html_path = data_dir / stored.html_path
    pdf_path = data_dir / "reports" / f"run-{run_id}.pdf"

    try:
        render_pdf(html_path, pdf_path, getattr(request.app.state, "pdf_renderer", None))
    except PdfUnavailable as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"{exc}. Open the HTML report instead.",
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_410_GONE, str(exc)) from exc

    if not stored.pdf_path:
        stored.pdf_path = str(pdf_path.relative_to(data_dir))
    repository.audit(session, "report.pdf_downloaded", run_id)

    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=f"greenlight-ai-run-{run_id}.pdf",
    )
