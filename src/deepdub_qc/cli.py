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
from deepdub_qc.exceptions import DeepdubQCError, PresetError, PresetValidationError
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


@app.command()
def analyze(
    input: Annotated[
        Path, typer.Option("--input", "-i", help="Path to the media file to analyze.")
    ],
    preset: Annotated[Path, typer.Option("--preset", "-p", help="Path to the client preset YAML.")],
    output: Annotated[
        Path, typer.Option("--output", "-o", help="Job output directory for reports.")
    ],
    pdf: Annotated[bool, typer.Option(help="Render report.pdf (requires WeasyPrint).")] = True,
) -> None:
    """Analyze one media file against one preset and generate QC reports.

    Exit codes: 0 PASS, 1 WARNING, 2 FAIL, 3 ERROR, 4 invalid preset,
    5 invalid input, 6 internal error (see README).
    """
    from deepdub_qc.orchestration.pipeline import (  # noqa: PLC0415
        AnalysisOptions,
        InputFileError,
        run_analysis,
    )

    status_exit = {
        "PASS": ExitCode.QC_PASS,
        "WARNING": ExitCode.QC_WARNING,
        "FAIL": ExitCode.QC_FAIL,
        "ERROR": ExitCode.QC_EXECUTION_ERROR,
    }

    def show_progress(message: str) -> None:
        err_console.print(f"[dim]{message}[/dim]")

    try:
        result = run_analysis(
            input, preset, output, AnalysisOptions(render_pdf=pdf, on_progress=show_progress)
        )
    except InputFileError as exc:
        err_console.print(f"[red]Invalid input:[/red] {exc}")
        raise typer.Exit(code=ExitCode.INVALID_INPUT) from exc
    except PresetError as exc:
        err_console.print(f"[red]Invalid preset:[/red] {exc}")
        raise typer.Exit(code=ExitCode.INVALID_CONFIGURATION) from exc
    except DeepdubQCError as exc:
        err_console.print(f"[red]QC execution error:[/red] {exc}")
        raise typer.Exit(code=ExitCode.QC_EXECUTION_ERROR) from exc

    summary = result.summary
    verdict_style = {"PASS": "green", "WARNING": "yellow"}.get(summary.overall_status.value, "red")
    console.print(
        f"[{verdict_style} bold]{summary.overall_status.value}[/{verdict_style} bold] "
        f"— {summary.passed} passed, {summary.warnings} warnings, {summary.failed} failed "
        f"({summary.blocking_failures} blocking), {summary.errors} errors, "
        f"{summary.skipped} skipped"
    )
    console.print(f"Reports written to {output}")
    raise typer.Exit(code=status_exit[summary.overall_status.value])


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
    path: Annotated[
        Path, typer.Argument(help="Path to a preset YAML file, or a directory of presets.")
    ],
) -> None:
    """Validate preset file(s) against the preset schema and invariants."""
    from deepdub_qc.presets.governance import discover_presets  # noqa: PLC0415

    targets = discover_presets(path) if path.is_dir() else [path]
    if not targets:
        err_console.print(f"[red]No preset files found in[/red] {path}")
        raise typer.Exit(code=ExitCode.INVALID_CONFIGURATION)

    failures = 0
    table = Table(title=f"Preset validation: {path}")
    table.add_column("Preset")
    table.add_column("ID / version")
    table.add_column("Client")
    table.add_column("Status")
    table.add_column("Rules")
    table.add_column("Result")
    for target in targets:
        try:
            preset = load_preset(target)
            preset_sha256(target)
        except PresetValidationError as exc:
            failures += 1
            table.add_row(target.name, "—", "—", "—", "—", "[red]INVALID[/red]")
            for error in exc.errors:
                err_console.print(f"  {target.name}: {error}")
            continue
        except PresetError as exc:
            failures += 1
            table.add_row(target.name, "—", "—", "—", "—", "[red]INVALID[/red]")
            err_console.print(f"  {target.name}: {exc}")
            continue
        table.add_row(
            target.name,
            f"{preset.preset.id} v{preset.preset.version}",
            preset.preset.client,
            preset.preset.status.value,
            str(len(preset.rules)),
            "[green]OK[/green]",
        )
    console.print(table)
    if failures:
        err_console.print(f"[red]{failures} invalid preset(s)[/red]")
        raise typer.Exit(code=ExitCode.INVALID_CONFIGURATION)


@presets_app.command("verify")
def presets_verify(
    directory: Annotated[
        Path, typer.Argument(help="Preset root directory (contains approved.lock.json).")
    ] = Path("presets"),
) -> None:
    """Verify that approved presets are unmodified (immutability check, ADR-013)."""
    from deepdub_qc.presets.governance import verify_approved  # noqa: PLC0415

    problems = verify_approved(directory)
    if problems:
        for problem in problems:
            err_console.print(f"[red]VIOLATION[/red] {problem}")
        raise typer.Exit(code=ExitCode.INVALID_CONFIGURATION)
    console.print("[green]Approved presets verified: no violations[/green]")


@presets_app.command("lock")
def presets_lock(
    directory: Annotated[
        Path, typer.Argument(help="Preset root directory to (re)generate the lock for.")
    ] = Path("presets"),
) -> None:
    """Record the current approved presets in approved.lock.json.

    Run this only in a reviewed commit after human approval (handoff section 30).
    """
    from deepdub_qc.presets.governance import build_lock, write_lock  # noqa: PLC0415

    target = write_lock(directory)
    entries = build_lock(directory)
    console.print(f"Wrote {target} ({len(entries)} approved preset(s))")


if __name__ == "__main__":
    app()
