from cataloging_tool.automation.pages import (
    form_marks_unknown_document,
    viewer_reports_zero_pages,
)
from cataloging_tool.domain.enums import RecordStatus
from cataloging_tool.domain.models import FormSnapshot


def test_explicit_unknown_placeholder_is_detected() -> None:
    assert form_marks_unknown_document(
        FormSnapshot(document_number="Không xác định", symbol="Ký hiệu văn bản")
    )


def test_valid_document_is_never_treated_as_missing_placeholder() -> None:
    assert not form_marks_unknown_document(
        FormSnapshot(document_number="91", symbol="BC/ĐU")
    )


def test_missing_pdf_has_a_distinct_resume_safe_status() -> None:
    assert RecordStatus.SKIPPED_NO_PDF.value == "skipped_no_pdf"


def test_viewer_zero_of_zero_is_detected() -> None:
    assert viewer_reports_zero_pages("Chi tiết 0 trên 0")
    assert viewer_reports_zero_pages("Page 0 / 0")
    assert not viewer_reports_zero_pages("1 trên 3")
