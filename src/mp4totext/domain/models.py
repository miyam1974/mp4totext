from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType


class ProgressStage(StrEnum):
    PREPARING = "preparing"
    DOWNLOADING_MODEL = "downloading_model"
    TRANSCRIBING = "transcribing"
    SAVING = "saving"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class TranscriptionOptions:
    model_name: str = "small"
    language: str | None = None
    compute_type: str = "int8"
    vad_filter: bool = True


@dataclass(frozen=True, slots=True)
class Segment:
    start_seconds: float
    end_seconds: float
    text: str

    def __post_init__(self) -> None:
        if self.start_seconds < 0:
            raise ValueError("Segment start time cannot be negative")
        if self.end_seconds < self.start_seconds:
            raise ValueError("Segment end time cannot precede start time")


@dataclass(frozen=True, slots=True)
class Transcript:
    language: str | None
    language_probability: float | None
    duration_seconds: float | None
    segments: tuple[Segment, ...]
    metadata: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))

    @property
    def text(self) -> str:
        return "\n".join(segment.text.strip() for segment in self.segments if segment.text.strip())


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    stage: ProgressStage
    fraction: float | None
    message: str

    def __post_init__(self) -> None:
        if self.fraction is not None and not 0 <= self.fraction <= 1:
            raise ValueError("Progress fraction must be between 0 and 1")
