"""Preset engine: load and validate versioned YAML client presets (ADR-003)."""

from deepdub_qc.presets.loader import load_preset, preset_sha256

__all__ = ["load_preset", "preset_sha256"]
