from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from cataloging_tool.domain.enums import RecordStatus


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    job_id: int
    record_id: int | None
    record_position: int | None
    position: int
    total: int
    status: RecordStatus | None
    message: str
    stage: str = ""


class WorkflowEventSink(Protocol):
    def publish(self, event: ProgressEvent) -> None: ...


class NullEventSink:
    def publish(self, event: ProgressEvent) -> None:
        return None
