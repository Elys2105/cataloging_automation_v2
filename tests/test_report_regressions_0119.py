from __future__ import annotations

from pathlib import Path

import yaml

from cataloging_tool.document.parser import DocumentParser
from cataloging_tool.document.report_title import (
    choose_better_report_title,
    extract_report_title_block,
    recover_special_report_title_from_candidates,
    report_title_needs_recovery,
)
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


def test_normal_report_never_appends_form_date_without_pdf_parenthetical() -> None:
    value = extract_report_title_block(
        """
        BÁO CÁO
        Về tình hình kinh tế, xã hội, công tác xây dựng Đảng, hệ thống chính trị
        -----
        Thực hiện Công văn số 12-CV/TU
        """,
        document_date="2025-10-17",
    )
    assert value == (
        "Về tình hình kinh tế, xã hội, công tác xây dựng Đảng, hệ thống chính trị"
    )
    assert "Ngày 17" not in value


def test_normal_report_keeps_actual_ky_bao_cao_period() -> None:
    value = extract_report_title_block(
        """
        BÁO CÁO
        về nắm tình hình, giám sát thường xuyên việc phân cấp, phân quyền gắn với
        thực hiện thủ tục hành chính để vận hành chính quyền địa phương 02 cấp
        đảm bảo ổn định, thông suốt, đồng bộ
        (Kỳ báo cáo: ngày 13/10/2025)
        -----
        Thực hiện Công văn số 134-CV/UBKTTU
        """,
        document_date="2025-10-13",
    )
    assert value == (
        "về nắm tình hình, giám sát thường xuyên việc phân cấp, phân quyền gắn với "
        "thực hiện thủ tục hành chính để vận hành chính quyền địa phương 02 cấp "
        "đảm bảo ổn định, thông suốt, đồng bộ (Kỳ báo cáo: ngày 13/10/2025)"
    )


def test_longer_bounded_normal_report_title_wins_over_truncated_candidate() -> None:
    short = (
        "Về tình hình hoạt động các đơn vị, tình hình kinh tế, xã hội "
        "và nhiệm vụ trọng tâm cần tập trung"
    )
    full = (
        "Về tình hình hoạt động các đơn vị, tình hình kinh tế, xã hội và nhiệm vụ "
        "trọng tâm cần tập trung thực hiện trong xây dựng Đảng, hệ thống chính trị"
    )
    assert choose_better_report_title(short, full) == full
    assert report_title_needs_recovery(short)
    assert not report_title_needs_recovery(full)


def test_special_report_recovers_date_only_for_fixed_special_subject() -> None:
    title = recover_special_report_title_from_candidates(
        [
            "VỀ CÔNG TÁC NỘI CHÍNH, PHÒNG CHỐNG THAM NHŨNG, "
            "LÃNG PHÍ TIÊU CỰC VÀ CẢI CÁCH TƯ PHÁP",
            "A. TÌNH HÌNH, KẾT QUẢ",
        ],
        document_date="2025-10-08",
    )
    assert title == f"BÁO CÁO NGÀY 8 THÁNG 10 NĂM 2025 {SPECIAL_SUBJECT}"


def test_form_date_does_not_repair_unrelated_normal_report() -> None:
    title = recover_special_report_title_from_candidates(
        ["BÁO CÁO", "Về tình hình hoạt động các đơn vị"],
        document_date="2025-10-08",
    )
    assert title == ""


def test_parser_uses_bounded_report_title_and_ignores_old_appended_date(
    tmp_path: Path,
) -> None:
    parser = _parser(tmp_path)
    raw = """
    Số 152-BC/ĐU
    BÁO CÁO
    tình hình Nhân dân và dư luận xã hội về Đại hội đảng bộ các cấp tiến tới Đại hội
    đại biểu Đảng bộ Thành phố Hồ Chí Minh lần thứ I, nhiệm kỳ 2025 - 2030,
    Đại hội đại biểu Đảng bộ toàn quốc lần thứ XIV của Đảng
    -----
    Thực hiện Hướng dẫn số 03-HD/BTGDVTU
    """
    result = parser.parse(
        raw,
        source=DataSource.PADDLE_OCR,
        source_confidence=0.68,
        existing_form=FormSnapshot(
            document_number="152",
            symbol="BC/ĐU",
            document_type="Báo cáo",
            abstract=(
                "tình hình Nhân dân và dư luận xã hội về Đại hội đảng bộ các cấp "
                "tiến tới Đại hội đại biểu Đảng bộ Thành phố Hồ Chí Minh lần thứ I, "
                "nhiệm kỳ 2025 - 2030, Đại hội đại biểu Đảng bộ toàn quốc lần thứ XIV "
                "của Đảng (Ngày 15 tháng 10 năm 2025)"
            ),
            document_date="2025-10-15",
        ),
    )
    assert result.document_type.value == "Báo cáo"
    assert result.abstract.value.endswith("lần thứ XIV của Đảng")
    assert "Ngày 15 tháng 10 năm 2025" not in result.abstract.value
    assert result.overall_confidence >= 0.90


def test_dedicated_report_title_overrides_stale_wrong_type(tmp_path: Path) -> None:
    parser = _parser(tmp_path)
    special = (
        "BÁO CÁO NGÀY 8 THÁNG 10 NĂM 2025 " + SPECIAL_SUBJECT
    )
    result = parser.parse(
        "nội dung OCR chung không đủ tiêu đề",
        source=DataSource.PADDLE_OCR,
        source_confidence=0.60,
        existing_form=FormSnapshot(
            document_number="137",
            symbol="CV/UBKTTU",
            document_type="Khác",
            abstract="A29.125.A29.125.001.14.014",
            document_date="2025-10-08",
        ),
        special_report_title=special,
        is_landscape=True,
    )
    assert result.document_type.value == "Báo cáo"
    assert result.abstract.value == special
    assert result.abstract.confidence == 0.99


def test_normal_report_without_separator_stops_at_body_and_is_complete() -> None:
    value = extract_report_title_block(
        """
        BÁO CÁO
        Về tình hình hoạt động các đơn vị, tình hình kinh tế, xã hội và nhiệm vụ
        trọng tâm cần tập trung thực hiện trong xây dựng Đảng, hệ thống chính trị
        Thực hiện Chương trình số 01-CTr/ĐU ngày 06 tháng 8 năm 2025
        """
    )
    assert value == (
        "Về tình hình hoạt động các đơn vị, tình hình kinh tế, xã hội và nhiệm vụ "
        "trọng tâm cần tập trung thực hiện trong xây dựng Đảng, hệ thống chính trị"
    )
