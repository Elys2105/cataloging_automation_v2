from __future__ import annotations

from pathlib import Path

import pytest

from cataloging_tool.document.document_header import (
    build_canonical_document_header_details,
    clean_cong_van_title,
    cong_van_title_is_clean,
)
from cataloging_tool.document.parser import DocumentParser
from cataloging_tool.document.validator import DocumentValidator
from cataloging_tool.domain.enums import DataSource
from cataloging_tool.domain.models import FormSnapshot


@pytest.fixture()
def parser() -> DocumentParser:
    root = Path(__file__).resolve().parents[1]
    return DocumentParser(root / "rules", "Tác giả", "Thường")


def parse_cv(parser: DocumentParser, header: str, *, old_abstract: str = ""):
    result = parser.parse(
        "Để có cơ sở xem xét, phần thân tuyệt đối không phải trích yếu.",
        source=DataSource.PADDLE_OCR,
        source_confidence=0.60,
        header_evidence_text=header,
        existing_form=FormSnapshot(
            document_number="",
            symbol="CV/ĐU",
            document_type="Công văn",
            abstract=old_abstract,
        ),
    )
    DocumentValidator().validate(result)
    return result


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "Về việc xác minh lý lịch đối với người xin vào Đảng quần chúng Nguyễn Thị Thùy Linh "
            "Kính oxrr' Plano ít oy cử BOS",
            "Về việc xác minh lý lịch đối với người xin vào Đảng quần chúng Nguyễn Thị Thùy Linh",
        ),
        (
            "Về việc xác minh thái độ chính trị phục vụ công tác kết nạp Đảng Ả",
            "Về việc xác minh thái độ chính trị phục vụ công tác kết nạp Đảng",
        ),
        (
            "Về việc xác minh nơi cư trú đối với bản thân và gia đình viên chức II Ự nè VI c: a. Co",
            "Về việc xác minh nơi cư trú đối với bản thân và gia đình viên chức",
        ),
        (
            "Về việc thống kê danh sách cán bộ, công chức J văn đi Đảng ủy năm 2025 Kính",
            "Về việc thống kê danh sách cán bộ, công chức",
        ),
        (
            "ve 3 mm Vô việc xác minh thái độ chính trị phục vụ công tác kết nạp Đảng - CT",
            "Về việc xác minh thái độ chính trị phục vụ công tác kết nạp Đảng",
        ),
    ],
)
def test_reported_cv_garbage_is_removed_at_a_hard_boundary(raw: str, expected: str) -> None:
    assert clean_cong_van_title(raw) == expected
    assert cong_van_title_is_clean(expected)


def test_record_141_stops_even_when_gui_is_corrupted(parser: DocumentParser) -> None:
    result = parse_cv(
        parser,
        """
        ĐẢNG ỦY PHƯỜNG BÌNH TIÊN
        Số 219-CV/ĐU
        Về việc xác minh lý lịch đối với người xin vào Đảng
        quần chúng Nguyễn Thị Thùy Linh
        Kính oxrr' Plano ít oy cử BOS: Ban Chỉ huy Công an phường Bình Tiên
        """,
    )
    assert result.document_number.value == "219"
    assert result.abstract.value == (
        "Về việc xác minh lý lịch đối với người xin vào Đảng "
        "quần chúng Nguyễn Thị Thùy Linh"
    )
    assert not any(issue.code in {"CV_ABSTRACT_INVALID", "ABSTRACT_BODY_LEAK"} for issue in result.issues)


def test_independent_header_readings_remove_leading_ocr_debris() -> None:
    details = build_canonical_document_header_details(
        [
            """ĐẢNG ỦY PHƯỜNG A
Số 5218-CV/ĐU
Về việc thẩm tra lý lịch
Kính gửi:""",
            """ĐẢNG ỦY PHƯỜNG A
Số 218-CV/ĐU
Về việc thẩm tra lý lịch
Kính gửi:""",
        ],
        symbol_hint="CV/ĐU",
        type_hint="Công văn",
        known_codes=("CV",),
    )
    assert details.number == "218"
    assert details.number_support >= 2


def test_record_92_preserves_date_line_inside_italic_title(parser: DocumentParser) -> None:
    result = parse_cv(
        parser,
        """
        ĐẢNG ỦY PHƯỜNG BÌNH TIÊN
        Số 167-CV/ĐU
        Về triển khai các quy định, quyết định
        ngày 30 tháng 8 năm 2025 của Ban Bí thư
        Kính gửi: Đảng ủy các cơ quan Đảng phường Bình Tiên
        """,
    )
    assert result.abstract.value == (
        "Về triển khai các quy định, quyết định ngày 30 tháng 8 năm 2025 của Ban Bí thư"
    )


def test_record_66_preserves_date_after_dot(parser: DocumentParser) -> None:
    result = parse_cv(
        parser,
        """
        ĐẢNG ỦY PHƯỜNG BÌNH TIÊN
        Số 141-CV/ĐU
        Về việc đề nghị xét tặng Huy hiệu Đảng đợt
        ngày 07 tháng 11 năm 2025
        Kính gửi: Ban Thường vụ Thành ủy Thành phố Hồ Chí Minh
        """,
    )
    assert result.abstract.value == (
        "Về việc đề nghị xét tặng Huy hiệu Đảng đợt ngày 07 tháng 11 năm 2025"
    )


def test_recipient_line_is_a_boundary_when_kinh_gui_was_missed(parser: DocumentParser) -> None:
    result = parse_cv(
        parser,
        """
        ĐẢNG ỦY PHƯỜNG BÌNH TIÊN
        Số 161-CV/ĐU
        Về việc xác minh thái độ chính trị
        phục vụ công tác kết nạp Đảng
        Ban Chỉ huy Công an phường Bình Tiên
        Để có cơ sở xem xét, phần thân
        """,
    )
    assert result.abstract.value == (
        "Về việc xác minh thái độ chính trị phục vụ công tác kết nạp Đảng"
    )


def test_record_68_cv_symbol_always_forces_cv_type(parser: DocumentParser) -> None:
    result = parser.parse(
        "Phần thân",
        source=DataSource.PADDLE_OCR,
        source_confidence=0.60,
        header_evidence_text=(
            "Số 143-CV/ĐU\n"
            "Về đăng ký lịch công tác và mời dự\n"
            "Hội nghị tổng kết thực hiện Nghị quyết 18-NQ/TW\n"
            "Kính gửi: Đồng chí A"
        ),
        existing_form=FormSnapshot(
            document_number="143",
            symbol="CV/ĐU",
            document_type="Khác",
            abstract="",
        ),
    )
    assert result.document_type.value == "Công văn"
    assert result.abstract.value == (
        "Về đăng ký lịch công tác và mời dự "
        "Hội nghị tổng kết thực hiện Nghị quyết 18-NQ/TW"
    )


@pytest.mark.parametrize(
    ("noisy", "confirmed"),
    [("9218", "218"), ("77224", "224"), ("3198", "198"), ("88234", "234")],
)
def test_leading_ocr_debris_is_removed_only_with_independent_suffix_evidence(
    noisy: str, confirmed: str
) -> None:
    details = build_canonical_document_header_details(
        [
            f"""ĐẢNG ỦY PHƯỜNG A
Số {noisy}-CV/ĐU
Về việc xác minh
Kính gửi:""",
            f"""ĐẢNG ỦY PHƯỜNG A
Số {confirmed}-CV/ĐU
Về việc xác minh
Kính gửi:""",
        ],
        symbol_hint="CV/ĐU",
        type_hint="Công văn",
        known_codes=("CV",),
    )
    assert details.number == confirmed
    assert details.number_support >= 2


def test_real_four_digit_body_reference_is_not_globally_truncated() -> None:
    details = build_canonical_document_header_details(
        [
            "ĐẢNG ỦY PHƯỜNG BÌNH TIÊN\n"
            "Số 219-CV/ĐU\nVề việc xác minh lý lịch\nKính gửi:\n"
            "Thực hiện Công văn số 9871-CV/BTCTU"
        ],
        symbol_hint="CV/ĐU",
        type_hint="Công văn",
        known_codes=("CV",),
    )
    assert details.number == "219"


def test_correct_title_candidate_beats_corrupted_name_candidate() -> None:
    details = build_canonical_document_header_details(
        [
            "Số 84-CV/ĐU\nVề việc xác minh lý lịch của người xin vào Đảng "
            "x3 với quần chúng Huỳnh Thị Home Nano\nKính gửi:",
            "Số 84-CV/ĐU\nVề việc xác minh lý lịch của người xin vào Đảng "
            "đối với quần chúng Huỳnh Thị Hồng Nhung\nKính gửi:",
        ],
        symbol_hint="CV/ĐU",
        type_hint="Công văn",
        known_codes=("CV",),
    )
    assert details.text == (
        "Số 84-CV/ĐU\n"
        "Về việc xác minh lý lịch của người xin vào Đảng đối với quần chúng Huỳnh Thị Hồng Nhung\n"
        "Kính gửi:"
    )

@pytest.mark.parametrize(
    ("header", "expected_number", "expected_abstract"),
    [
        (
            "Số 210-CV/ĐU\n"
            "Về việc trả lời xác minh lý lịch người xin vào đảng\n"
            "Đối với quần chúng Nguyễn Ngọc Hải\n"
            "Kính oxrr' Plano ít oy cử BOS: Đảng ủy cơ sở E25",
            "210",
            "Về việc trả lời xác minh lý lịch người xin vào đảng "
            "Đối với quần chúng Nguyễn Ngọc Hải",
        ),
        (
            "Số 179-CV/ĐU\n"
            "ve 3 mm Vô việc xác minh thái độ chính trị\n"
            "phục vu cong tac ket ngp Beng Ả - CT\n"
            "Kính gửi: Ban Chỉ huy Công an phường Bình Tiên",
            "179",
            "Về việc xác minh thái độ chính trị phục vụ công tác kết nạp Đảng",
        ),
        (
            "Số 161-CV/ĐU\n"
            "Về việc xác minh thái độ chính trị\n"
            "phục vụ công tác kết nạp Đảng\n"
            "Kính gửi: Đảng ủy phường Bình Phú",
            "161",
            "Về việc xác minh thái độ chính trị phục vụ công tác kết nạp Đảng",
        ),
        (
            "Số 148-CV/ĐU\n"
            "Về việc xác minh nơi cư trú đối với\n"
            "bản thân và gia đình viên chức II Ự nè VI c: a. Co\n"
            "Kính gửi: Ban Chỉ huy Công an phường Bình Tiên",
            "148",
            "Về việc xác minh nơi cư trú đối với bản thân và gia đình viên chức",
        ),
        (
            "Số 142-CV/ĐU\n"
            "Về việc thống kê danh sách cán bộ, công chức\n"
            "J văn đi Đảng ủy năm 2025 Kính gửi: Ban Tổ chức Thành ủy",
            "142",
            "Về việc thống kê danh sách cán bộ, công chức",
        ),
        (
            "Số 124-CV/ĐU\n"
            "Về việc xác minh thái độ chính trị Ả\n"
            "phục vụ công tác kết nạp Đảng\n"
            "Kính gửi: Đảng ủy phường Hoài Nhơn Bắc",
            "124",
            "Về việc xác minh thái độ chính trị phục vụ công tác kết nạp Đảng",
        ),
    ],
)
def test_all_reported_multiline_cv_titles_are_bounded_and_clean(
    parser: DocumentParser,
    header: str,
    expected_number: str,
    expected_abstract: str,
) -> None:
    result = parse_cv(parser, header)
    assert result.document_number.value == expected_number
    assert result.symbol.value == "CV/ĐU"
    assert result.document_type.value == "Công văn"
    assert result.abstract.value == expected_abstract
    assert not [issue for issue in result.issues if issue.severity.value == "error"]


@pytest.mark.parametrize(
    "raw_symbol",
    ["CV/U", "CV/DU", "CV/PDU", "CV/PĐU", "S-CV/ĐU", "V-CV/ĐU", "I-CV/ĐU"],
)
def test_all_reported_cv_symbol_noise_normalizes_only_the_own_header(raw_symbol: str) -> None:
    details = build_canonical_document_header_details(
        [
            "ĐẢNG BỘ THÀNH PHỐ HỒ CHÍ MINH\n"
            "ĐẢNG ỦY PHƯỜNG BÌNH TIÊN\n"
            f"Số 219-{raw_symbol}\n"
            "Về việc xác minh lý lịch đối với người xin vào Đảng\n"
            "Kính gửi: Ban Chỉ huy Công an phường"
        ],
        symbol_hint="CV/ĐU",
        type_hint="Công văn",
        known_codes=("CV",),
    )
    assert details.number == "219"
    assert details.symbol == "CV/ĐU"


def test_header_cache_from_older_cv_rules_is_never_reused(tmp_path: Path) -> None:
    import json

    from cataloging_tool.document.text_extractor import (
        CV_HEADER_CACHE_VERSION,
        DocumentTextExtractor,
    )

    artifact_dir = tmp_path / "record"
    artifact_dir.mkdir()
    meta = artifact_dir / "document-header-meta.json"
    meta.write_text(
        json.dumps(
            {
                "cache_version": "0.1.27.3-cong-van-v13",
                "number": "5218",
                "number_support": 9,
                "title_score": 0.99,
            }
        ),
        encoding="utf-8",
    )
    assert DocumentTextExtractor._load_document_header_meta(artifact_dir) == {}

    meta.write_text(
        json.dumps(
            {
                "cache_version": CV_HEADER_CACHE_VERSION,
                "number": "218",
                "number_support": 2,
                "title_score": 0.90,
            }
        ),
        encoding="utf-8",
    )
    loaded = DocumentTextExtractor._load_document_header_meta(artifact_dir)
    assert loaded["number"] == "218"


def test_dedicated_left_title_crop_exists_only_for_cong_van(tmp_path: Path) -> None:
    from PIL import Image

    from cataloging_tool.document.pdf_pipeline import PdfPipeline

    source = tmp_path / "viewer.png"
    Image.new("RGB", (1200, 1600), "white").save(source)
    pipeline = PdfPipeline(tmp_path / "rendered", render_dpi=300, minimum_text_length=80)

    generic = pipeline.prepare_document_header_crops(
        source, tmp_path / "generic", cong_van=False
    )
    cv = pipeline.prepare_document_header_crops(
        source, tmp_path / "cv", cong_van=True
    )

    assert "document-title-left.png" not in {path.name for path in generic}
    assert "document-title-left.png" in {path.name for path in cv}
