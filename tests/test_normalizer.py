from pathlib import Path

from cataloging_tool.document.normalizer import VietnameseNormalizer, fold_vietnamese


def test_fold_vietnamese() -> None:
    assert fold_vietnamese("ĐẢNG ỦY Phường Bình Tiên") == "dang uy phuong binh tien"


def test_symbol_normalization() -> None:
    root = Path(__file__).resolve().parents[1]
    normalizer = VietnameseNormalizer(root / "rules" / "vietnamese_normalization.tsv")
    assert normalizer.normalize_symbol(" kh / du ") == "KH/ĐU"
    assert normalizer.normalize_symbol("NQ/TƯ") == "NQ/TW"


def test_repairs_accentless_and_pang_uy_title() -> None:
    root = Path(__file__).resolve().parents[1]
    normalizer = VietnameseNormalizer(root / "rules" / "vietnamese_normalization.tsv")
    assert (
        normalizer.normalize_text("KET LUAN CUA BAN THUONG VU PANG UY")
        == "KẾT LUẬN CỦA BAN THƯỜNG VỤ ĐẢNG ỦY"
    )


def test_repairs_partial_committee_phrase_without_touching_following_text() -> None:
    root = Path(__file__).resolve().parents[1]
    normalizer = VietnameseNormalizer(root / "rules" / "vietnamese_normalization.tsv")
    result = normalizer.normalize_text(
        "BAN THUONG VU PANG UY Về đánh giá kết quả thực hiện nhiệm vụ"
    )
    assert result == (
        "BAN THƯỜNG VỤ ĐẢNG ỦY Về đánh giá kết quả thực hiện nhiệm vụ"
    )


def test_normalizes_fixed_thong_bao_heading_with_missing_vowels(tmp_path) -> None:
    from cataloging_tool.document.normalizer import VietnameseNormalizer

    normalizer = VietnameseNormalizer()
    assert normalizer.normalize_text("KT LUN CỦA BAN THƯỜNG VỤ ĐNG Y") == (
        "KẾT LUẬN CỦA BAN THƯỜNG VỤ ĐẢNG ỦY"
    )
