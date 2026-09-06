from __future__ import annotations

from pathlib import Path

from cataloging_tool.document.parser import DocumentParser
from cataloging_tool.document.validator import DocumentValidator
from cataloging_tool.domain.enums import DataSource


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = DocumentParser(
        root / "rules",
        author="ĐẢNG ỦY PHƯỜNG BÌNH TIÊN ĐẢNG BỘ THÀNH PHỐ HỒ CHÍ MINH",
        security_level="Thường",
    )
    text = """
    ĐẢNG ỦY PHƯỜNG BÌNH TIÊN
    Số 27-KH/DU
    KẾ HOẠCH
    sắp xếp cán bộ, công chức, viên chức,
    người hoạt động không chuyên trách
    I. MỤC ĐÍCH, YÊU CẦU
    """
    result = parser.parse(text, source=DataSource.PADDLE_OCR, source_confidence=0.96)
    DocumentValidator(0.82).validate(result)
    assert result.document_number.value == "27"
    assert result.symbol.value == "KH/ĐU"
    assert result.document_type.value == "Kế hoạch"
    assert "người hoạt động không chuyên trách" in result.abstract.value
    assert DocumentValidator.can_auto_submit(result)

    cong_van = """
    Số 237-CV/ĐU
    Về việc xác minh thái độ chính trị hiện nay
    phục vụ công tác cán bộ
    Kính gửi: Ban Tổ chức
    """
    cv = parser.parse(cong_van, source=DataSource.PDF_TEXT, source_confidence=0.98)
    DocumentValidator(0.82).validate(cv)
    assert cv.document_type.value == "Công văn"
    assert cv.abstract.value == "Về việc xác minh thái độ chính trị hiện nay phục vụ công tác cán bộ"
    assert DocumentValidator.can_auto_submit(cv)
    print("Parser and validator smoke test: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
