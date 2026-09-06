from __future__ import annotations

from cataloging_tool.document.metadata import canonical_author_from_text


def _author(header: str, raw: str = "") -> str:
    return canonical_author_from_text(
        header,
        raw,
        default_author="Mặc định",
    )


def test_quan_uy_parent_is_moved_after_ward_committee() -> None:
    assert _author(
        "QUẬN UỶ QUẬN 6\nĐẢNG UỶ PHƯỜNG 1"
    ) == "ĐẢNG ỦY PHƯỜNG 1 QUẬN ỦY QUẬN 6"


def test_dang_bo_quan_parent_is_moved_after_ward_committee() -> None:
    assert _author(
        "ĐẢNG BỘ QUẬN 8\nĐẢNG ỦY PHƯỜNG 7"
    ) == "ĐẢNG ỦY PHƯỜNG 7 ĐẢNG BỘ QUẬN 8"


def test_dynamic_names_are_read_from_header_not_fixed_to_one_ward() -> None:
    assert _author(
        "QUẬN ỦY QUẬN GÒ VẤP\nĐẢNG ỦY PHƯỜNG HẠNH THÔNG"
    ) == "ĐẢNG ỦY PHƯỜNG HẠNH THÔNG QUẬN ỦY QUẬN GÒ VẤP"


def test_merged_ocr_header_line_is_supported() -> None:
    assert _author(
        "QUẬN UỶ QUẬN 3 ĐẢNG UỶ PHƯỜNG 4"
    ) == "ĐẢNG ỦY PHƯỜNG 4 QUẬN ỦY QUẬN 3"


def test_office_author_uses_dynamic_ward_but_not_parent_prefix() -> None:
    assert _author(
        "QUẬN ỦY QUẬN 6\nĐẢNG ỦY PHƯỜNG 1\nVĂN PHÒNG"
    ) == "VĂN PHÒNG ĐẢNG ỦY PHƯỜNG 1"


def test_dedicated_header_wins_over_unrelated_raw_body_mentions() -> None:
    assert _author(
        "ĐẢNG BỘ THÀNH PHỐ HỒ CHÍ MINH\nĐẢNG ỦY PHƯỜNG BÌNH TIÊN",
        "Trong nội dung có nhắc QUẬN ỦY QUẬN 6 ĐẢNG ỦY PHƯỜNG 1",
    ) == "ĐẢNG ỦY PHƯỜNG BÌNH TIÊN ĐẢNG BỘ THÀNH PHỐ HỒ CHÍ MINH"


def test_unrelated_agency_never_uses_configured_default_author() -> None:
    assert _author(
        "ỦY BAN NHÂN DÂN PHƯỜNG 1"
    ) == ""


def test_city_parent_is_dynamic_and_not_fixed_to_binh_tien() -> None:
    assert _author(
        "ĐẢNG BỘ THÀNH PHỐ HỒ CHÍ MINH\nĐẢNG ỦY PHƯỜNG AN ĐÔNG"
    ) == "ĐẢNG ỦY PHƯỜNG AN ĐÔNG ĐẢNG BỘ THÀNH PHỐ HỒ CHÍ MINH"
