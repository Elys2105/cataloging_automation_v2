from pathlib import Path

import pytest

from cataloging_tool.document.parser import DocumentParser
from cataloging_tool.document.validator import DocumentValidator
from cataloging_tool.domain.enums import DataSource


@pytest.fixture()
def parser() -> DocumentParser:
    root = Path(__file__).resolve().parents[1]
    return DocumentParser(root / "rules", "Tác giả", "Thường")


def test_ke_hoach(parser: DocumentParser) -> None:
    text = """
    ĐẢNG ỦY PHƯỜNG BÌNH TIÊN
    Số 27-KH/DU
    KẾ HOẠCH
    sắp xếp cán bộ, công chức, viên chức,
    người hoạt động không chuyên trách
    I. MỤC ĐÍCH, YÊU CẦU
    """
    result = parser.parse(text, source=DataSource.PADDLE_OCR, source_confidence=0.96)
    DocumentValidator().validate(result)
    assert result.document_number.value == "27"
    assert result.symbol.value == "KH/ĐU"
    assert result.document_type.value == "Kế hoạch"
    assert result.abstract.value.endswith("người hoạt động không chuyên trách")
    assert DocumentValidator.can_auto_submit(result)


def test_cong_van_stops_before_kinh_gui(parser: DocumentParser) -> None:
    text = """
    Số 237-CV/ĐU
    Về việc xác minh thái độ chính trị hiện nay
    phục vụ công tác cán bộ
    Kính gửi: Ban Tổ chức
    """
    result = parser.parse(text, source=DataSource.PDF_TEXT, source_confidence=0.98)
    DocumentValidator().validate(result)
    assert result.abstract.value == "Về việc xác minh thái độ chính trị hiện nay phục vụ công tác cán bộ"
    assert "Kính gửi" not in result.abstract.value


def test_parser_does_not_use_record_specific_override(parser: DocumentParser) -> None:
    text = """
    Số 34-KH/ĐU
    KẾ HOẠCH
    Triển khai thực hiện phong trào thi đua Dân vận khéo trên địa bàn phường Bình Tiên
    """
    result = parser.parse(text, source=DataSource.PADDLE_OCR, source_confidence=0.90)
    assert result.source == DataSource.PADDLE_OCR
    assert result.abstract.value == (
        "Triển khai thực hiện phong trào thi đua Dân vận khéo "
        "trên địa bàn phường Bình Tiên"
    )


def test_thong_bao_uses_only_text_below_heading_until_separator(parser: DocumentParser) -> None:
    text = """
    ĐẢNG ỦY PHƯỜNG BÌNH TIÊN
    Số 82-TB/ĐU
    THÔNG BÁO
    KẾT LUẬN CỦA BAN THƯỜNG VỤ ĐẢNG ỦY
    Về đánh giá kết quả thực hiện nhiệm vụ năm 2025 đối với đồng chí
    Trần Thị Thu Hà - Phó Bí thư Chi bộ, Phó Trưởng Ban Quản lý chợ Bình Tiên
    -----
    Thực hiện Kế hoạch số 13-KH/TU ngày 17 tháng 11 năm 2025
    1. Về ưu điểm, kết quả đạt được
    """
    result = parser.parse(text, source=DataSource.PDF_TEXT, source_confidence=0.99)
    assert result.document_number.value == "82"
    assert result.symbol.value == "TB/ĐU"
    assert result.document_type.value == "Thông báo"
    assert result.abstract.value == (
        "KẾT LUẬN CỦA BAN THƯỜNG VỤ ĐẢNG ỦY "
        "Về đánh giá kết quả thực hiện nhiệm vụ năm 2025 đối với đồng chí "
        "Trần Thị Thu Hà - Phó Bí thư Chi bộ, Phó Trưởng Ban Quản lý chợ Bình Tiên"
    )
    assert "Thực hiện Kế hoạch" not in result.abstract.value


def test_non_cong_van_rule_applies_to_quyet_dinh(parser: DocumentParser) -> None:
    text = """
    Số 12-QĐ/ĐU
    QUYẾT ĐỊNH
    Về việc thành lập Tổ công tác chuyển đổi số
    ----------------
    Căn cứ Điều lệ Đảng Cộng sản Việt Nam
    Điều 1. Thành lập Tổ công tác
    """
    result = parser.parse(text, source=DataSource.PDF_TEXT, source_confidence=0.99)
    assert result.document_type.value == "Quyết định"
    assert result.abstract.value == "Về việc thành lập Tổ công tác chuyển đổi số"


def test_cong_van_rule_uses_text_after_number_until_kinh_gui(parser: DocumentParser) -> None:
    text = """
    Số 237-CV/ĐU
    Về việc xác minh thái độ chính trị hiện nay
    phục vụ công tác cán bộ
    Kính gửi: Ban Chỉ huy Công an phường
    Đề có cơ sở xem xét, bố trí cán bộ
    """
    result = parser.parse(text, source=DataSource.PDF_TEXT, source_confidence=0.99)
    assert result.document_type.value == "Công văn"
    assert result.abstract.value == (
        "Về việc xác minh thái độ chính trị hiện nay phục vụ công tác cán bộ"
    )


def test_non_cong_van_body_opener_is_boundary_when_dash_is_missed(parser: DocumentParser) -> None:
    text = """
    Số 82-TB/ĐU
    THÔNG BÁO
    KẾT LUẬN CỦA BAN THƯỜNG VỤ ĐẢNG ỦY
    Về đánh giá kết quả thực hiện nhiệm vụ năm 2025 đối với đồng chí Trần Thị Thu Hà
    Thực hiện Kế hoạch số 13-KH/TU ngày 17 tháng 11 năm 2025
    1. Về ưu điểm, kết quả đạt được
    """
    result = parser.parse(text, source=DataSource.PDF_TEXT, source_confidence=0.99)
    assert result.abstract.value == (
        "KẾT LUẬN CỦA BAN THƯỜNG VỤ ĐẢNG ỦY "
        "Về đánh giá kết quả thực hiện nhiệm vụ năm 2025 đối với đồng chí Trần Thị Thu Hà"
    )
    assert result.abstract.confidence >= 0.90


def test_non_cong_van_without_separator_or_strong_boundary_is_not_auto_submit(parser: DocumentParser) -> None:
    text = """
    Số 15-BC/ĐU
    BÁO CÁO
    Kết quả công tác tháng 7 năm 2026
    Dòng tiếp tục không có ranh giới rõ ràng
    """
    result = parser.parse(text, source=DataSource.PDF_TEXT, source_confidence=0.99)
    DocumentValidator().validate(result)
    assert result.abstract.value.startswith("Kết quả công tác")
    assert result.abstract.confidence < 0.82
    assert not DocumentValidator.can_auto_submit(result)


def test_reported_tb_82_corruption_is_repaired_and_body_is_cut(parser: DocumentParser) -> None:
    text = """
    Số 82-TB/ĐU
    THÔNG BÁO
    KT LUN CA BAN THƯNG VU ĐNG Y
    Vè đánh giá kt quă the hin nhim v năm 2025 đi vói đng chí
    Trn Th Thu Hà - Phó Bí thưr Chi b, Phó Trưng Ban Qun lý ch Binh Tiên
    -----
    Thc hin Ké hoch s 13-KH/TU ngày 17 tháng 11 năm 2025 ca Ban Thưng v Thành y
    """
    result = parser.parse(text, source=DataSource.PADDLE_OCR, source_confidence=0.93)
    assert result.abstract.value == (
        "KẾT LUẬN CỦA BAN THƯỜNG VỤ ĐẢNG ỦY "
        "Về đánh giá kết quả thực hiện nhiệm vụ năm 2025 đối với đồng chí "
        "Trần Thị Thu Hà - Phó Bí thư Chi bộ, Phó Trưởng Ban Quản lý ch Bình Tiên"
    )
    assert "Thực hiện Kế hoạch" not in result.abstract.value


def test_landscape_daily_bao_cao_uses_title_block_after_number(parser: DocumentParser) -> None:
    text = """
    ĐẢNG ỦY PHƯỜNG BÌNH TIÊN
    Số 91-BC/ĐU
    BÁO CÁO NGÀY 11 THÁNG 9 NĂM 2025
    VỀ CÔNG TÁC NỘI CHÍNH, PHÒNG CHỐNG THAM NHŨNG, LÃNG PHÍ TIÊU CỰC VÀ CẢI CÁCH TƯ PHÁP
    Danh sách chuyên viên Văn phòng phụ trách công tác nội chính
    STT Tên công việc
    """
    result = parser.parse(
        text,
        source=DataSource.PADDLE_OCR,
        source_confidence=0.96,
        is_landscape=True,
    )
    assert result.document_number.value == "91"
    assert result.symbol.value == "BC/ĐU"
    assert result.document_type.value == "Báo cáo"
    assert result.abstract.value == (
        "BÁO CÁO NGÀY 11 THÁNG 9 NĂM 2025 "
        "VỀ CÔNG TÁC NỘI CHÍNH, PHÒNG CHỐNG THAM NHŨNG, "
        "LÃNG PHÍ TIÊU CỰC VÀ CẢI CÁCH TƯ PHÁP"
    )
    assert "Danh sách" not in result.abstract.value


def test_normal_bao_cao_keeps_existing_heading_rule(parser: DocumentParser) -> None:
    text = """
    Số 90-BC/ĐU
    BÁO CÁO
    Về tình hình kinh tế, xã hội, công tác xây dựng Đảng, hệ thống chính trị
    (Ngày 11 tháng 9 năm 2025)
    -----
    Thực hiện Công văn số 12-CV/TU
    """
    result = parser.parse(
        text,
        source=DataSource.PDF_TEXT,
        source_confidence=0.99,
        is_landscape=False,
    )
    assert result.document_type.value == "Báo cáo"
    assert result.abstract.value == (
        "Về tình hình kinh tế, xã hội, công tác xây dựng Đảng, "
        "hệ thống chính trị (Ngày 11 tháng 9 năm 2025)"
    )
    assert not result.abstract.value.startswith("BÁO CÁO")


def test_landscape_report_uses_existing_bc_hint_when_number_line_ocr_is_missing(
    parser: DocumentParser,
) -> None:
    from cataloging_tool.domain.models import FormSnapshot

    # This reproduces the real failure: the tiny landscape number line was not
    # present in generic OCR, but the website form already contained 91 / BC/ĐU.
    text = """
    ĐẢNG ỦY PHƯỜNG BÌNH TIÊN
    BÁO CÁO NGÀY 11 THÁNG 9 NĂM 2025
    VỀ CÔNG TÁC NỘI CHÍNH, PHÒNG CHỐNG THAM NHŨNG, LÃNG PHÍ TIÊU CỰC VÀ CẢI CÁCH TƯ PHÁP
    Danh sách chuyên viên Văn phòng phụ trách công tác nội chính
    STT Tên công việc
    """
    result = parser.parse(
        text,
        source=DataSource.PADDLE_OCR,
        source_confidence=0.88,
        existing_form=FormSnapshot(
            document_number="91",
            symbol="BC/ĐU",
            document_type="Khác",
            abstract="",
        ),
        is_landscape=True,
    )
    DocumentValidator().validate(result)

    assert result.document_number.value == "91"
    assert result.symbol.value == "BC/ĐU"
    assert result.document_type.value == "Báo cáo"
    assert result.abstract.value.startswith("BÁO CÁO NGÀY 11 THÁNG 9 NĂM 2025")
    assert "Danh sách" not in result.abstract.value
    assert DocumentValidator.can_auto_submit(result)


def test_landscape_report_title_can_be_recovered_globally_after_generic_ocr(
    parser: DocumentParser,
) -> None:
    from cataloging_tool.domain.models import FormSnapshot

    # The dedicated crop OCR is appended after the generic OCR result, so the
    # report title may no longer be adjacent to the number line.
    text = """
    Số 91-BC/ĐU
    A. TÌNH HÌNH, KẾT QUẢ
    STT Tên công việc
    BÁO CÁO NGÀY 11 THÁNG 9 NĂM 2025
    VỀ CÔNG TÁC NỘI CHÍNH, PHÒNG CHỐNG THAM NHŨNG, LÃNG PHÍ TIÊU CỰC VÀ CẢI CÁCH TƯ PHÁP
    Danh sách chuyên viên Văn phòng phụ trách công tác nội chính
    """
    result = parser.parse(
        text,
        source=DataSource.PADDLE_OCR,
        source_confidence=0.90,
        existing_form=FormSnapshot(document_number="91", symbol="BC/ĐU", document_type="Khác"),
        is_landscape=True,
    )

    assert result.document_type.value == "Báo cáo"
    assert result.abstract.value == (
        "BÁO CÁO NGÀY 11 THÁNG 9 NĂM 2025 "
        "VỀ CÔNG TÁC NỘI CHÍNH, PHÒNG CHỐNG THAM NHŨNG, "
        "LÃNG PHÍ TIÊU CỰC VÀ CẢI CÁCH TƯ PHÁP"
    )


def test_daily_report_stops_before_ocr_damaged_body_and_repairs_fixed_subject(
    parser: DocumentParser,
) -> None:
    from cataloging_tool.domain.models import FormSnapshot

    text = """
    Số 116-BC/ĐU
    BÁO CÁO NGÀY 25 THÁNG 9 NĂM 2025
    V CÔNG TC NỘI CHÍNH, PHÒNG CHỐNG THAM NHNG, LNG PHÍ TIU CC VÀ CẢI CÁCH TU PHÁP
    Thc hin Công văn s 279-CV/BNCTU ngày 12 tháng 8 năm 2025 của Ban Nội chính
    A. TÌNH HÌNH, KẾT QUẢ
    """
    result = parser.parse(
        text,
        source=DataSource.PADDLE_OCR,
        source_confidence=0.72,
        existing_form=FormSnapshot(
            document_number="116",
            symbol="BC/ĐU",
            document_type="Báo cáo",
            abstract=(
                "BÁO CÁO NGÀY 25 THÁNG 9 NĂM 2025 V CÔNG TC NỘI CHÍNH, "
                "PHÒNG CHỐNG THAM NHNG, LNG PHÍ TIU CC VÀ CẢI CÁCH TU PHÁP "
                "Thc hin Công văn s 279-CV/BNCTU ngày 12 tháng 8 năm 2025"
            ),
        ),
        is_landscape=True,
    )

    assert result.abstract.value == (
        "BÁO CÁO NGÀY 25 THÁNG 9 NĂM 2025 "
        "VỀ CÔNG TÁC NỘI CHÍNH, PHÒNG CHỐNG THAM NHŨNG, "
        "LÃNG PHÍ TIÊU CỰC VÀ CẢI CÁCH TƯ PHÁP"
    )
    assert "Thực hiện" not in result.abstract.value
    assert "279-CV" not in result.abstract.value


def test_daily_report_uses_dedicated_title_hint_when_generic_ocr_is_empty(
    parser: DocumentParser,
) -> None:
    from cataloging_tool.domain.models import FormSnapshot

    result = parser.parse(
        "A. TÌNH HÌNH, KẾT QUẢ\nSTT Tên công việc",
        source=DataSource.PADDLE_OCR,
        source_confidence=0.60,
        existing_form=FormSnapshot(
            document_number="119",
            symbol="BC/ĐU",
            document_type="Khác",
        ),
        is_landscape=True,
        special_report_title=(
            "BÁO CÁO NGÀY 26 THÁNG 9 NĂM 2025 "
            "VỀ CÔNG TÁC NỘI CHÍNH, PHÒNG CHỐNG THAM NHŨNG, "
            "LÃNG PHÍ TIÊU CỰC VÀ CẢI CÁCH TƯ PHÁP"
        ),
    )
    DocumentValidator().validate(result)

    assert result.document_type.value == "Báo cáo"
    assert result.abstract.value.startswith("BÁO CÁO NGÀY 26 THÁNG 9 NĂM 2025")
    assert result.abstract.confidence == pytest.approx(0.99)
    assert DocumentValidator.can_auto_submit(result)


def test_to_trinh_confidence_uses_kinh_gui_or_clean_title_boundary(parser: DocumentParser) -> None:
    from cataloging_tool.domain.models import FormSnapshot

    text = """
    Số 17-TTr/ĐU
    TỜ TRÌNH
    v báo cáo cho thôi là di biu chính thc d di hi di biu Đng b phường Bình Tiên
    ln th I, nhim k 2025 - 2030 và ch đnh di biu di hi di biu Đng b phường Bình Tiên
    ln th I, nhim k 2025 - 2030
    Kính gửi: Ban Chấp hành Đảng bộ phường
    """
    result = parser.parse(
        text,
        source=DataSource.PADDLE_OCR,
        source_confidence=0.60,
        existing_form=FormSnapshot(
            document_number="17",
            symbol="TTR/ĐU",
            document_type="Tờ trình",
            abstract=(
                "v báo cáo cho thôi là di biu chính thc d di hi di biu Đng b phường "
                "Bình Tiên ln th I, nhim k 2025 - 2030 và ch đnh di biu di hi di biu "
                "Đng b phường Bình Tiên ln th I, nhim k 2025 - 2030"
            ),
        ),
    )
    DocumentValidator().validate(result)
    assert result.abstract.value == (
        "Về báo cáo cho thôi là đại biểu chính thức dự Đại hội đại biểu "
        "Đảng bộ phường Bình Tiên lần thứ I, nhiệm kỳ 2025 - 2030 và "
        "chỉ định đại biểu dự Đại hội đại biểu Đảng bộ phường Bình Tiên "
        "lần thứ I, nhiệm kỳ 2025 - 2030"
    )
    assert result.overall_confidence >= 0.82
    assert DocumentValidator.can_auto_submit(result)


def test_to_trinh_repairs_chi_dinh_title(parser: DocumentParser) -> None:
    from cataloging_tool.domain.models import FormSnapshot

    text = """
    Số 14-TTr/ĐU
    TỜ TRÌNH
    V ch đnh đi biu d hi di biu Đng b phưng Bình Tiên ln th I, nhim k 2025 - 2030
    -----
    Kính gửi: Ban Chấp hành Đảng bộ phường
    """
    result = parser.parse(
        text,
        source=DataSource.PADDLE_OCR,
        source_confidence=0.60,
        existing_form=FormSnapshot(
            document_number="14",
            symbol="TTR/ĐU",
            document_type="Tờ trình",
            abstract="V ch đnh đi biu d hi di biu Đng b phưng Bình Tiên ln th I, nhim k 2025 - 2030",
        ),
    )
    DocumentValidator().validate(result)
    assert result.abstract.value == (
        "Về chỉ định đại biểu dự Đại hội đại biểu Đảng bộ phường Bình Tiên "
        "lần thứ I, nhiệm kỳ 2025 - 2030"
    )
    assert DocumentValidator.can_auto_submit(result)


def test_to_trinh_removes_heading_junk_and_does_not_take_body(parser: DocumentParser) -> None:
    text = """
    Số 03-TTr/ĐU
    TỜ TRÌNH à | Về thành lập các cơ quan tham mưu, giúp việc Đảng ủy, cơ quan Ủy ban
    Kiểm tra Đảng ủy, cơ quan Ủy ban Mặt trận Tổ quốc, các phòng chuyên môn thuộc
    Ủy ban nhân dân, các Ban Hội đồng nhân dân phường
    Kính gửi: Ban Chấp hành Đảng bộ phường
    Căn cứ Điều lệ Đảng và Quy định thi hành Điều lệ Đảng
    """
    result = parser.parse(text, source=DataSource.PADDLE_OCR, source_confidence=0.60)
    DocumentValidator().validate(result)
    assert result.abstract.value == (
        "Về thành lập các cơ quan tham mưu, giúp việc Đảng ủy, cơ quan "
        "Ủy ban Kiểm tra Đảng ủy, cơ quan Ủy ban Mặt trận Tổ quốc, các "
        "phòng chuyên môn thuộc Ủy ban nhân dân, các Ban Hội đồng nhân dân phường"
    )
    assert not result.abstract.value.startswith("TỜ TRÌNH")
    assert "Kính gửi" not in result.abstract.value
    assert "Căn cứ" not in result.abstract.value
    assert DocumentValidator.can_auto_submit(result)


def test_to_trinh_clean_title_without_visible_dash_is_above_submit_threshold(parser: DocumentParser) -> None:
    text = """
    Số 20-TTr/ĐU
    TỜ TRÌNH
    Về xin chủ trương tổ chức hội nghị tổng kết công tác năm 2025
    """
    result = parser.parse(text, source=DataSource.PADDLE_OCR, source_confidence=0.60)
    DocumentValidator().validate(result)
    assert result.abstract.value == "Về xin chủ trương tổ chức hội nghị tổng kết công tác năm 2025"
    assert result.abstract.confidence >= 0.90
    assert result.overall_confidence >= 0.82
    assert DocumentValidator.can_auto_submit(result)


def test_thong_bao_repairs_recurring_ocr_damage_and_inline_body_boundary(
    parser: DocumentParser,
) -> None:
    from cataloging_tool.domain.models import FormSnapshot

    text = """
    Số 78-TB/ĐU
    THÔNG BÁO
    KT LUN CỦA BAN THƯỜNG VỤ ĐNG Y
    V đánh giá kt quả the hin nhim v năm 2025 đối với đồng chí
    V Thị Cẩm Tú - Phó Chánh Vãn phòng H đồng nhân dân và y ban nhân dân Phường
    Thc hin Kế hoạch số 13-KH/TU ngày 17 tháng 11 năm 2025
    1. Về ưu điểm, kết quả đạt được
    """
    result = parser.parse(
        text,
        source=DataSource.PADDLE_OCR,
        source_confidence=0.60,
        existing_form=FormSnapshot(
            document_number="78",
            symbol="TB/ĐU",
            document_type="Thông báo",
            abstract=(
                "KT LUN CỦA BAN THƯỜNG VỤ ĐNG Y V đánh giá kt quả "
                "the hin nhim v năm 2025 đối với đồng chí V Thị Cẩm Tú - "
                "Phó Chánh Vãn phòng H đồng nhân dân và y ban nhân dân Phường "
                "Thc hin Kế hoạch số 13-KH/TU ngày 17 tháng 11 năm 2025"
            ),
        ),
    )
    issues = DocumentValidator().validate(result)

    assert result.abstract.value == (
        "KẾT LUẬN CỦA BAN THƯỜNG VỤ ĐẢNG ỦY "
        "Về đánh giá kết quả thực hiện nhiệm vụ năm 2025 đối với đồng chí "
        "V Thị Cẩm Tú - Phó Chánh Văn phòng Hội đồng nhân dân "
        "và Ủy ban nhân dân Phường"
    )
    assert "Thực hiện Kế hoạch" not in result.abstract.value
    assert result.overall_confidence >= 0.82
    assert not any(issue.code == "CORRUPTED_VIETNAMESE" for issue in issues)
    assert DocumentValidator.can_auto_submit(result)


def test_bounded_thong_bao_title_is_not_overridden_by_long_existing_body(
    parser: DocumentParser,
) -> None:
    from cataloging_tool.domain.models import FormSnapshot

    text = """
    Số 82-TB/ĐU
    THÔNG BÁO
    KẾT LUẬN CỦA BAN THƯỜNG VỤ ĐẢNG ỦY
    Về đánh giá kết quả thực hiện nhiệm vụ năm 2025 đối với đồng chí
    Trần Thị Thu Hà - Phó Bí thư Chi bộ, Phó Trưởng Ban Quản lý chợ Bình Tiên
    Thc hin Kế hoạch số 13-KH/TU ngày 17 tháng 11 năm 2025
    """
    existing = (
        "KẾT LUẬN CỦA BAN THƯỜNG VỤ ĐẢNG ỦY Về đánh giá kết quả thực hiện "
        "nhiệm vụ năm 2025 đối với đồng chí Trần Thị Thu Hà - Phó Bí thư Chi bộ, "
        "Phó Trưởng Ban Quản lý chợ Bình Tiên Thực hiện Kế hoạch số 13-KH/TU "
        "ngày 17 tháng 11 năm 2025 của Ban Thường vụ Thành ủy"
    )
    result = parser.parse(
        text,
        source=DataSource.PADDLE_OCR,
        source_confidence=0.60,
        existing_form=FormSnapshot(
            document_number="82",
            symbol="TB/ĐU",
            document_type="Thông báo",
            abstract=existing,
        ),
    )
    DocumentValidator().validate(result)

    assert result.abstract.value == (
        "KẾT LUẬN CỦA BAN THƯỜNG VỤ ĐẢNG ỦY "
        "Về đánh giá kết quả thực hiện nhiệm vụ năm 2025 đối với đồng chí "
        "Trần Thị Thu Hà - Phó Bí thư Chi bộ, Phó Trưởng Ban Quản lý chợ Bình Tiên"
    )
    assert "Thực hiện Kế hoạch" not in result.abstract.value
    assert result.abstract.confidence >= 0.90
    assert DocumentValidator.can_auto_submit(result)


def test_thong_bao_body_boundary_is_cut_when_merged_on_same_ocr_line(
    parser: DocumentParser,
) -> None:
    text = """
    Số 82-TB/ĐU
    THÔNG BÁO
    KẾT LUẬN CỦA BAN THƯỜNG VỤ ĐẢNG ỦY
    Về đánh giá kết quả thực hiện nhiệm vụ năm 2025 đối với đồng chí Trần Thị Thu Hà - Phó Bí thư Chi bộ Thực hiện Kế hoạch số 13-KH/TU ngày 17 tháng 11 năm 2025
    """
    result = parser.parse(
        text,
        source=DataSource.PADDLE_OCR,
        source_confidence=0.60,
    )
    DocumentValidator().validate(result)

    assert result.abstract.value.endswith("Phó Bí thư Chi bộ")
    assert "Thực hiện Kế hoạch" not in result.abstract.value
    assert result.overall_confidence >= 0.82
    assert DocumentValidator.can_auto_submit(result)
