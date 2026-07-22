"""Detector engine: tools that measure media and emit normalized Measurements.

Detectors never evaluate thresholds, never see presets or clients, and always
preserve raw tool output (ADR-001, ARCHITECTURE section 2).
"""

from deepdub_qc.detectors.base import Detector, DetectorRunError, QCContext
from deepdub_qc.detectors.registry import all_detectors, register

__all__ = ["Detector", "DetectorRunError", "QCContext", "all_detectors", "register"]
