from cataloging_tool.document.ocr import vietnamese_text_quality


def test_vietnamese_quality_prefers_correct_diacritics() -> None:
    correct = (
        "THÔNG BÁO KẾT LUẬN CỦA BAN THƯỜNG VỤ ĐẢNG ỦY "
        "Về đánh giá kết quả thực hiện nhiệm vụ năm 2025"
    )
    broken = (
        "THONG BAO KT LUN CA BAN THƯNG VU ĐNG Y "
        "Ve danh gia kt qua thc hin nhim v nam 2025"
    )
    assert vietnamese_text_quality(correct) > vietnamese_text_quality(broken)


def test_hybrid_merge_prefers_accented_vietnamese_line() -> None:
    from cataloging_tool.document.ocr import merge_ocr_results
    from cataloging_tool.domain.models import OcrLine, OcrResult

    bad = OcrResult(
        raw_text="KT LUN CA BAN THƯNG VU ĐNG Y",
        confidence=0.97,
        lines=[
            OcrLine(
                "KT LUN CA BAN THƯNG VU ĐNG Y",
                0.97,
                [[10, 20], [600, 20], [600, 60], [10, 60]],
            )
        ],
        engine="tesseract",
    )
    good = OcrResult(
        raw_text="KẾT LUẬN CỦA BAN THƯỜNG VỤ ĐẢNG ỦY",
        confidence=0.88,
        lines=[
            OcrLine(
                "KẾT LUẬN CỦA BAN THƯỜNG VỤ ĐẢNG ỦY",
                0.88,
                [[12, 22], [598, 22], [598, 61], [12, 61]],
            )
        ],
        engine="paddle",
    )

    merged = merge_ocr_results([bad, good])
    assert merged is not None
    assert merged.raw_text == "KẾT LUẬN CỦA BAN THƯỜNG VỤ ĐẢNG ỦY"
