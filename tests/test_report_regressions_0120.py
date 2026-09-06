from __future__ import annotations

from pathlib import Path

import yaml

from cataloging_tool.document.parser import DocumentParser
from cataloging_tool.document.report_title import (
    extract_report_title_block,
    recover_special_report_title_from_candidates,
)
from cataloging_tool.document.text_extractor import DocumentTextExtractor
from cataloging_tool.domain.enums import DataSource
from cataloging_tool.domain.models import FormSnapshot

SPECIAL_SUBJECT = (
    "VỀ CÔNG TÁC NỘI CHÍNH, PHÒNG CHỐNG THAM NHŨNG, "
    "LÃNG PHÍ TIÊU CỰC VÀ CẢI CÁCH TƯ PHÁP"
)


def _parser(tmp_path: Path) -> DocumentParser:
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "vietnamese_normalization.tsv").write_text("", encoding="utf-8")
    (rules / "document_types.yaml").write_text(
        yaml.safe_dump({"BC": "Báo cáo", "CV": "Công văn"}, allow_unicode=True),
        encoding="utf-8",
    )
    (rules / "known_overrides.yaml").write_text("[]", encoding="utf-8")
    return DocumentParser(rules, "Tác giả", "Thường")


def test_stale_cong_van_form_cannot_beat_report_header(tmp_path: Path) -> None:
    parser = _parser(tmp_path)
    raw = """
    ĐẢNG ỦY PHƯỜNG BÌNH TIÊN
    Số 145-BC/ĐU
    BÁO CÁO
    về nắm tình hình, giám sát thường xuyên việc phân cấp, phân quyền gắn với
    thực hiện thủ tục hành chính để vận hành chính quyền địa phương 02 cấp
    đảm bảo ổn định, thông suốt, đồng bộ
    (Kỳ báo cáo: ngày 13/10/2025)
    -----
    Thực hiện Công văn số 134-CV/UBKTTU ngày 14 tháng 8 năm 2025
    """
    result = parser.parse(
        raw,
        source=DataSource.PADDLE_OCR,
        source_confidence=0.65,
        existing_form=FormSnapshot(
            document_number="134",
            symbol="CV/UBKTTU",
            document_type="Công văn",
            abstract="về nắm tình hình, giám sát thường xuyên việc phân cấp",
            document_date="2025-10-13",
        ),
    )
    assert result.document_number.value == "145"
    assert result.symbol.value == "BC/ĐU"
    assert result.document_type.value == "Báo cáo"
    assert result.abstract.value == (
        "về nắm tình hình, giám sát thường xuyên việc phân cấp, phân quyền gắn với "
        "thực hiện thủ tục hành chính để vận hành chính quyền địa phương 02 cấp "
        "đảm bảo ổn định, thông suốt, đồng bộ (Kỳ báo cáo: ngày 13/10/2025)"
    )
    assert result.overall_confidence >= 0.82


def test_body_reference_is_not_selected_as_report_number(tmp_path: Path) -> None:
    parser = _parser(tmp_path)
    raw = """
    Số 152-BC/ĐU
    BÁO CÁO
    tình hình Nhân dân và dư luận xã hội về Đại hội đảng bộ các cấp
    -----
    Thực hiện Hướng dẫn số 03-HD/BTGDVTU
    Công văn số 134-CV/UBKTTU được viện dẫn trong nội dung
    """
    result = parser.parse(raw, source=DataSource.PDF_TEXT, source_confidence=0.98)
    assert result.document_number.value == "152"
    assert result.symbol.value == "BC/ĐU"


def test_normal_report_continuation_lines_are_not_truncated() -> None:
    title = extract_report_title_block(
        """
        BÁO CÁO
        Về tình hình hoạt động các đơn vị, tình hình kinh tế, xã hội và nhiệm vụ
        trọng tâm cần tập trung thực hiện trong xây dựng Đảng, hệ thống chính trị
        -----
        Thực hiện Chương trình số 01-CTr/ĐU
        """,
        document_date="2025-10-02",
    )
    assert title == (
        "Về tình hình hoạt động các đơn vị, tình hình kinh tế, xã hội và nhiệm vụ "
        "trọng tâm cần tập trung thực hiện trong xây dựng Đảng, hệ thống chính trị"
    )
    assert "Ngày 2 tháng 10" not in title


def test_normal_report_keeps_visible_period_but_never_form_date() -> None:
    title = extract_report_title_block(
        """
        BÁO CÁO
        về nắm tình hình, giám sát thường xuyên việc phân cấp, phân quyền gắn với
        thực hiện thủ tục hành chính để vận hành chính quyền địa phương 02 cấp
        đảm bảo ổn định, thông suốt, đồng bộ
        (Kỳ báo cáo: ngày 06/10/2025)
        -----
        Thực hiện Công văn số 134-CV/UBKTTU
        """,
        document_date="2025-10-15",
    )
    assert title.endswith("(Kỳ báo cáo: ngày 6/10/2025)")
    assert "Ngày 15 tháng 10" not in title


def test_special_date_recovery_requires_table_layout() -> None:
    subject_only = f"BÁO CÁO\n{SPECIAL_SUBJECT}"
    assert recover_special_report_title_from_candidates(
        [subject_only], document_date="2025-10-08"
    ) == ""

    table_layout = subject_only + "\nA. TÌNH HÌNH, KẾT QUẢ\nSTT\nTên công việc\nĐơn vị tính"
    assert recover_special_report_title_from_candidates(
        [table_layout], document_date="2025-10-08"
    ) == f"BÁO CÁO NGÀY 8 THÁNG 10 NĂM 2025 {SPECIAL_SUBJECT}"


def test_report_is_detected_from_ocr_when_form_type_is_wrong() -> None:
    assert DocumentTextExtractor._looks_like_bao_cao_text(
        "Số 145-BC/ĐU\nBÁO CÁO\nVề nắm tình hình"
    )
    assert DocumentTextExtractor._looks_like_bao_cao_text(
        "A. TÌNH HÌNH, KẾT QUẢ\nSTT\nTóm tắt nội dung\nĐơn vị tính"
    )
