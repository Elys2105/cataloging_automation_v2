from __future__ import annotations

from pathlib import Path

import pytest

from cataloging_tool.document.document_header import (
    best_number_symbol,
    clean_cong_van_title,
    extract_cong_van_title,
    normalize_header_symbol,
)
from cataloging_tool.document.parser import DocumentParser
from cataloging_tool.document.validator import DocumentValidator
from cataloging_tool.domain.enums import DataSource
from cataloging_tool.domain.models import FormSnapshot


@pytest.fixture()
def parser() -> DocumentParser:
    root = Path(__file__).resolve().parents[1]
    return DocumentParser(root / "rules", "Tác giả", "Thường")


def _parse(
    parser: DocumentParser,
    body: str,
    header: str,
    *,
    form: FormSnapshot | None = None,
):
    return parser.parse(
        body,
        source=DataSource.PADDLE_OCR,
        source_confidence=0.60,
        existing_form=form,
        header_evidence_text=header,
    )


def test_340_abstract_is_bounded_before_body(parser: DocumentParser) -> None:
    header = """
    ĐẢNG BỘ THÀNH PHỐ HỒ CHÍ MINH
    ĐẢNG ỦY PHƯỜNG BÌNH TIÊN
    Số 340-CV/ĐU
    Về việc xác minh thái độ chính trị
    phục vụ công tác kết nạp Đảng
    Kính gửi: Đảng ủy xã Cần Đước, tỉnh Tây Ninh.
    """
    stale = FormSnapshot(
        document_number="340",
        symbol="CV/ĐU",
        document_type="Công văn",
        abstract=(
            "Về việc xác minh thái độ chính trị 2025 phục vụ công tác kết nạp Đảng "
            "Để có cơ sở xem xét, kết nạp xét, đa - giáo viên của Trường Trung học"
        ),
    )
    result = _parse(parser, header + "\nĐể có cơ sở xem xét, kết nạp vào Đảng", header, form=stale)
    assert result.document_number.value == "340"
    assert result.symbol.value == "CV/ĐU"
    assert result.document_type.value == "Công văn"
    assert result.abstract.value == (
        "Về việc xác minh thái độ chính trị phục vụ công tác kết nạp Đảng"
    )
    assert result.abstract.confidence >= 0.97


def test_338_header_beats_clean_cited_body_instrument(parser: DocumentParser) -> None:
    header = """
    ĐẢNG ỦY PHƯỜNG BÌNH TIÊN
    Số 338-CV/ĐU
    Về hỗ trợ xác minh thông tin phục vụ công tác
    kết luận tiêu chuẩn chính trị của cán bộ, đảng viên và Người xin vào Đảng
    Kính gửi: Ban Chỉ huy Công an phường.
    """
    body = """
    Thực hiện Công văn số 8034-CV/BTCTU ngày 08 tháng 4 năm 2024
    và Công văn số 9871-CV/BTCTU ngày 31 tháng 3 năm 2025.
    """
    result = _parse(
        parser,
        body,
        header,
        form=FormSnapshot(
            document_number="9871",
            symbol="CV/BTCTU",
            document_type="Công văn",
            abstract="Về hỗ trợ xác minh thông tin phục vụ công tác kết luận tiêu chuẩn chính trị",
        ),
    )
    assert result.document_number.value == "338"
    assert result.symbol.value == "CV/ĐU"
    assert result.abstract.value.endswith("và Người xin vào Đảng")


def test_handwritten_digit_confusions_are_limited_to_number_token() -> None:
    candidate = best_number_symbol(
        "Số 34O-CV/ĐU\nVề việc xác minh thái độ chính trị\nKính gửi:",
        expected_code="CV",
        known_codes=("CV", "BC", "CT"),
    )
    assert candidate is not None
    assert candidate.number == "340"
    assert candidate.symbol == "CV/ĐU"


def test_spurious_one_letter_prefix_is_removed_but_office_suffix_is_preserved() -> None:
    assert normalize_header_symbol("S-CV/ĐU", known_codes=("CV", "BC")) == "CV/ĐU"
    assert normalize_header_symbol("V-CV/ĐU", known_codes=("CV", "BC")) == "CV/ĐU"
    assert normalize_header_symbol("CV/UBKTTU", known_codes=("CV", "BC")) == "CV/UBKTTU"
    assert normalize_header_symbol("CV/BTCTU", known_codes=("CV", "BC")) == "CV/BTCTU"


def test_330_wrong_chi_thi_form_is_replaced_by_own_cv_header(parser: DocumentParser) -> None:
    header = """
    ĐẢNG ỦY THÀNH PHỐ HỒ CHÍ MINH
    ĐẢNG ỦY PHƯỜNG BÌNH TIÊN
    Số 330-CV/ĐU
    về xin ý kiến dự thảo Kế hoạch lãnh đạo cuộc bầu cử
    đại biểu Quốc hội khóa XVI và cuộc bầu cử đại biểu
    Hội đồng nhân dân các cấp nhiệm kỳ 2026 - 2031
    Kính gửi: Các đồng chí Ủy viên Ban Thường vụ Đảng ủy.
    """
    body = "Thực hiện Chỉ thị số 47-CT/TU ngày 09 tháng 6 năm 2025"
    result = _parse(
        parser,
        body,
        header,
        form=FormSnapshot(
            document_number="47",
            symbol="CT/TW",
            document_type="Chỉ thị",
            abstract="DQQD V/I về xin ý kiến dự thảo Kế hoạch lãnh đạo cuộc bầu cử",
        ),
    )
    assert result.document_number.value == "330"
    assert result.symbol.value == "CV/ĐU"
    assert result.document_type.value == "Công văn"
    assert result.abstract.value.startswith("về xin ý kiến dự thảo Kế hoạch")
    assert "DQQD" not in result.abstract.value


def test_328_cv_u_is_repaired_only_with_matching_issuer(parser: DocumentParser) -> None:
    header = """
    ĐẢNG BỘ THÀNH PHỐ HỒ CHÍ MINH
    ĐẢNG ỦY PHƯỜNG BÌNH TIÊN
    Số 328-CV/U
    Về việc trả lời xác minh lý lịch của người xin vào Đảng
    quần chúng Nguyễn Thị Thùy Linh
    Kính gửi: Chi bộ Bệnh viện Bình Phú.
    """
    result = _parse(
        parser,
        "Đảng ủy phường có nhận được Công văn số 48-CV/ĐU",
        header,
        form=FormSnapshot(document_number="48", symbol="CV/U", document_type="Công văn"),
    )
    assert result.document_number.value == "328"
    assert result.symbol.value == "CV/ĐU"
    assert result.abstract.value.endswith("quần chúng Nguyễn Thị Thùy Linh")


def test_320_document_type_is_inferred_from_header_not_cited_program(parser: DocumentParser) -> None:
    header = """
    Số 320-CV/ĐU
    về lãnh đạo thực hiện chỉ tiêu giảm hộ cận nghèo
    từ nay đến hết năm 2025
    Kính gửi: Đảng ủy Ủy ban nhân dân.
    """
    body = "Thực hiện Chương trình Giảm nghèo bền vững và Chương trình hành động số 02-CTr/ĐU"
    result = _parse(
        parser,
        body,
        header,
        form=FormSnapshot(
            document_number="02",
            symbol="CTR/ĐU",
            document_type="Chương trình",
            abstract="về lãnh đạo thực hiện chỉ tiêu giảm hộ cận nghèo từ nay đến hết năm 2025",
        ),
    )
    assert result.document_number.value == "320"
    assert result.symbol.value == "CV/ĐU"
    assert result.document_type.value == "Công văn"
    assert result.abstract.value == "về lãnh đạo thực hiện chỉ tiêu giảm hộ cận nghèo từ nay đến hết năm 2025"


def test_319_stops_at_kinh_gui_and_never_appends_body(parser: DocumentParser) -> None:
    header = """
    Số 319-CV/ĐU
    Về gửi tài liệu và xin ý kiến
    Kính gửi: Các đồng chí Ủy viên Ban Thường vụ Đảng ủy.
    """
    body = """
    Thực hiện Quy chế làm việc số 01-QC/ĐU ngày 01 tháng 7 năm 2025
    Thường trực Hội đồng nhân dân phường đã xây dựng Tờ trình số 26/TTr-HĐND
    """
    result = _parse(
        parser,
        body,
        header,
        form=FormSnapshot(
            document_number="319",
            symbol="CV/ĐU",
            document_type="Công văn",
            abstract="Về gửi tài liệu và xin ý kiến Kính gửi: Các đồng chí ỦY VIÊN BAN THƯỜNG VỤ ĐẢNG ỦY Thực hiện Quy chế làm việc số 01-QC/ĐU",
        ),
    )
    assert result.abstract.value == "Về gửi tài liệu và xin ý kiến"
    assert "Kính gửi" not in result.abstract.value
    assert "Quy chế" not in result.abstract.value


@pytest.mark.parametrize(
    ("number", "title"),
    [
        ("310", "Về việc xác nhận thực trạng hồ sơ đảng viên"),
        ("305", "về đánh giá, xếp loại chất lượng theo hiệu quả công việc quý III/2025 đối với đồng chí Bí thư Đảng ủy, Chủ tịch Hội đồng nhân dân phường Bình Tiên"),
        ("296", "Về việc lấy ý kiến nơi cư trú đối với đảng viên dự bị"),
        ("274", "Về việc xác minh thái độ chính trị phục vụ công tác kết nạp Đảng"),
        ("270", "Về việc xác nhận thực trạng hồ sơ đảng viên"),
        ("269", "Về việc tăng cường thực hiện nghiêm các quy định về công tác chuyển sinh hoạt đảng; xét giảm, miễn công tác, sinh hoạt đảng; xóa tên đảng viên, đảng viên xin ra khỏi Đảng"),
    ],
)
def test_visible_cv_title_is_not_reported_missing_or_low_confidence(
    parser: DocumentParser, number: str, title: str
) -> None:
    header = f"Số {number}-CV/ĐU\n{title}\nKính gửi: Đơn vị liên quan"
    result = _parse(
        parser,
        "Nội dung phần thân không được dùng làm trích yếu",
        header,
        form=FormSnapshot(document_number=number, symbol="CV/ĐU", document_type="Khác"),
    )
    issues = DocumentValidator().validate(result)
    assert result.abstract.value == title
    assert result.overall_confidence >= 0.82
    assert not any(issue.field == "abstract" for issue in issues)
    assert not any(issue.code == "LOW_CONFIDENCE" for issue in issues)


def test_299_multiline_title_is_kept_complete(parser: DocumentParser) -> None:
    header = """
    Số 299-CV/ĐU
    Về việc tham gia lớp bồi dưỡng
    nhận thức về Đảng khóa 6
    Kính gửi: Ban Giám đốc Trung tâm Chính trị phường Cầu Ông Lãnh.
    """
    result = _parse(parser, "Căn cứ Thông báo số 08-TB/TTCT", header)
    assert result.abstract.value == "Về việc tham gia lớp bồi dưỡng nhận thức về Đảng khóa 6"


def test_268_long_multiline_title_is_kept_until_urgency_and_recipient(parser: DocumentParser) -> None:
    header = """
    Số 268-CV/ĐU
    về nghiên cứu bổ sung kết quả thực hiện; các khó khăn,
    vướng mắc và kiến nghị, giải pháp vào báo cáo việc triển khai
    thực hiện Kế hoạch số 249-KH/UBKTTW
    KHẨN
    Kính gửi: Đảng ủy Ủy ban nhân dân.
    """
    result = _parse(parser, "Thực hiện Quyết định số 632-QĐ/TU", header)
    assert result.abstract.value == (
        "về nghiên cứu bổ sung kết quả thực hiện; các khó khăn, vướng mắc và kiến nghị, "
        "giải pháp vào báo cáo việc triển khai thực hiện Kế hoạch số 249-KH/UBKTTW"
    )


def test_noise_before_title_is_removed_without_deleting_real_words() -> None:
    value = clean_cong_van_title(
        "ND 000 V/L Về việc trả lời xác minh lý lịch của người xin vào Đảng Kính gửi: Chi bộ"
    )
    assert value == "Về việc trả lời xác minh lý lịch của người xin vào Đảng"


def test_extract_title_requires_top_title_and_ignores_body_number() -> None:
    raw = """
    Số 321-CV/ĐU
    Về việc trả lời xác minh lý lịch của người xin vào Đảng
    quần chúng Lê Thị Hồng Trinh
    Kính gửi: Ban Xây dựng Đảng phường An Lạc.
    Thực hiện Công văn số 144-CV/BXĐĐ ngày 01 tháng 11 năm 2025
    """
    title = extract_cong_van_title(raw, known_codes=("CV", "BC", "CT"))
    assert title.number == "321"
    assert title.symbol == "CV/ĐU"
    assert title.value.endswith("quần chúng Lê Thị Hồng Trinh")
    assert "144-CV/BXĐĐ" not in title.value


def test_single_handwritten_number_is_not_truncated_without_evidence() -> None:
    candidate = best_number_symbol(
        "Số 56234-CV/ĐU\nVề việc xác minh thái độ chính trị hiện nay\nKính gửi:",
        expected_code="CV",
        known_codes=("CV", "BC"),
    )
    assert candidate is not None
    assert candidate.number == "56234"


def test_cv_title_truncates_visible_ocr_garbage_suffix() -> None:
    assert clean_cong_van_title(
        "Về việc xác minh thái độ chính trị hiện nay nu mm | ˆ E"
    ) == "Về việc xác minh thái độ chính trị hiện nay"
    assert clean_cong_van_title(
        "Về việc xác minh thái độ chính trị phục vụ công tác cán bộ mmm"
    ) == "Về việc xác minh thái độ chính trị phục vụ công tác cán bộ"


def test_canonical_header_prefers_complete_clean_title_over_short_corrupt_candidate() -> None:
    from cataloging_tool.document.document_header import build_canonical_document_header

    canonical = build_canonical_document_header(
        [
            "Số 234-CV/ĐU\nVE vide văn minh\nKính gửi:",
            "Số 234-CV/ĐU\nVề việc xác minh thái độ chính trị hiện nay\nphục vụ công tác cán bộ\nKính gửi: Ban Chỉ huy Công an phường.",
        ],
        symbol_hint="CV/ĐU",
        type_hint="Công văn",
        known_codes=("CV", "BC"),
    )
    assert "Số 234-CV/ĐU" in canonical
    assert "Về việc xác minh thái độ chính trị hiện nay phục vụ công tác cán bộ" in canonical
    assert "vide văn minh" not in canonical


def test_handwritten_number_consensus_beats_single_confident_wrong_reading() -> None:
    from cataloging_tool.document.document_header import build_canonical_document_header

    canonical = build_canonical_document_header(
        [
            "Số 7-CV/ĐU\\nVề việc góp ý dự thảo Báo cáo phục vụ giám sát việc triển khai\\nKính gửi:",
            "Số 7-CV/ĐU",
            "Số 7-CV/ĐU",
            "Số 71-CV/ĐU",
        ],
        symbol_hint="CV/ĐU",
        type_hint="Công văn",
        known_codes=("CV", "BC"),
    )
    assert canonical.startswith("Số 7-CV/ĐU")


def test_handwritten_234_prefix_debris_loses_to_clean_consensus() -> None:
    from cataloging_tool.document.document_header import build_canonical_document_header

    canonical = build_canonical_document_header(
        [
            "Số 56234-CV/ĐU\\nVề việc xác minh thái độ chính trị hiện nay\\nKính gửi:",
            "Số 234-CV/ĐU",
            "Số 234-CV/ĐU",
        ],
        symbol_hint="CV/ĐU",
        type_hint="Công văn",
        known_codes=("CV",),
    )
    assert canonical.startswith("Số 234-CV/ĐU")

def test_cv_159_uses_only_italic_title_block_and_stops_before_recipient(parser: DocumentParser) -> None:
    text = """
    ĐẢNG BỘ THÀNH PHỐ HỒ CHÍ MINH
    ĐẢNG ỦY PHƯỜNG BÌNH TIÊN
    Số 231-CV/ĐU
    Về việc xác minh thái độ chính trị hiện nay
    phục vụ công tác cán bộ
    Kính gửi: Ban Chỉ huy Công an phường.
    Để có cơ sở xem xét, bố trí cán bộ đối với đồng chí Phạm Sỹ Việt.
    """
    result = parser.parse(text, source=DataSource.PADDLE_OCR, source_confidence=0.95, header_evidence_text=text)
    assert result.document_type.value == "Công văn"
    assert result.abstract.value == "Về việc xác minh thái độ chính trị hiện nay phục vụ công tác cán bộ"
    assert "Kính gửi" not in result.abstract.value
    assert "Để có cơ sở" not in result.abstract.value
