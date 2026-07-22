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
