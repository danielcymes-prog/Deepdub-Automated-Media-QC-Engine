"""Parser for Telestream Vidchecker XML report exports.

Why: Vidchecker XML (namespace ``http://www.vidcheck.com/services``) is the
machine-readable exchange format for parity validation (docs/VALIDATION.md).
This module extracts only the fields the comparison engine needs; the raw
XML remains the authoritative artifact.

Inputs: an XML report file exported by Vidchecker 8.x.
Outputs: a ``VidcheckerTask`` per report (first task).
Side effects: none (pure parse).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from pydantic import BaseModel

from deepdub_qc.exceptions import DeepdubQCError

NAMESPACE = "http://www.vidcheck.com/services"
_NS = {"v": NAMESPACE}

#: AlertTypeId values the comparison engine understands.
ALERT_LOUDNESS_INTEGRATED = 1000
ALERT_LOUDNESS_INFO = 1001
ALERT_MIN_LEVEL = 1120
ALERT_CLIPPING = 1140

#: Detail phrasings that mean "Vidchecker did not measure anything".
_NOT_RUN_PATTERNS = (
    "will not be run",
    "can't run",
    "cannot run",
    "can't test",
    "cannot test",
)

_LOUDNESS_IN_DETAIL = re.compile(r"(-?\d+(?:\.\d+)?)\s*LKFS/LUFS")


class VidcheckerParseError(DeepdubQCError):
    """The XML file is not a readable Vidchecker report."""


class VidcheckerAlert(BaseModel):
    """One TaskAlert, normalized."""

    alert_id: int | None = None
    type_name: str = ""
    alert_type_id: int | None = None
    level: str = ""
    stream_index: int | None = None
    channels: str = ""
    detail: str = ""
    begin_seconds: float | None = None
    end_seconds: float | None = None
    loudness_db: float | None = None
    not_run: bool = False


class VidcheckerTask(BaseModel):
    """One analyzed file in a Vidchecker report."""

    filename: str
    file_size: int | None = None
    duration_seconds: float | None = None
    template: str = ""
    verdict: str = ""
    product_version: str = ""
    alerts: list[VidcheckerAlert] = []


def _text(element: ET.Element | None, path: str) -> str | None:
    if element is None:
        return None
    found = element.find(path, _NS)
    if found is None or found.text is None:
        return None
    return found.text.strip() or None


def _seconds(element: ET.Element | None, path: str) -> float | None:
    raw = _text(element, f"{path}/v:TotalSeconds")
    try:
        return float(raw) if raw is not None else None
    except ValueError:
        return None


def _parse_alert(node: ET.Element) -> VidcheckerAlert:
    detail = _text(node, "v:Detail") or ""
    detail_lower = detail.lower()
    not_run = any(pattern in detail_lower for pattern in _NOT_RUN_PATTERNS)

    loudness_raw = _text(node, "v:DetailParams/v:LoudnessDb")
    loudness = float(loudness_raw) if loudness_raw is not None else None
    if loudness is None and not not_run:
        match = _LOUDNESS_IN_DETAIL.search(detail)
        if match and "integrated loudness" in detail_lower:
            loudness = float(match.group(1))

    alert_id_raw = _text(node, "v:Id")
    type_id_raw = _text(node, "v:AlertTypeId")
    stream_raw = _text(node, "v:StreamIndex")
    return VidcheckerAlert(
        alert_id=int(alert_id_raw) if alert_id_raw else None,
        type_name=_text(node, "v:Type") or "",
        alert_type_id=int(type_id_raw) if type_id_raw else None,
        level=_text(node, "v:Level") or "",
        stream_index=int(stream_raw) if stream_raw else None,
        channels=_text(node, "v:ChannelMaskStr") or "",
        detail=detail,
        begin_seconds=_seconds(node, "v:BeginTime"),
        end_seconds=_seconds(node, "v:EndTime"),
        loudness_db=loudness,
        not_run=not_run,
    )


def parse_vidchecker_report(path: Path) -> VidcheckerTask:
    """Parse a Vidchecker XML report; returns the first (usually only) task."""
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise VidcheckerParseError(f"Cannot parse Vidchecker XML {path}: {exc}") from exc

    if root.tag != f"{{{NAMESPACE}}}Report":
        raise VidcheckerParseError(f"{path} is not a Vidchecker report (root element {root.tag!r})")

    task = root.find("v:ArrayOfTask/v:Task", _NS)
    if task is None:
        raise VidcheckerParseError(f"{path} contains no Task element")

    size_raw = _text(task, "v:FileSize")
    return VidcheckerTask(
        filename=_text(task, "v:Filename") or "",
        file_size=int(size_raw) if size_raw else None,
        duration_seconds=_seconds(task, "v:StreamInfo/v:Duration"),
        template=_text(task, "v:Template") or "",
        verdict=_text(task, "v:CheckResult") or "",
        product_version=_text(root, "v:ProductVersion") or "",
        alerts=[_parse_alert(node) for node in task.findall("v:TaskAlerts/v:TaskAlert", _NS)],
    )
