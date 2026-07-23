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
import threading
import time
from dataclasses import dataclass

from deepdub_qc.exceptions import DeepdubQCError

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 300.0

#: Active child process per thread, so a controller (the server worker's
#: cancel/timeout monitor) can terminate a long ffmpeg run mid-flight from
#: another thread. ffmpeg/ffprobe spawn no children of their own, so killing
#: the direct child terminates the whole tool.
_ACTIVE: dict[int, subprocess.Popen[str]] = {}
_ACTIVE_LOCK = threading.Lock()


def terminate_active_tool(thread_ident: int) -> bool:
    """Kill the tool currently running on the given thread, if any.

    Returns True when a process was signalled. The victim thread's run_tool
    then sees a non-zero exit and raises ToolExecutionError; callers that
    initiated the kill (cancel/timeout) classify that error themselves.
    """
    with _ACTIVE_LOCK:
        process = _ACTIVE.get(thread_ident)
    if process is None:
        return False
    try:
        process.kill()
    except OSError:  # already exited
        return False
    logger.info("terminated active tool", extra={"thread": thread_ident, "pid": process.pid})
    return True


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
    ident = threading.get_ident()
    try:
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            shell=False,
        )
    except FileNotFoundError as exc:
        raise ToolNotFoundError(f"executable not found: {args[0]}") from exc

    with _ACTIVE_LOCK:
        _ACTIVE[ident] = process
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.communicate()  # reap; avoid zombies and dangling pipes
        logger.error(
            "tool timed out",
            extra={"tool": args[0], "timeout_seconds": timeout},
        )
        raise ToolTimeoutError(f"{args[0]} exceeded timeout of {timeout:.0f}s") from exc
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE.pop(ident, None)

    duration = time.monotonic() - started
    logger.debug(
        "tool finished",
        extra={"tool": args[0], "exit_code": process.returncode, "duration": duration},
    )
    if check and process.returncode != 0:
        raise ToolExecutionError(
            f"{args[0]} failed with exit code {process.returncode}: {stderr.strip()[:500]}",
            exit_code=process.returncode,
            stderr=stderr,
        )
    return ToolResult(
        args=tuple(args),
        exit_code=process.returncode,
        stdout=stdout,
        stderr=stderr,
        duration_seconds=duration,
    )
