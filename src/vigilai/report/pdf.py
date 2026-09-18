"""PDF rendering: the stored HTML printed by headless Chromium.

The PDF is rendered **from the stored HTML**, never from the data again
(``docs/design.md`` "Review and final report"). That is what makes the two artifacts
agree: if the PDF were re-rendered from the database it could drift from the frozen
page it claims to be.

The renderer sits behind a Protocol so the API and the worker depend on the capability
rather than on Playwright, and so a test can substitute a fake instead of driving a
browser.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Final, Protocol

__all__ = ["PdfRenderer", "PlaywrightRenderer", "PdfUnavailable", "render_pdf"]

_LOG: Final = logging.getLogger(__name__)

#: Print settings. Backgrounds are on because severity is carried by colour, and a
#: report printed without them loses the distinction between high and low.
PAGE_FORMAT: Final[str] = "A4"
PRINT_BACKGROUND: Final[bool] = True
MARGIN: Final[str] = "12mm"

#: How long to wait for Chromium before giving up.
TIMEOUT_MS: Final[int] = 60_000


class PdfUnavailable(RuntimeError):
    """PDF rendering is not available in this deployment.

    Raised when Playwright or its browser is not installed. The HTML report is always
    available, so this degrades one feature rather than the run.
    """


class PdfRenderer(Protocol):
    """Turns a stored HTML file into a PDF."""

    def render(self, html_path: Path, pdf_path: Path) -> Path:
        """Render one file.

        Args:
            html_path: The stored report.
            pdf_path: Where to write the PDF.

        Returns:
            The written path.

        Raises:
            PdfUnavailable: When the renderer cannot run here.
        """
        ...


class PlaywrightRenderer:
    """Renders with headless Chromium via Playwright.

    Lives in the worker image, which is where the design doc puts it: the api must stay
    responsive, and a browser launch is neither quick nor cheap.
    """

    def render(self, html_path: Path, pdf_path: Path) -> Path:
        """Print the stored HTML to PDF with every finding expanded.

        Args:
            html_path: The stored report.
            pdf_path: Where to write the PDF.

        Returns:
            The written path.

        Raises:
            PdfUnavailable: When Playwright or its browser is not installed.
        """
        try:
            from playwright.sync_api import sync_playwright  # noqa: PLC0415
        except ImportError as exc:
            raise PdfUnavailable(
                "playwright is not installed; the HTML report is still available"
            ) from exc

        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    page = browser.new_page()
                    page.goto(html_path.resolve().as_uri(), timeout=TIMEOUT_MS)
                    # The print stylesheet expands every <details>; emulating print
                    # media is what makes those rules apply.
                    page.emulate_media(media="print")
                    page.pdf(
                        path=str(pdf_path),
                        format=PAGE_FORMAT,
                        print_background=PRINT_BACKGROUND,
                        margin={
                            "top": MARGIN,
                            "bottom": MARGIN,
                            "left": MARGIN,
                            "right": MARGIN,
                        },
                    )
                finally:
                    browser.close()
        except Exception as exc:  # noqa: BLE001 - playwright raises its own hierarchy
            if isinstance(exc, PdfUnavailable):
                raise
            raise PdfUnavailable(f"headless Chromium could not render the PDF: {exc}") from exc

        _LOG.info("rendered PDF %s (%d bytes)", pdf_path.name, pdf_path.stat().st_size)
        return pdf_path


def renderer_available() -> bool:
    """Whether a PDF can be produced in this deployment.

    Returns:
        ``True`` when Playwright is importable. The UI uses this to hide a download
        button that would only ever fail.
    """
    try:
        import playwright  # noqa: F401,PLC0415

        return True
    except ImportError:
        return False


def render_pdf(html_path: Path, pdf_path: Path, renderer: PdfRenderer | None = None) -> Path:
    """Render a stored report to PDF.

    Args:
        html_path: The stored report.
        pdf_path: Where to write the PDF.
        renderer: The renderer to use; Playwright by default. Injectable so a test does
            not launch a browser.

    Returns:
        The written path.

    Raises:
        PdfUnavailable: When no renderer can run here.
        FileNotFoundError: When the stored HTML is missing, which means the volume lost
            a frozen report and is worth failing loudly over.
    """
    if not html_path.exists():
        raise FileNotFoundError(f"the stored report {html_path.name} is missing")
    if pdf_path.exists() and pdf_path.stat().st_size > 0:
        # Already rendered: the PDF is as frozen as the HTML it came from.
        return pdf_path
    return (renderer or PlaywrightRenderer()).render(html_path, pdf_path)


def has_chromium() -> bool:
    """Whether a Chromium binary is visible on PATH, for diagnostics only.

    Returns:
        ``True`` when one is found. Playwright ships its own browser, so this is a hint
        for an operator debugging a deployment rather than a precondition.
    """
    return any(shutil.which(name) for name in ("chromium", "chromium-browser", "google-chrome"))
