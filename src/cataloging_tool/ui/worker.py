from __future__ import annotations

import asyncio
import traceback
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from cataloging_tool.domain.enums import JobMode
from cataloging_tool.workflow.events import ProgressEvent


class QtEventSink(QObject):
    """Qt signal adapter that structurally satisfies WorkflowEventSink."""

    progress = Signal(object)

    def __init__(self) -> None:
        super().__init__()

    def publish(self, event: ProgressEvent) -> None:
        self.progress.emit(event)


class AutomationWorker(QObject):
    progress = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, runner: Any, profile_query: str, mode: JobMode, target: str = "") -> None:
        super().__init__()
        self.runner = runner
        self.profile_query = profile_query
        self.mode = mode
        self.target = target
        self._loop: asyncio.AbstractEventLoop | None = None
        sink = QtEventSink()
        sink.progress.connect(self.progress.emit)
        self._sink = sink
        self.runner.event_sink = sink

    @Slot()
    def run(self) -> None:
        try:
            asyncio.run(self._run_async())
        except Exception:
            self.failed.emit(traceback.format_exc())
        finally:
            self.finished.emit()

    async def _run_async(self) -> None:
        self._loop = asyncio.get_running_loop()
        try:
            if self.mode == JobMode.RESUME:
                jobs = self.runner.jobs.find_resumable()
                if not jobs:
                    raise RuntimeError("Không có job đang dở để tiếp tục.")
                await self.runner.resume(jobs[0])
            else:
                await self.runner.run_new(self.profile_query, self.mode, self.target)
        finally:
            await self.runner.browser_session.stop(save_trace=True)
            self._loop = None

    def cancel(self) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self.runner.request_cancel)
