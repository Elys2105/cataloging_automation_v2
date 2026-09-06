from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

from cataloging_tool.automation.pages import (
    DocumentEditPage,
    form_needs_full_metadata_recovery,
)
from cataloging_tool.document.parser import DocumentParser
from cataloging_tool.document.text_extractor import DocumentTextExtractor
from cataloging_tool.document.validator import DocumentValidator
from cataloging_tool.domain.enums import DataSource, Severity
from cataloging_tool.domain.models import FormSnapshot, ParsedDocument, ParsedField
from cataloging_tool.workflow.runner import WorkflowRunner


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_AUTHOR = (
    "ĐẢNG ỦY PHƯỜNG BÌNH TIÊN ĐẢNG BỘ THÀNH PHỐ HỒ CHÍ MINH"
)


def _parser() -> DocumentParser:
    return DocumentParser(ROOT / "rules", "", "Thường")


def _blank_unknown_form() -> FormSnapshot:
    return FormSnapshot(
        document_number="Không xác định",
        symbol="Ký hiệu văn bản",
        document_type="--Tên thể loại văn bản--",
        abstract="",
        document_date="",
        author="",
        security_level="--Chọn độ mật--",
        signer_name="",
    )


def test_supplied_blank_pdf_report_recovers_every_requested_field() -> None:
    raw = """ĐẢNG BỘ THÀNH PHỐ HỒ CHÍ MINH
ĐẢNG ỦY PHƯỜNG BÌNH TIÊN
ĐẢNG CỘNG SẢN VIỆT NAM
Bình Tiên, ngày 08 tháng 12 năm 2025
Số 258-BC/ĐU
BÁO CÁO
về tình hình kinh tế, xã hội, công tác xây dựng Đảng, hệ thống chính trị
(Ngày 08 tháng 12 năm 2025)
-----
Thực hiện Công văn số 12-CV/TU ngày 15 tháng 7 năm 2025 của Ban Thường vụ Thành ủy
báo cáo như sau:"""

    result = _parser().parse(
        raw,
        source=DataSource.PDF_TEXT,
        source_confidence=0.995,
        existing_form=_blank_unknown_form(),
        header_evidence_text=raw,
        author_evidence_text=raw,
    )
    WorkflowRunner._require_complete_unknown_pdf_metadata(result)
    issues = DocumentValidator(0.82, require_author=True).validate(result)

    assert result.document_type.value == "Báo cáo"
    assert result.document_number.value == "258"
    assert result.symbol.value == "BC/ĐU"
    assert result.document_date.value == "2025-12-08"
    assert result.abstract.value == (
        "về tình hình kinh tế, xã hội, công tác xây dựng Đảng, "
        "hệ thống chính trị (Ngày 8 tháng 12 năm 2025)"
    )
    assert result.author == EXPECTED_AUTHOR
    assert result.security_level == "Thường"
    assert result.security_source_text == "default:no-explicit-security-marking"
    assert not [item for item in issues if item.severity == Severity.ERROR]
    assert DocumentValidator.can_auto_submit(result)


def test_focused_header_can_recover_generic_non_report_when_page_ocr_misses_heading() -> None:
    page_ocr = """Nội dung văn bản bắt đầu ở đây
Căn cứ quy định hiện hành
Điều 1. Ban hành kèm theo..."""
    focused_header = """ĐẢNG BỘ THÀNH PHỐ HỒ CHÍ MINH
ĐẢNG ỦY PHƯỜNG BÌNH TIÊN
ĐẢNG CỘNG SẢN VIỆT NAM
Bình Tiên, ngày 08 tháng 12 năm 2025
Số 259-QĐ/ĐU
QUYẾT ĐỊNH
về việc ban hành Quy chế làm việc
-----"""
    result = _parser().parse(
        page_ocr,
        source=DataSource.PADDLE_OCR,
        source_confidence=0.70,
        existing_form=_blank_unknown_form(),
        header_evidence_text=focused_header,
        author_evidence_text=focused_header,
    )

    assert result.document_number.value == "259"
    assert result.symbol.value == "QĐ/ĐU"
    assert result.document_type.value == "Quyết định"
    assert result.abstract.value == "về việc ban hành Quy chế làm việc"
    assert result.document_date.value == "2025-12-08"
    assert result.author == EXPECTED_AUTHOR


def test_empty_and_explicit_unknown_forms_enter_full_metadata_recovery_only() -> None:
    assert form_needs_full_metadata_recovery(_blank_unknown_form())
    assert form_needs_full_metadata_recovery(FormSnapshot())
    assert form_needs_full_metadata_recovery(
        FormSnapshot(
            document_number="",
            symbol="Ký hiệu văn bản",
            document_type="--Tên thể loại văn bản--",
        )
    )

    # A partially catalogued record must keep the normal reconciliation path.
    assert not form_needs_full_metadata_recovery(
        FormSnapshot(
            document_number="258",
            symbol="BC/ĐU",
            document_type="Báo cáo",
            abstract="về tình hình kinh tế, xã hội",
        )
    )


def _complete_document() -> ParsedDocument:
    return ParsedDocument(
        document_number=ParsedField("258", 0.99, "header"),
        symbol=ParsedField("BC/ĐU", 0.99, "header"),
        document_type=ParsedField("Báo cáo", 0.99, "header"),
        abstract=ParsedField("về tình hình kinh tế, xã hội", 0.99, "title"),
        document_date=ParsedField("2025-12-08", 0.99, "date"),
        author=EXPECTED_AUTHOR,
        author_confidence=0.99,
        security_level="Thường",
        security_confidence=0.95,
        security_source_text="default:no-explicit-security-marking",
        overall_confidence=0.99,
    )


def test_unknown_recovery_retries_weak_date_or_author_and_blocks_missing_metadata() -> None:
    complete = _complete_document()
    assert not WorkflowRunner._unknown_metadata_needs_retry(complete)
    WorkflowRunner._require_complete_unknown_pdf_metadata(complete)
    assert not complete.issues

    weak = _complete_document()
    weak.document_date = ParsedField("2025-12-08", 0.70, "weak")
    assert WorkflowRunner._unknown_metadata_needs_retry(weak)

    missing = _complete_document()
    missing.abstract = ParsedField("", 0.0, "")
    WorkflowRunner._require_complete_unknown_pdf_metadata(missing)
    assert any(
        issue.code == "UNKNOWN_PDF_METADATA_INCOMPLETE"
        and issue.severity == Severity.ERROR
        and "Trích yếu nội dung" in issue.message
        for issue in missing.issues
    )


def test_unknown_form_selects_document_type_before_number_and_symbol(monkeypatch) -> None:
    calls: list[tuple[str, str, str]] = []
    page = DocumentEditPage(page=object(), pdf_acquirer=object())
    document = _complete_document()
    before = _blank_unknown_form()
    final = FormSnapshot(
        document_number="258",
        symbol="BC/ĐU",
        document_type="Báo cáo",
        abstract="về tình hình kinh tế, xã hội",
        document_date="2025-12-08",
        author=EXPECTED_AUTHOR,
        security_level="Thường",
        signer_name="",
    )

    async def fake_select(_self, label: str, value: str) -> None:
        calls.append(("select", label, value))

    async def fake_wait(_self, label: str, attempts: int = 30) -> None:
        calls.append(("wait", label, str(attempts)))

    async def fake_fill(_self, label: str, value: str) -> None:
        calls.append(("fill", label, value))

    async def fake_date(_self, value: str) -> None:
        calls.append(("date", "Ngày, tháng, năm văn bản", value))

    async def fake_read(_self) -> FormSnapshot:
        return final

    monkeypatch.setattr(DocumentEditPage, "_select_or_fill", fake_select)
    monkeypatch.setattr(DocumentEditPage, "_wait_field_ready", fake_wait)
    monkeypatch.setattr(DocumentEditPage, "_fill_field", fake_fill)
    monkeypatch.setattr(DocumentEditPage, "_fill_document_date", fake_date)
    monkeypatch.setattr(DocumentEditPage, "read_form", fake_read)

    actual = asyncio.run(page.fill_from_parsed(document, before))
    assert actual == final

    type_index = calls.index(("select", "Tên thể loại văn bản", "Báo cáo"))
    number_index = calls.index(("fill", "Số văn bản", "258"))
    symbol_index = calls.index(("fill", "Ký hiệu văn bản", "BC/ĐU"))
    assert type_index < number_index < symbol_index
    assert ("wait", "Số văn bản", "30") in calls
    assert ("wait", "Ký hiệu văn bản", "30") in calls
    assert ("select", "Độ mật", "Thường") in calls
    assert ("date", "Ngày, tháng, năm văn bản", "2025-12-08") in calls


def test_force_metadata_recovery_uses_rendered_pdf_and_all_focused_modes() -> None:
    source = inspect.getsource(DocumentTextExtractor.extract)
    focused = inspect.getsource(DocumentTextExtractor._recover_document_header)
    runner_source = inspect.getsource(WorkflowRunner._process_one)

    assert "metadata_source_image = source_image or rendered.full_page" in source
    assert "force_full_metadata=(metadata_recovery or force_metadata_recovery)" in source
    assert 'if force_full_metadata or (cv_hint and (is_number_crop or is_title_crop))' in focused
    assert "force_metadata_recovery=True" in runner_source
    assert 'symbol_hint = "" if metadata_recovery_record else existing_form.symbol' in runner_source
    assert 'type_hint = "" if metadata_recovery_record else existing_form.document_type' in runner_source
