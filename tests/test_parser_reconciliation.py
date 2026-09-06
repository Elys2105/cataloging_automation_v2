from pathlib import Path

from cataloging_tool.document.parser import DocumentParser
from cataloging_tool.domain.enums import DataSource
from cataloging_tool.domain.models import FormSnapshot


def _parser() -> DocumentParser:
    root = Path(__file__).resolve().parents[1]
    return DocumentParser(root / "rules", "Tác giả", "Thường")


def test_strong_structure_is_not_capped_by_low_raw_ocr_confidence() -> None:
    result = _parser().parse(
        """Số 82-TB/ĐU
THÔNG BÁO
KẾT LUẬN CỦA BAN THƯỜNG VỤ ĐẢNG ỦY
Về công tác cán bộ năm 2025
-----
Thực hiện Kế hoạch số 1-KH/ĐU
""",
        source=DataSource.PADDLE_OCR,
        source_confidence=0.60,
    )
    assert result.abstract.value.startswith("KẾT LUẬN")
    assert result.overall_confidence >= 0.82


def test_clean_existing_form_rescues_weak_ocr_and_is_confirmed() -> None:
    existing = FormSnapshot(
        document_number="82",
        symbol="TB/ĐU",
        document_type="Thông báo",
        abstract=(
            "KẾT LUẬN CỦA BAN THƯỜNG VỤ ĐẢNG ỦY Về đánh giá kết quả "
            "thực hiện nhiệm vụ năm 2025 đối với đồng chí Trần Thị Thu Hà"
        ),
    )
    result = _parser().parse(
        """Số 82-TB/ĐU
THÔNG BÁO
KT LUN CA BAN THƯNG VU ĐNG Y
-----
""",
        source=DataSource.PADDLE_OCR,
        source_confidence=0.45,
        existing_form=existing,
    )
    assert result.abstract.value == existing.abstract
    assert "existing-form-confirmed" in result.abstract.source_text
    assert result.overall_confidence >= 0.82
