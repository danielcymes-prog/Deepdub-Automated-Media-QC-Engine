"""PDF rendering from an existing report.html (Playwright or WeasyPrint).

Why: on Windows, WeasyPrint's native Pango/Cairo stack is painful to install
and keep deterministic; ADR-014 (amending ADR-007) selects Playwright's
headless Chromium there, behind the same replaceable-renderer idea as
ADR-012. Both backends here render the ALREADY-WRITTEN report.html file, so
the PDF is by construction a paged view of the canonical artifact and can
never diverge from it.

Failure is never fatal to a job: callers (the server worker) treat
PdfRenderError as the E10 degraded-artifacts condition - JSON+HTML complete,
PDF marked unavailable, verdict unaffected.

Inputs: html_path, pdf_path, renderer kind, timeout. Outputs: report.pdf.
Side effects: launches headless Chromium (playwright) or loads native
libraries (weasyprint).
"""

from __future__ import annotations

from pathlib import Path

from deepdub_qc.reports.pdf_renderer import PdfRenderError

__all__ = ["PdfRenderError", "render_pdf_from_html"]


def render_pdf_from_html(
    html_path: Path,
    pdf_path: Path,
    renderer: str = "playwright",
    timeout_seconds: int = 120,
) -> Path:
    """Render an existing HTML report file to PDF with the selected backend.

    Raises:
        PdfRenderError: backend unavailable, timed out, or rendering failed.
    """
    if not html_path.is_file():
        raise PdfRenderError(f"HTML report not found: {html_path}")
    if renderer == "playwright":
        _render_playwright(html_path, pdf_path, timeout_seconds)
    elif renderer == "weasyprint":
        _render_weasyprint(html_path, pdf_path)
    else:  # config validation prevents this; defensive for direct callers
        raise PdfRenderError(f"Unknown PDF renderer: {renderer!r}")
    return pdf_path


def _render_playwright(html_path: Path, pdf_path: Path, timeout_seconds: int) -> None:
    try:
        from playwright.sync_api import (  # noqa: PLC0415 - lazy: heavy optional dep
            Error as PlaywrightError,
        )
        from playwright.sync_api import (  # noqa: PLC0415
            sync_playwright,
        )
    except ImportError as exc:
        raise PdfRenderError(
            "PDF rendering requires Playwright. Install it with "
            "'pip install playwright && playwright install chromium'. "
            f"Underlying error: {exc}"
        ) from exc

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page()
                page.goto(html_path.resolve().as_uri(), timeout=timeout_seconds * 1000)
                page.pdf(
                    path=str(pdf_path),
                    format="A4",
                    print_background=True,
                    margin={"top": "12mm", "bottom": "12mm", "left": "10mm", "right": "10mm"},
                )
            finally:
                browser.close()
    except PlaywrightError as exc:
        raise PdfRenderError(f"Playwright PDF rendering failed: {exc}") from exc


def _render_weasyprint(html_path: Path, pdf_path: Path) -> None:
    try:
        from weasyprint import HTML  # noqa: PLC0415 - lazy: heavy native deps
    except (ImportError, OSError) as exc:
        raise PdfRenderError(
            "PDF rendering requires WeasyPrint and its native libraries "
            f"(Pango/Cairo). Underlying error: {exc}"
        ) from exc
    try:
        HTML(filename=str(html_path)).write_pdf(str(pdf_path))
    except Exception as exc:  # WeasyPrint raises assorted exception types
        raise PdfRenderError(f"WeasyPrint PDF rendering failed: {exc}") from exc
