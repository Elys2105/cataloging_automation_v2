from __future__ import annotations

from cataloging_tool.document.metadata import canonical_author_from_text


CITY_DEFAULT = "ĐẢNG ỦY PHƯỜNG BÌNH TIÊN ĐẢNG BỘ THÀNH PHỐ HỒ CHÍ MINH"


def _author(header: str, raw: str = "") -> str:
    return canonical_author_from_text(
        header,
        raw,
        default_author=CITY_DEFAULT,
    )


def test_dang_bo_quan_pair_is_exact_and_replaces_city_default() -> None:
    assert _author(
        "ĐẢNG BỘ QUẬN 6\nĐẢNG ỦY PHƯỜNG 1"
    ) == "ĐẢNG ỦY PHƯỜNG 1 ĐẢNG BỘ QUẬN 6"


def test_quan_uy_quan_pair_is_exact_and_replaces_city_default() -> None:
    assert _author(
        "QUẬN UỶ QUẬN 6\nĐẢNG UỶ PHƯỜNG 1"
    ) == "ĐẢNG ỦY PHƯỜNG 1 QUẬN ỦY QUẬN 6"


def test_title_words_merged_after_numbered_ward_are_not_appended() -> None:
    assert _author(
        "ĐẢNG ỦY PHƯỜNG 1 XÂY DỰNG NGHỊ QUẬN ỦY QUẬN 6"
    ) == "ĐẢNG ỦY PHƯỜNG 1 QUẬN ỦY QUẬN 6"


def test_document_title_on_same_line_is_a_hard_boundary() -> None:
    assert _author(
        "QUẬN ỦY QUẬN 6 ĐẢNG ỦY PHƯỜNG 1 NGHỊ QUYẾT "
        "Lãnh đạo tăng cường thực hiện chỉ thị"
    ) == "ĐẢNG ỦY PHƯỜNG 1 QUẬN ỦY QUẬN 6"


def test_named_units_are_dynamic_and_not_hard_coded() -> None:
    assert _author(
        "QUẬN ỦY QUẬN BÌNH TÂN\nĐẢNG ỦY PHƯỜNG AN LẠC"
    ) == "ĐẢNG ỦY PHƯỜNG AN LẠC QUẬN ỦY QUẬN BÌNH TÂN"


def test_district_context_never_falls_back_to_unrelated_city_author() -> None:
    assert _author(
        "QUẬN ỦY QUẬN 6\nĐẢNG ỦY PHƯỜNG"
    ) == ""


def test_city_level_binh_tien_rule_still_works() -> None:
    assert _author(
        "ĐẢNG BỘ THÀNH PHỐ HỒ CHÍ MINH\nĐẢNG ỦY PHƯỜNG BÌNH TIÊN"
    ) == CITY_DEFAULT


def test_office_rule_still_works_without_district_pair() -> None:
    assert _author(
        "ĐẢNG ỦY PHƯỜNG BÌNH TIÊN\nVĂN PHÒNG"
    ) == "VĂN PHÒNG ĐẢNG ỦY PHƯỜNG BÌNH TIÊN"
