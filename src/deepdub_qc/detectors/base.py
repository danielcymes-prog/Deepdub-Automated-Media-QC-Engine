"""Detector interface (handoff section 14).

A detector measures facts about a media asset. It must:
- produce normalized Measurement models only (no pass/fail),
- preserve raw tool output under the job's raw/ directory,
- declare its identity, version, and the parameters it produces,
- raise DetectorRunError (or subclasses) on failure so the pipeline can emit
  ERROR findings for the rules that depend on it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from deepdub_qc.exceptions import DeepdubQCError

if TYPE_CHECKING:
    from deepdub_qc.models.measurement import Measurement


class DetectorRunError(DeepdubQCError):
    """A detector failed to produce its measurements."""


@dataclass(frozen=True)
class QCContext:
    """Everything a detector may know about the job it runs in.

    Deliberately minimal: no preset, no client, no thresholds (ADR-001).
    """

    job_id: UUID
    input_path: Path
    raw_dir: Path


class Detector(ABC):
    """Base class for all detectors."""

    detector_id: str
    detector_version: str
    #: Parameter IDs this detector produces. Used by the pipeline to emit
    #: ERROR findings for dependent rules when the detector fails.
    parameters: tuple[str, ...]

    @abstractmethod
    def is_applicable(self, context: QCContext) -> bool:
        """Whether this detector can run for the given job."""

    @abstractmethod
    def run(self, context: QCContext) -> list[Measurement]:
        """Measure the asset and return normalized measurements.

        Must preserve raw tool output under context.raw_dir.
        Raises DetectorRunError on failure.
        """
