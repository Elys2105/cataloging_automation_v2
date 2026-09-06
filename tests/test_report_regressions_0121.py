from __future__ import annotations

from pathlib import Path

import yaml

from cataloging_tool.document.parser import DocumentParser
from cataloging_tool.document.report_title import (
    choose_better_report_title,
    extract_report_title_block,
    repair_report_title,
)
from cataloging_tool.domain.enums import DataSource
from cataloging_tool.domain.models import FormSnapshot


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


def test_report_header_evidence_owns_number_and_symbol(tmp_path: Path) -> None:
    parser = _parser(tmp_path)
    body_ocr = """
    Thực hiện Kế hoạch số 15-KH/TU
    Công văn số 134-CV/UBKTTU ngày 14 tháng 8 năm 2025
    I. TÌNH HÌNH, KẾT QUẢ
    """
    header_ocr = """
    Số 118-BC/ĐU
    BÁO CÁO
    Tổng kết thực hiện Nghị quyết số 18-NQ/TW ngày 25 tháng 10 năm 2017
    của Ban Chấp hành Trung ương Đảng (khóa XII)
    -----
    """
    result = parser.parse(
        body_ocr,
        source=DataSource.PADDLE_OCR,
        source_confidence=0.65,
        existing_form=FormSnapshot(
            document_number="134",
            symbol="CV/UBKTTU",
            document_type="Công văn",
            abstract="Tổng kết thực hiện Nghị quyết số 18-NQ/TW",
        ),
        special_report_title=extract_report_title_block(header_ocr),
        header_evidence_text=header_ocr,
    )
    assert result.document_number.value == "118"
    assert result.symbol.value == "BC/ĐU"
    assert result.document_type.value == "Báo cáo"
    assert result.abstract.value == (
        "Tổng kết thực hiện Nghị quyết số 18-NQ/TW ngày 25 tháng 10 năm 2017 "
        "của Ban Chấp hành Trung ương Đảng (khóa XII)"
    )


def test_overlapping_crop_titles_are_not_duplicated() -> None:
    raw = """
    BÁO CÁO
    Tổng kết công tác phòng, chống tham nhũng, lãng phí, tiêu cực
    nhiệm kỳ 2020 - 2025
    BÁO CÁO
    Tổng kết công tác phòng, chống tham nhũng, lãng phí, tiêu cực
    nhiệm kỳ 2020 - 2025
    -----
    Thực hiện Kế hoạch số 15-KH/TU
    """
    assert extract_report_title_block(raw) == (
        "Tổng kết công tác phòng, chống tham nhũng, lãng phí, tiêu cực "
        "nhiệm kỳ 2020 - 2025"
    )


def test_noisy_fixed_report_titles_are_repaired_conservatively() -> None:
    assert repair_report_title(
        "Tng kt công tác phng, chng tham nhng, lãng phí, tiêu cc nhim k 2020 - 2025"
    ) == (
        "Tổng kết công tác phòng, chống tham nhũng, lãng phí, tiêu cực "
        "nhiệm kỳ 2020 - 2025"
    )
    assert repair_report_title(
        "Tổng kết thực hiện Nghị quyết số 18-NQ/TW ngày 25 tháng 10 năm 2017 "
        "ca Ban Chp hnh Trung ương Đng (khóa XII)"
    ) == (
        "Tổng kết thực hiện Nghị quyết số 18-NQ/TW ngày 25 tháng 10 năm 2017 "
        "của Ban Chấp hành Trung ương Đảng (khóa XII)"
    )


def test_full_title_beats_missing_beginning_and_body_overrun() -> None:
    missing_beginning = "của Ban Chấp hành Trung ương Đảng (khóa XII)"
    full = (
        "Tổng kết thực hiện Nghị quyết số 18-NQ/TW ngày 25 tháng 10 năm 2017 "
        "của Ban Chấp hành Trung ương Đảng (khóa XII)"
    )
    overrun = full + " Thực hiện Kế hoạch số 22-KH/TU ngày 16 tháng 9 năm 2025"
    assert choose_better_report_title(missing_beginning, overrun, full) == full


def test_old_form_cannot_append_or_replace_bounded_report_title(tmp_path: Path) -> None:
    parser = _parser(tmp_path)
    header = """
    Số 117-BC/ĐU
    BÁO CÁO
    Tổng kết công tác phòng, chống tham nhũng, lãng phí, tiêu cực
    nhiệm kỳ 2020 - 2025
    -----
    """
    result = parser.parse(
        "Thực hiện Kế hoạch số 15-KH/TU",
        source=DataSource.PADDLE_OCR,
        source_confidence=0.62,
        existing_form=FormSnapshot(
            document_number="117",
            symbol="BC/ĐU",
            document_type="Báo cáo",
            abstract=(
                "Tng kt công tác phng, chng tham nhng, lãng phí, tiêu cc "
                "nhim k 2020 - 2025 Thực hiện Kế hoạch số 15-KH/TU"
            ),
        ),
        special_report_title=extract_report_title_block(header),
        header_evidence_text=header,
    )
    assert result.abstract.value == (
        "Tổng kết công tác phòng, chống tham nhũng, lãng phí, tiêu cực "
        "nhiệm kỳ 2020 - 2025"
    )
    assert result.overall_confidence >= 0.82


def test_report_body_overrun_from_old_form_cannot_replace_bounded_title(tmp_path: Path) -> None:
    parser = _parser(tmp_path)
    header = """
    Số 113-BC/ĐU
    BÁO CÁO
    tình hình thực hiện nhiệm vụ Quý III
    và phương hướng, nhiệm vụ Quý IV năm 2025
    -----
    """
    result = parser.parse(
        "Thực hiện Quy định số 219-QĐ/TU ngày 08 tháng 8 năm 2025 của Ban Thường vụ Thành ủy",
        source=DataSource.PADDLE_OCR,
        source_confidence=0.64,
        existing_form=FormSnapshot(
            document_number="113",
            symbol="BC/ĐU",
            document_type="Báo cáo",
            abstract=(
                "tình hình thực hiện nhiệm vụ Quý III và phương hướng, nhiệm vụ Quý IV năm 2025 "
                "(Ngày 8 tháng 8 năm 2025) Thành ủy về chế độ báo cáo của các cấp ủy"
            ),
        ),
        special_report_title=extract_report_title_block(header),
        header_evidence_text=header,
    )
    assert result.abstract.value == (
        "tình hình thực hiện nhiệm vụ Quý III và phương hướng, nhiệm vụ Quý IV năm 2025"
    )


def test_repeated_parenthetical_date_is_kept_once() -> None:
    value = (
        "Về tình hình kinh tế, xã hội, công tác xây dựng Đảng, hệ thống chính trị "
        "(Ngày 24 tháng 9 năm 2025) (Ngày 24 tháng 9 năm 2025)"
    )
    assert repair_report_title(value) == (
        "Về tình hình kinh tế, xã hội, công tác xây dựng Đảng, hệ thống chính trị "
        "(Ngày 24 tháng 9 năm 2025)"
    )


def test_full_multiline_report_title_beats_stale_missing_beginning(tmp_path: Path) -> None:
    parser = _parser(tmp_path)
    header = """
    Số 110-BC/ĐU
    BÁO CÁO
    Tình hình, kết quả triển khai thực hiện các văn bản chỉ đạo, kết luận của
    Bộ Chính trị, Ban Bí thư về sắp xếp tổ chức bộ máy của hệ thống chính trị
    và vận hành mô hình chính quyền địa phương 2 cấp
    -----
    """
    result = parser.parse(
        "I. KẾT QUẢ THỰC HIỆN",
        source=DataSource.PADDLE_OCR,
        source_confidence=0.64,
        existing_form=FormSnapshot(
            document_number="110",
            symbol="BC/ĐU",
            document_type="Báo cáo",
            abstract=(
                "Bộ Chính trị, Ban Bí thư về sắp xếp tổ chức bộ máy của hệ thống chính trị "
                "và vận hành mô hình chính quyền địa phương 2 cấp (Ngày 23 tháng 9 năm 2025)"
            ),
        ),
        special_report_title=extract_report_title_block(header),
        header_evidence_text=header,
    )
    assert result.abstract.value == (
        "Tình hình, kết quả triển khai thực hiện các văn bản chỉ đạo, kết luận của "
        "Bộ Chính trị, Ban Bí thư về sắp xếp tổ chức bộ máy của hệ thống chính trị "
        "và vận hành mô hình chính quyền địa phương 2 cấp"
    )


def test_header_bc_outranks_cited_kl_tw_and_stale_form(tmp_path: Path) -> None:
    parser = _parser(tmp_path)
    header = """
    Số 143-BC/ĐU
    BÁO CÁO
    về nắm tình hình, giám sát thường xuyên việc phân cấp, phân quyền gắn với
    thực hiện thủ tục hành chính để vận hành chính quyền địa phương 02 cấp
    đảm bảo ổn định, thông suốt, đồng bộ
    (Kỳ báo cáo: ngày 22/9/2025)
    -----
    """
    result = parser.parse(
        "Thực hiện Kết luận số 183-KL/TW ngày 01 tháng 8 năm 2025",
        source=DataSource.PADDLE_OCR,
        source_confidence=0.62,
        existing_form=FormSnapshot(
            document_number="183",
            symbol="KL/TW",
            document_type="Báo cáo",
            abstract="về nắm tình hình, giám sát thường xuyên việc phân cấp",
        ),
        special_report_title=extract_report_title_block(header),
        header_evidence_text=header,
    )
    assert result.document_number.value == "143"
    assert result.symbol.value == "BC/ĐU"
    assert result.abstract.value.endswith("(Kỳ báo cáo: ngày 22/9/2025)")


def test_short_ocr_junk_and_duplicate_date_are_removed() -> None:
    value = (
        "mm Về tình hình kinh tế, xã hội, công tác xây dựng Đảng, hệ thống chính trị "
        "(Ngày 19 tháng 9 năm 2025) (Ngày 19 tháng 9 năm 2025)"
    )
    assert repair_report_title(value) == (
        "Về tình hình kinh tế, xã hội, công tác xây dựng Đảng, hệ thống chính trị "
        "(Ngày 19 tháng 9 năm 2025)"
    )
