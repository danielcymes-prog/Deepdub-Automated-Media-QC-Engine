"""Safe subprocess execution for external media tools (handoff section 20).

Why this exists: every detector shells out to FFmpeg-family tools. All of
those calls must share one hardened path: argument arrays only (never
shell=True), explicit timeouts, captured stdout/stderr, typed errors, and
structured logging. Input paths are untrusted.

Inputs: an argument array. Outputs: a ToolResult. Side effects: process
execution and log records; never raises bare OSError/CalledProcessError.
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass

from deepdub_qc.exceptions import DeepdubQCError

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 300.0


class ToolError(DeepdubQCError):
    """Base class for external-tool execution errors."""


class ToolNotFoundError(ToolError):
    """The executable does not exist on PATH."""


class ToolTimeoutError(ToolError):
    """The tool exceeded its execution timeout."""


class ToolExecutionError(ToolError):
    """The tool ran but returned a non-zero exit code.

    Attributes:
        exit_code: process exit code.
        stderr: captured stderr (truncated for the message, full here).
    """

    def __init__(self, message: str, exit_code: int, stderr: str) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.stderr = stderr


@dataclass(frozen=True)
class ToolResult:
    """Outcome of a successful tool invocation."""

    args: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float


def run_tool(
    args: list[str],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    check: bool = True,
) -> ToolResult:
    """Run an external tool safely and return its captured output.

    Args:
        args: full argument array; args[0] is the executable name.
        timeout: hard wall-clock limit in seconds; the process is killed on expiry.
        check: raise ToolExecutionError on non-zero exit when True.

    Raises:
        ToolNotFoundError, ToolTimeoutError, ToolExecutionError.
    """
    if not args:
        msg = "run_tool requires a non-empty argument array"
        raise ValueError(msg)
    started = time.monotonic()
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ToolNotFoundError(f"executable not found: {args[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        logger.error(
            "tool timed out",
            extra={"tool": args[0], "timeout_seconds": timeout},
        )
        raise ToolTimeoutError(f"{args[0]} exceeded timeout of {timeout:.0f}s") from exc

    duration = time.monotonic() - started
    logger.debug(
        "tool finished",
        extra={"tool": args[0], "exit_code": completed.returncode, "duration": duration},
    )
    if check and completed.returncode != 0:
        raise ToolExecutionError(
            f"{args[0]} failed with exit code {completed.returncode}: "
            f"{completed.stderr.strip()[:500]}",
            exit_code=completed.returncode,
            stderr=completed.stderr,
        )
    return ToolResult(
        args=tuple(args),
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_seconds=duration,
    )
