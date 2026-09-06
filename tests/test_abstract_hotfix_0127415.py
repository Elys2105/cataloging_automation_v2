from __future__ import annotations

from pathlib import Path

import pytest

from cataloging_tool.document.document_header import (
    build_canonical_document_header_details,
    clean_cong_van_title,
    cong_van_title_is_safe_extension,
    cong_van_title_looks_truncated,
)
from cataloging_tool.document.parser import DocumentParser
from cataloging_tool.domain.enums import DataSource
from cataloging_tool.domain.models import FormSnapshot


@pytest.fixture()
def parser() -> DocumentParser:
    root = Path(__file__).resolve().parents[1]
    return DocumentParser(root / "rules", "Tác giả", "Thường")


def _parse_cv(parser: DocumentParser, header: str, *, existing_abstract: str = ""):
    return parser.parse(
        "Nhằm để đảm bảo quy trình, phần thân không phải trích yếu.",
        source=DataSource.PADDLE_OCR,
        source_confidence=0.60,
        header_evidence_text=header,
        existing_form=FormSnapshot(
            document_number="",
            symbol="CV/ĐU",
            document_type="Công văn",
            abstract=existing_abstract,
        ),
    )


@pytest.mark.parametrize(
    ("number", "title_lines", "expected"),
    [
        (
            "153",
            [
                "V/v nhắc các chi bộ thực hiện quy trình kiểm tra, giám sát,",
                "đảm bảo theo Quyết định số 1480-QĐ/TU",
                "ngày 25/7/2023 của Ban Thường vụ Thành ủy",
            ],
            "V/v nhắc các chi bộ thực hiện quy trình kiểm tra, giám sát, đảm bảo theo Quyết định số 1480-QĐ/TU ngày 25/7/2023 của Ban Thường vụ Thành ủy",
        ),
        (
            "147",
            [
                "Về thống nhất xét duyệt đi nước ngoài đối với",
                "Đảng viên Lê Võ Ngọc Thảo",
            ],
            "Về thống nhất xét duyệt đi nước ngoài đối với Đảng viên Lê Võ Ngọc Thảo",
        ),
        (
            "145",
            [
                "Về thống nhất xét duyệt đi nước ngoài đối với",
                "Đảng viên Nguyễn Thị Xuân Hồng",
            ],
            "Về thống nhất xét duyệt đi nước ngoài đối với Đảng viên Nguyễn Thị Xuân Hồng",
        ),
        (
            "135",
            [
                "Về triển khai thực hiện Kế hoạch hành",
                "động về phát triển khoa học, công",
                "nghệ, đổi mới sáng tạo, chuyển đổi số",
                "và phong trào “Bình dân học vụ số”",
            ],
            "Về triển khai thực hiện Kế hoạch hành động về phát triển khoa học, công nghệ, đổi mới sáng tạo, chuyển đổi số và phong trào \"Bình dân học vụ số\"",
        ),
        (
            "126",
            [
                "V/v viếng tang đồng chí Bùi Đức Quân,",
                "đảng viên Huy hiệu 30 năm tuổi Đảng",
            ],
            "V/v viếng tang đồng chí Bùi Đức Quân, đảng viên Huy hiệu 30 năm tuổi Đảng",
        ),
        (
            "125",
            [
                "về báo cáo kết quả thực hiện",
                "Quy định 590 (được sửa đổi, bổ sung theo",
                "Quyết định số 231-QĐ/QU ngày 20/01/2022",
                "của Ban Thường vụ Quận ủy) quý II năm 2025",
            ],
            "về báo cáo kết quả thực hiện Quy định 590 (được sửa đổi, bổ sung theo Quyết định số 231-QĐ/QU ngày 20/01/2022 của Ban Thường vụ Quận ủy) quý II năm 2025",
        ),
        (
            "119",
            [
                "về việc đề xuất khen thưởng tập thể, cá nhân có",
                "thành tích trong thực hiện Chỉ thị số 05-CT/TW của",
                "Bộ chính trị về đẩy mạnh học tập và làm theo",
                "tư tưởng, đạo đức, phong cách Hồ Chí Minh",
            ],
            "Về việc đề xuất khen thưởng tập thể, cá nhân có thành tích trong thực hiện Chỉ thị số 05-CT/TW của Bộ chính trị về đẩy mạnh học tập và làm theo tư tưởng, đạo đức, phong cách Hồ Chí Minh",
        ),
        (
            "74",
            [
                "V/v Hỗ trợ xác minh thông tin liên quan đến",
                "đảng viên Phùng Văn Phát – Đảng viên chi bộ",
                "khu phố 6",
            ],
            "V/v Hỗ trợ xác minh thông tin liên quan đến đảng viên Phùng Văn Phát – Đảng viên chi bộ khu phố 6",
        ),
        (
            "105",
            [
                "Về tăng cường lãnh đạo, chỉ đạo tổ chức các",
                "hoạt động, tuyên truyền, nắm tình hình, đảm bảo",
                "an ninh chính trị, trật tự an toàn xã hội trước,",
                "trong và sau Lễ kỷ niệm 50 năm Ngày Giải phóng",
                "miền Nam, thống nhất đất nước",
            ],
            "Về tăng cường lãnh đạo, chỉ đạo tổ chức các hoạt động, tuyên truyền, nắm tình hình, đảm bảo an ninh chính trị, trật tự an toàn xã hội trước, trong và sau Lễ kỷ niệm 50 năm Ngày Giải phóng miền Nam, thống nhất đất nước",
        ),
        (
            "103",
            [
                "V/v xin ý kiến nhận xét của cấp ủy (chi bộ)",
                "nơi cư trú đối với đồng chí Liên Chí Quang",
            ],
            "V/v xin ý kiến nhận xét của cấp ủy (chi bộ) nơi cư trú đối với đồng chí Liên Chí Quang",
        ),
        (
            "101",
            [
                "V/v mời tham gia Ban giám khảo chấm điểm",
                "hội thi trang trí tập san",
            ],
            "V/v mời tham gia Ban giám khảo chấm điểm hội thi trang trí tập san",
        ),
        (
            "88",
            [
                "Về việc đề xuất, giới thiệu tập thể, cá nhân tiêu",
                "biểu, điển hình trong tổng kết 10 năm thực hiện",
                "Chỉ thị số 05-CT/TW của Bộ Chính trị về đẩy",
                "mạnh học tập và làm theo tư tưởng, đạo đức,",
                "phong cách Hồ Chí Minh",
            ],
            "Về việc đề xuất, giới thiệu tập thể, cá nhân tiêu biểu, điển hình trong tổng kết 10 năm thực hiện Chỉ thị số 05-CT/TW của Bộ Chính trị về đẩy mạnh học tập và làm theo tư tưởng, đạo đức, phong cách Hồ Chí Minh",
        ),
        (
            "86",
            [
                "về việc báo cáo kết quả xét lại đánh giá",
                "kết quả công tác của đồng chí Bí thư",
                "Đảng ủy phường Quý I/2025",
            ],
            "Về việc báo cáo kết quả xét lại đánh giá kết quả công tác của đồng chí Bí thư Đảng ủy phường Quý I/2025",
        ),
        (
            "85",
            [
                "Về việc tăng cường lãnh đạo công tác quản lý, xét",
                "duyệt cho đảng viên đi nước ngoài",
            ],
            "Về việc tăng cường lãnh đạo công tác quản lý, xét duyệt cho đảng viên đi nước ngoài",
        ),
    ],
)
def test_all_user_supplied_cv_abstract_shapes_are_complete(
    parser: DocumentParser,
    number: str,
    title_lines: list[str],
    expected: str,
) -> None:
    header = "\n".join(
        [
            "ĐẢNG ỦY PHƯỜNG 1",
            f"Số {number}-CV/ĐU",
            *title_lines,
            "Kính gửi: Đơn vị nhận văn bản",
            "Nhằm để đảm bảo quy trình, đây là phần thân văn bản.",
        ]
    )
    result = _parse_cv(parser, header)
    assert result.abstract.value == expected


def test_date_after_cited_instrument_is_not_cut_from_title(parser: DocumentParser) -> None:
    header = """
    Số 153-CV/ĐU
    V/v nhắc các chi bộ thực hiện quy trình kiểm tra, giám sát,
    đảm bảo theo Quyết định số 1480-QĐ/TU
    ngày 25/7/2023 của Ban Thường vụ Thành ủy
    Kính gửi: Các chi bộ trực thuộc
    """
    result = _parse_cv(parser, header)
    assert "ngày 25/7/2023 của Ban Thường vụ Thành ủy" in result.abstract.value
    assert "2023" in clean_cong_van_title(result.abstract.value)


def test_canonical_title_prefers_complete_extension_over_clean_truncated_prefix() -> None:
    truncated = (
        "Số 135-CV/ĐU\n"
        "Về triển khai\n"
        "Kính gửi:"
    )
    complete = (
        "Số 135-CV/ĐU\n"
        "Về triển khai thực hiện Kế hoạch hành động về phát triển khoa học, công nghệ, "
        "đổi mới sáng tạo, chuyển đổi số và phong trào Bình dân học vụ số\n"
        "Kính gửi:"
    )
    details = build_canonical_document_header_details(
        [truncated, complete],
        symbol_hint="CV/ĐU",
        type_hint="Công văn",
        known_codes=("CV",),
    )
    assert "Kế hoạch hành động" in details.text
    assert "Bình dân học vụ số" in details.text


def test_manual_corrected_existing_abstract_is_not_shortened_again(parser: DocumentParser) -> None:
    corrected = (
        "V/v xin ý kiến nhận xét của cấp ủy (chi bộ) "
        "nơi cư trú đối với đồng chí Liên Chí Quang"
    )
    header = (
        "Số 103-CV/ĐU\n"
        "V/v xin ý kiến nhận xét của cấp ủy (chi bộ)\n"
        "Kính gửi: Đảng ủy Phường 8"
    )
    result = parser.parse(
        "Để có cơ sở xem xét, đây là phần thân.",
        source=DataSource.PADDLE_OCR,
        source_confidence=0.60,
        header_evidence_text=header,
        existing_form=FormSnapshot(
            document_number="103",
            symbol="CV/ĐU",
            document_type="Công văn",
            abstract=corrected,
        ),
    )
    assert result.abstract.value == corrected
    assert "abstract-complete-extension" in result.abstract.source_text


def test_existing_body_leak_is_not_treated_as_a_safe_extension() -> None:
    short = "V/v mời tham gia Ban giám khảo chấm điểm hội thi trang trí tập san"
    leaked = short + " Nhằm thực hiện Kế hoạch số 04-KH/ĐU, Đảng ủy phường đề nghị các đơn vị triển khai"
    assert not cong_van_title_is_safe_extension(leaked, short)


def test_truncation_detector_flags_recurring_short_forms() -> None:
    assert cong_van_title_looks_truncated("Về triển khai")
    assert cong_van_title_looks_truncated("Về việc tăng cường")
    assert cong_van_title_looks_truncated(
        "V/v nhắc các chi bộ thực hiện quy trình kiểm tra, giám sát,"
    )
    assert not cong_van_title_looks_truncated(
        "V/v mời tham gia Ban giám khảo chấm điểm hội thi trang trí tập san"
    )


def test_body_after_title_is_still_excluded_when_kinh_gui_is_missed(parser: DocumentParser) -> None:
    header = """
    Số 101-CV/ĐU
    V/v mời tham gia Ban giám khảo chấm điểm
    hội thi trang trí tập san
    Thực hiện Kế hoạch số 04-KH/ĐU ngày 16/01/2025 về tổ chức Hội thi
    """
    result = _parse_cv(parser, header)
    assert result.abstract.value == (
        "V/v mời tham gia Ban giám khảo chấm điểm hội thi trang trí tập san"
    )
    assert "Thực hiện Kế hoạch" not in result.abstract.value
