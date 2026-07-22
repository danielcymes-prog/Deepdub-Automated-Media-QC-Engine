"""Report engine: render the canonical QCResult to JSON, HTML, and PDF (ADR-002).

Renderers are pure functions of the QCResult model. They must never compute,
alter, or invent findings, and must never include information absent from the
canonical JSON.
"""

from deepdub_qc.reports.html_renderer import render_html
from deepdub_qc.reports.json_renderer import render_json, write_json_report

__all__ = ["render_html", "render_json", "write_json_report"]
