from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


def test_ui_worker_imports_without_metaclass_conflict() -> None:
    from cataloging_tool.ui.worker import AutomationWorker, QtEventSink

    assert AutomationWorker is not None
    assert QtEventSink is not None
