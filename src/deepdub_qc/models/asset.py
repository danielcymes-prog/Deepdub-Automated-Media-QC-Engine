"""Asset model: identity of the analyzed media file."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from deepdub_qc.models.types import NonEmptyStr


class Asset(BaseModel):
    """The media file a QC job analyzed. `sha256` makes results traceable to exact bytes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    input_path: NonEmptyStr
    filename: NonEmptyStr
    file_size_bytes: int = Field(ge=0)
    sha256: NonEmptyStr
    duration_seconds: float | None = Field(default=None, ge=0)
