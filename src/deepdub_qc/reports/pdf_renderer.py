"""PDF report rendering via WeasyPrint (ADR-007).

The PDF is a paged rendering of the same HTML produced by html_renderer -
one canonical model, one HTML layout, two output media (ADR-002).

WeasyPrint is imported lazily: it links against native Pango/Cairo libraries
that may be missing on developer machines. The Docker image is the canonical
environment; local failures raise a typed, actionable error instead of an
ImportError traceback.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from deepdub_qc.exceptions import DeepdubQCError
from deepdub_qc.models.report import QCResult
from deepdub_qc.reports.html_renderer import render_html

REPORT_PDF_FILENAME = "report.pdf"


class PdfRenderError(DeepdubQCError):
    """PDF rendering failed or the rendering backend is unavailable."""


def render_pdf(result: QCResult, generated_at: datetime | None = None) -> bytes:
    """Render the canonical QCResult to PDF bytes.

    Raises:
        PdfRenderError: WeasyPrint (or its native libraries) is unavailable,
            or rendering failed.
    """
    try:
        from weasyprint import HTML  # noqa: PLC0415  (lazy: heavy native deps)
    except (ImportError, OSError) as exc:
        raise PdfRenderError(
            "PDF rendering requires WeasyPrint and its native libraries "
            "(Pango/Cairo). Install them or run inside the deepdub-qc Docker "
            f"image. Underlying error: {exc}"
        ) from exc

    html = render_html(result, generated_at)
    try:
        pdf: bytes | None = HTML(string=html).write_pdf()
    except Exception as exc:  # WeasyPrint raises assorted exception types
        raise PdfRenderError(f"PDF rendering failed: {exc}") from exc
    if pdf is None:  # pragma: no cover - defensive; write_pdf() returns bytes
        raise PdfRenderError("PDF rendering produced no output")
    return pdf


def write_pdf_report(
    result: QCResult, output_dir: Path, generated_at: datetime | None = None
) -> Path:
    """Write report.pdf into the job output directory and return its path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / REPORT_PDF_FILENAME
    target.write_bytes(render_pdf(result, generated_at))
    return target
