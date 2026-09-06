from __future__ import annotations

import inspect
from pathlib import Path

from cataloging_tool.automation.pages import viewer_reports_zero_pages
from cataloging_tool.document.parser import DocumentParser
from cataloging_tool.domain.enums import DataSource
from cataloging_tool.domain.models import FormSnapshot
from cataloging_tool.workflow.runner import WorkflowRunner


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUTHOR = "ĐẢNG ỦY PHƯỜNG BÌNH TIÊN ĐẢNG BỘ THÀNH PHỐ HỒ CHÍ MINH"


def _parser() -> DocumentParser:
    return DocumentParser(ROOT / "rules", DEFAULT_AUTHOR, "Thường")


def _form(**values: str) -> FormSnapshot:
    base = dict(
        document_number="",
        symbol="",
        document_type="",
        abstract="",
        document_date="",
        author="",
        signer_name="",
    )
    base.update(values)
    return FormSnapshot(**base)


def test_positive_page_count_beats_hidden_stale_zero_over_zero() -> None:
    assert viewer_reports_zero_pages("Trang 1 trên 8 ẩn 0 trên 0") is False
    assert viewer_reports_zero_pages("1/8 0/0") is False
    assert viewer_reports_zero_pages("0 trên 0") is True
    assert viewer_reports_zero_pages("Đang tải tài liệu") is False


def test_unknown_record_attempts_pdf_acquisition_before_missing_pdf_skip() -> None:
    source = inspect.getsource(WorkflowRunner._process_one)
    assert source.index("acquire_pdf(record.external_id)") < source.index(
        "should_skip_missing_pdf"
    )


def test_normal_report_uses_title_not_cited_body_instrument() -> None:
    raw = """ĐẢNG BỘ THÀNH PHỐ HỒ CHÍ MINH
ĐẢNG ỦY PHƯỜNG BÌNH TIÊN
ĐẢNG CỘNG SẢN VIỆT NAM
Bình Tiên, ngày 16 tháng 12 năm 2025
Số 276-BC/ĐU
BÁO CÁO
Kết quả công tác phát triển đảng viên năm 2025
-----
Thực hiện Công văn 384-CV/BTCTU ngày 27 tháng 11 năm 2025 của Ban Tổ chức Thành ủy
Ban Thường vụ Đảng ủy phường báo cáo như sau:
I. ĐẶC ĐIỂM, TÌNH HÌNH"""
    result = _parser().parse(
        raw,
        source=DataSource.PDF_TEXT,
        source_confidence=0.99,
        existing_form=_form(
            document_number="276",
            symbol="BC/ĐU",
            document_type="Báo cáo",
            abstract=(
                "384-CV/BTCTU ngày 27 tháng 11 năm 2025 của Ban Tổ chức Thành ủy"
            ),
            document_date="2025-12-16",
        ),
        header_evidence_text=raw,
    )
    assert result.document_number.value == "276"
    assert result.symbol.value == "BC/ĐU"
    assert result.document_type.value == "Báo cáo"
    assert result.abstract.value == "Kết quả công tác phát triển đảng viên năm 2025"


def test_special_report_header_beats_stale_cv_form_and_body_citation() -> None:
    raw = """ĐẢNG ỦY PHƯỜNG BÌNH TIÊN
ĐẢNG CỘNG SẢN VIỆT NAM
Bình Tiên, ngày 11 tháng 12 năm 2025
Số 266-BC/ĐU
BÁO CÁO NGÀY 11 THÁNG 12 NĂM 2025
VỀ CÔNG TÁC NỘI CHÍNH, PHÒNG CHỐNG THAM NHŨNG, LÃNG PHÍ TIÊU CỰC VÀ CẢI CÁCH TƯ PHÁP
Thực hiện Công văn số 272-CV/BNCTU ngày 12 tháng 8 năm 2025
A. TÌNH HÌNH, KẾT QUẢ
STT Tên công việc, vụ việc xảy ra cần báo cáo"""
    result = _parser().parse(
        raw,
        source=DataSource.PDF_TEXT,
        source_confidence=0.99,
        existing_form=_form(
            document_number="272",
            symbol="CV/BNCTU",
            document_type="Công văn",
            abstract="Về công tác nội chính XI SEAR NGHI YEN",
            document_date="2025-12-11",
        ),
        is_landscape=True,
        header_evidence_text=raw,
    )
    assert result.document_number.value == "266"
    assert result.symbol.value == "BC/ĐU"
    assert result.document_type.value == "Báo cáo"
    assert result.abstract.value == (
        "BÁO CÁO NGÀY 11 THÁNG 12 NĂM 2025 "
        "VỀ CÔNG TÁC NỘI CHÍNH, PHÒNG CHỐNG THAM NHŨNG, "
        "LÃNG PHÍ TIÊU CỰC VÀ CẢI CÁCH TƯ PHÁP"
    )


def test_normal_report_recovers_full_title_and_visible_parenthetical_date() -> None:
    raw = """ĐẢNG BỘ THÀNH PHỐ HỒ CHÍ MINH
ĐẢNG ỦY PHƯỜNG BÌNH TIÊN
ĐẢNG CỘNG SẢN VIỆT NAM
Bình Tiên, ngày 15 tháng 12 năm 2025
Số 272-BC/ĐU
BÁO CÁO
về tình hình kinh tế, xã hội, công tác xây dựng Đảng, hệ thống chính trị
(Ngày 15 tháng 12 năm 2025)
-----
Thực hiện Công văn số 12-CV/TU ngày 15 tháng 7 năm 2025 của Ban Thường vụ Thành ủy"""
    result = _parser().parse(
        raw,
        source=DataSource.PDF_TEXT,
        source_confidence=0.99,
        existing_form=_form(
            document_number="277",
            symbol="CV/TW",
            document_type="Công văn",
            abstract="về tình hình",
            document_date="2025-12-15",
        ),
        header_evidence_text=raw,
    )
    assert result.document_number.value == "272"
    assert result.symbol.value == "BC/ĐU"
    assert result.document_type.value == "Báo cáo"
    assert result.abstract.value == (
        "về tình hình kinh tế, xã hội, công tác xây dựng Đảng, "
        "hệ thống chính trị (Ngày 15 tháng 12 năm 2025)"
    )
