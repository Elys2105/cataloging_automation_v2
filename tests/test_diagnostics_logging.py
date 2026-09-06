from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler

from cataloging_tool.diagnostics.logging_config import JsonFormatter, configure_logging


def _close_root_handlers() -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()


def test_logging_uses_bounded_rotating_files(tmp_path):
    try:
        configure_logging(tmp_path)
        handlers = logging.getLogger().handlers
        rotating = [item for item in handlers if isinstance(item, RotatingFileHandler)]
        assert len(rotating) == 2
        assert all(item.backupCount == 5 for item in rotating)
        assert all(item.maxBytes > 0 for item in rotating)
    finally:
        _close_root_handlers()


def test_json_formatter_keeps_structured_workflow_context():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="test", level=logging.ERROR, pathname=__file__, lineno=1, msg="boom", args=(), exc_info=None
    )
    record.slot_id = 2
    record.job_id = 11
    record.record_id = 7
    record.record_external_id = "ABC"
    record.position = 3
    record.total = 10
    record.stage = "PARSE"
    record.error_code = "PARSE_ERROR"
    record.field = "abstract"
    payload = json.loads(formatter.format(record))
    assert payload["slot_id"] == 2
    assert payload["position"] == 3
    assert payload["total"] == 10
    assert payload["stage"] == "PARSE"
    assert payload["error_code"] == "PARSE_ERROR"
    assert payload["field"] == "abstract"


def test_reconfigure_logging_closes_old_file_handlers(tmp_path):
    try:
        configure_logging(tmp_path / "first")
        old_handlers = list(logging.getLogger().handlers)
        old_file_handlers = [item for item in old_handlers if isinstance(item, RotatingFileHandler)]
        configure_logging(tmp_path / "second")
        assert old_file_handlers
        assert all(item.stream is None for item in old_file_handlers)
    finally:
        _close_root_handlers()
