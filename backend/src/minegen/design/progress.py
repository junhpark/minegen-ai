"""Progress reporting contract for long-running design algorithms (rule 60).

Algorithms call a plain ``ProgressCallback`` with ``ProgressEvent`` values.
They never import job, thread or WebSocket machinery. Progress reporting
must not influence results; the default callback is a no-op.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class ProgressStage(StrEnum):
    LEVEL_STARTED = "LEVEL_STARTED"
    CANDIDATE_STARTED = "CANDIDATE_STARTED"
    CANDIDATE_COMPLETED = "CANDIDATE_COMPLETED"
    LEVEL_COMPLETED = "LEVEL_COMPLETED"
    DECLINE_COMPLETED = "DECLINE_COMPLETED"
    SEGMENT_STARTED = "SEGMENT_STARTED"
    SEGMENT_COMPLETED = "SEGMENT_COMPLETED"
    SMOOTHING_COMPLETED = "SMOOTHING_COMPLETED"


@dataclass(frozen=True)
class ProgressEvent:
    stage: ProgressStage
    phase: str  # e.g. "DECLINE_SEARCH"
    level: int  # 1-based index of the current level
    total_levels: int
    candidate: int  # 1-based index of the current candidate (0 when not in a candidate)
    total_candidates: int
    progress: float  # 0..1
    expanded_states: int  # cumulative
    message: str = ""
    level_id: str = ""
    candidate_id: str = ""
    candidate_status: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["stage"] = self.stage.value
        return d


ProgressCallback = Callable[[ProgressEvent], None]


def no_progress(_: ProgressEvent) -> None:
    return None
