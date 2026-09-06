from __future__ import annotations

from pathlib import Path

import yaml

from cataloging_tool.document.parser import DocumentParser
from cataloging_tool.document.report_title import (
    extract_report_title_block,
    recover_special_report_title_from_candidates,
    report_abstract_is_garbage,
)
from cataloging_tool.domain.enums import DataSource
from cataloging_tool.domain.models import FormSnapshot


def _parser(tmp_path: Path) -> DocumentParser:
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "vietnamese_normalization.tsv").write_text("", encoding="utf-8")
    (rules / "document_types.yaml").write_text(
        yaml.safe_dump({"BC": "Báo cáo"}, allow_unicode=True), encoding="utf-8"
    )
    (rules / "known_overrides.yaml").write_text("[]", encoding="utf-8")
    return DocumentParser(rules, "Tác giả", "Thường")


def test_normal_report_keeps_parenthetical_document_date(tmp_path: Path) -> None:
    parser = _parser(tmp_path)
    text = """
    Số 156-BC/ĐU
    BÁO CÁO
    Về tình hình kinh tế, xã hội, công tác xây dựng Đảng, hệ thống chính trị
    (Ngày 17 tháng 10 năm 2025)
    -----
    Thực hiện Công văn số 12-CV/TU
    """
    result = parser.parse(text, source=DataSource.PDF_TEXT, source_confidence=0.99)
    assert result.abstract.value == (
        "Về tình hình kinh tế, xã hội, công tác xây dựng Đảng, "
        "hệ thống chính trị (Ngày 17 tháng 10 năm 2025)"
    )


def test_normal_report_does_not_invent_date_when_pdf_title_has_none(
    tmp_path: Path,
) -> None:
    parser = _parser(tmp_path)
    text = """
    Số 154-BC/ĐU
    BÁO CÁO
    Về tình hình kinh tế, xã hội, công tác xây dựng Đảng, hệ thống chính trị
    -----
    Thực hiện Công văn số 12-CV/TU
    """
    result = parser.parse(
        text,
        source=DataSource.PADDLE_OCR,
        source_confidence=0.72,
        existing_form=FormSnapshot(
            document_number="154",
            symbol="BC/ĐU",
            document_type="Báo cáo",
            abstract="Về tình hình kinh tế, xã hội, công tác xây dựng Đảng, hệ thống chính trị",
            document_date="2025-10-16",
        ),
    )
    assert result.abstract.value == (
        "Về tình hình kinh tế, xã hội, công tác xây dựng Đảng, "
        "hệ thống chính trị"
    )
    assert "Ngày 16 tháng 10 năm 2025" not in result.abstract.value
    assert result.abstract.confidence >= 0.95


def test_report_parser_rejects_identifier_and_html_garbage_from_old_form(
    tmp_path: Path,
) -> None:
    parser = _parser(tmp_path)
    text = """
    Số 152-BC/ĐU
    BÁO CÁO
    tình hình Nhân dân và dư luận xã hội về Đại hội đảng bộ các cấp tiến tới Đại hội
    đại biểu Đảng bộ Thành phố Hồ Chí Minh lần thứ I, nhiệm kỳ 2025 - 2030,
    Đại hội đại biểu Đảng bộ toàn quốc lần thứ XIV của Đảng
    -----
    Thực hiện Hướng dẫn số 03-HD/BTGDVTU
    """
    result = parser.parse(
        text,
        source=DataSource.PADDLE_OCR,
        source_confidence=0.76,
        existing_form=FormSnapshot(
            document_number="152",
            symbol="BC/ĐU",
            document_type="Báo cáo",
            abstract="x¬ 4n: võ NI Riek &gt; wa Ar à va s.,* wrvrwwr",
            document_date="2025-10-15",
        ),
    )
    assert result.abstract.value.startswith("tình hình Nhân dân và dư luận xã hội")
    assert "wrvr" not in result.abstract.value
    assert "(Ngày 15 tháng 10 năm 2025)" not in result.abstract.value


def test_special_report_can_merge_date_and_subject_from_separate_crops() -> None:
    title = recover_special_report_title_from_candidates(
        [
            "Số 150-BC/ĐU\nBÁO CÁO NGÀY 15 THÁNG 10 NĂM 2025",
            "VỀ CÔNG TÁC NỘI CHÍNH, PHÒNG CHỐNG THAM NHŨNG, "
            "LÃNG PHÍ TIÊU CỰC VÀ CẢI CÁCH TƯ PHÁP\nA. TÌNH HÌNH, KẾT QUẢ",
        ]
    )
    assert title == (
        "BÁO CÁO NGÀY 15 THÁNG 10 NĂM 2025 "
        "VỀ CÔNG TÁC NỘI CHÍNH, PHÒNG CHỐNG THAM NHŨNG, "
        "LÃNG PHÍ TIÊU CỰC VÀ CẢI CÁCH TƯ PHÁP"
    )


def test_report_identifier_is_never_a_valid_abstract() -> None:
    assert report_abstract_is_garbage("A29.125.A29.125.001.14.027")
    assert report_abstract_is_garbage("x¬ 4n: võ NI Riek &gt; wa Ar à va s.,* wrvrwwr")
    assert not report_abstract_is_garbage(
        "Về tình hình kinh tế, xã hội, công tác xây dựng Đảng, hệ thống chính trị"
    )


def test_extract_normal_report_title_stops_before_body_and_keeps_date() -> None:
    value = extract_report_title_block(
        """
        BÁO CÁO
        Về tình hình kinh tế, xã hội, công tác xây dựng Đảng, hệ thống chính trị
        (Ngày 17 tháng 10 năm 2025)
        -----
        Thực hiện Công văn số 12-CV/TU
        """
    )
    assert value.endswith("(Ngày 17 tháng 10 năm 2025)")
    assert "Thực hiện Công văn" not in value


def test_special_report_uses_form_date_only_in_table_recovery() -> None:
    raw = """
    BÁO CÁO
    VỀ CÔNG TÁC NỘI CHÍNH, PHÒNG CHỐNG THAM NHŨNG,
    LÃNG PHÍ TIÊU CỰC VÀ CẢI CÁCH TƯ PHÁP
    A. TÌNH HÌNH, KẾT QUẢ
    STT  Tên công việc  Đơn vị tính
    """
    # Generic extraction never invents a date from form fields.
    assert "NGÀY 15" not in extract_report_title_block(
        raw, document_date="2025-10-15"
    )
    # The dedicated table-layout recovery may restore the tiny fixed date line.
    value = recover_special_report_title_from_candidates(
        [raw], document_date="2025-10-15"
    )
    assert value == (
        "BÁO CÁO NGÀY 15 THÁNG 10 NĂM 2025 "
        "VỀ CÔNG TÁC NỘI CHÍNH, PHÒNG CHỐNG THAM NHŨNG, "
        "LÃNG PHÍ TIÊU CỰC VÀ CẢI CÁCH TƯ PHÁP"
    )
