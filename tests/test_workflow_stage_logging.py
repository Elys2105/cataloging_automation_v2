from __future__ import annotations

from types import SimpleNamespace

from cataloging_tool.domain.enums import RecordStatus
from cataloging_tool.domain.errors import ParseError
from cataloging_tool.domain.models import DocumentRecord
from cataloging_tool.workflow.runner import WorkflowRunner


class Sink:
    def __init__(self):
        self.events = []
    def publish(self, event):
        self.events.append(event)


def _runner(sink):
    obj = object.__new__(WorkflowRunner)
    obj.slot_id = 2
    obj.event_sink = sink
    return obj


def _record():
    return DocumentRecord(id=5, job_id=1, external_id="R-5", edit_url="", row_text="", position=23)


def test_stage_event_keeps_human_readable_stage():
    sink = Sink()
    runner = _runner(sink)
    runner._stage(9, _record(), 23, 80, "OPEN RECORD", "Mở bản ghi", RecordStatus.OPENING)
    assert sink.events[-1].stage == "OPEN RECORD"
    assert sink.events[-1].position == 23
    assert sink.events[-1].total == 80


def test_error_payload_contains_code_stage_record_and_artifact(tmp_path):
    runner = _runner(Sink())
    exc = ParseError("bad", step="parse", field="abstract")
    payload = runner._error_payload(exc, record=_record(), artifact_dir=tmp_path)
    assert payload["error_code"] == "PARSE_ERROR"
    assert payload["stage"] == "parse"
    assert payload["field"] == "abstract"
    assert payload["record"]["external_id"] == "R-5"
    assert payload["artifact"] == str(tmp_path)


def test_generic_exception_still_gets_stable_error_code(tmp_path):
    runner = _runner(Sink())
    payload = runner._error_payload(ValueError("bad"), record=_record(), artifact_dir=tmp_path)
    assert payload["error_code"] == "VALUE_ERROR"
