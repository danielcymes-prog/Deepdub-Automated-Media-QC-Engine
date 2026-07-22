"""deepdub-qc command-line interface.

The CLI is a thin shell: it parses arguments, calls the library, renders
console output, and maps typed errors to documented exit codes (section 18
of the handoff). It contains no QC logic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from deepdub_qc import __version__
from deepdub_qc.exceptions import PresetError, PresetValidationError
from deepdub_qc.exit_codes import ExitCode
from deepdub_qc.logging import configure_logging
from deepdub_qc.presets.loader import load_preset, preset_sha256

app = typer.Typer(
    name="deepdub-qc",
    help="Deepdub automated media QC engine.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)
presets_app = typer.Typer(help="Inspect and validate QC presets.", no_args_is_help=True)
app.add_typer(presets_app, name="presets")

console = Console()
err_console = Console(stderr=True)


@app.callback()
def main(
    log_level: Annotated[
        str, typer.Option(help="Log level: DEBUG, INFO, WARNING, ERROR.")
    ] = "WARNING",
    log_json: Annotated[bool, typer.Option(help="Emit structured JSON logs.")] = True,
) -> None:
    configure_logging(log_level, json_output=log_json)


@app.command()
def version() -> None:
    """Print the tool version."""
    console.print(f"deepdub-qc {__version__}")


@app.command("render-mock")
def render_mock(
    output: Annotated[
        Path, typer.Option("--output", "-o", help="Output directory for the rendered reports.")
    ],
    pdf: Annotated[
        bool, typer.Option(help="Also render report.pdf (requires WeasyPrint native libs).")
    ] = True,
) -> None:
    """Render the built-in mock QC result to JSON, HTML, and PDF.

    Report-first prototype (M2): lets stakeholders review the report layout
    before detectors exist. The mock content is illustrative, not measured.
    """
    from deepdub_qc.reports.html_renderer import write_html_report  # noqa: PLC0415
    from deepdub_qc.reports.json_renderer import write_json_report  # noqa: PLC0415
    from deepdub_qc.reports.mock_result import build_mock_result  # noqa: PLC0415

    result = build_mock_result()
    written = [write_json_report(result, output), write_html_report(result, output)]

    if pdf:
        from deepdub_qc.reports.pdf_renderer import (  # noqa: PLC0415
            PdfRenderError,
            write_pdf_report,
        )

        try:
            written.append(write_pdf_report(result, output))
        except PdfRenderError as exc:
            err_console.print(f"[red]PDF rendering failed:[/red] {exc}")
            raise typer.Exit(code=ExitCode.INTERNAL_ERROR) from exc

    console.print(f"Mock report rendered (overall status: {result.summary.overall_status.value})")
    for path in written:
        console.print(f"  {path}")


@presets_app.command("validate")
def presets_validate(
    path: Annotated[Path, typer.Argument(help="Path to a preset YAML file.")],
) -> None:
    """Validate a preset file against the preset schema and its invariants."""
    try:
        preset = load_preset(path)
        digest = preset_sha256(path)
    except PresetValidationError as exc:
        err_console.print(f"[red]INVALID[/red] {path}")
        for error in exc.errors:
            err_console.print(f"  - {error}")
        raise typer.Exit(code=ExitCode.INVALID_CONFIGURATION) from exc
    except PresetError as exc:
        err_console.print(f"[red]INVALID[/red] {path}: {exc}")
        raise typer.Exit(code=ExitCode.INVALID_CONFIGURATION) from exc

    table = Table(title=f"Preset OK: {path.name}", show_header=False)
    table.add_row("Preset ID", preset.preset.id)
    table.add_row("Version", preset.preset.version)
    table.add_row("Client", preset.preset.client)
    table.add_row("Content type", preset.preset.content_type)
    table.add_row("Status", preset.preset.status.value)
    table.add_row("Rules", str(len(preset.rules)))
    table.add_row("Enabled rules", str(sum(1 for rule in preset.rules if rule.enabled)))
    table.add_row("SHA-256", digest)
    console.print(table)


if __name__ == "__main__":
    app()
