"""Detector registry: the pipeline discovers detectors here, never imports them directly."""

from __future__ import annotations

from deepdub_qc.detectors.base import Detector

_REGISTRY: dict[str, type[Detector]] = {}


def register(cls: type[Detector]) -> type[Detector]:
    """Class decorator: add a detector to the registry (id must be unique)."""
    if cls.detector_id in _REGISTRY:
        msg = f"duplicate detector_id: {cls.detector_id}"
        raise ValueError(msg)
    _REGISTRY[cls.detector_id] = cls
    return cls


def all_detectors() -> list[Detector]:
    """Instantiate every registered detector, in deterministic id order."""
    # Import detector modules for their registration side effects.
    from deepdub_qc.detectors.audio import clipping, loudness, silence  # noqa: F401, PLC0415
    from deepdub_qc.detectors.metadata import ffprobe  # noqa: F401, PLC0415

    return [_REGISTRY[key]() for key in sorted(_REGISTRY)]
