import json
from pathlib import Path

from cataloging_tool.document.parser import DocumentParser
from cataloging_tool.document.report_title import repair_report_title
from cataloging_tool.document.validator import DocumentValidator
from cataloging_tool.domain.enums import DataSource
from cataloging_tool.domain.models import FormSnapshot


def _parser() -> DocumentParser:
    root = Path(__file__).resolve().parents[1]
    return DocumentParser(root / "rules", "Tác giả", "Thường")


def test_trien_khai_thuc_hien_is_kept_inside_report_title() -> None:
    value = (
        "việc triển khai thực hiện Kế hoạch số 249-KH/UBKTTW "
        "ngày 24 tháng 7 năm 2025 của Ủy ban Kiểm tra Trung ương "
        "(Kỳ báo cáo: Ngày 12/12/2025)"
    )
    assert repair_report_title(value) == value


def test_real_weak_ocr_tail_confirms_clean_existing_report_title() -> None:
    existing = FormSnapshot(
        document_number="270",
        symbol="BC/ĐU",
        document_type="Báo cáo",
        abstract=(
            "việc triển khai thực hiện Kế hoạch số 249-KH/UBKTTW "
            "ngày 24 tháng 7 năm 2025 của Ủy ban Kiểm tra Trung ương "
            "(Kỳ báo cáo: Ngày 12/12/2025)"
        ),
        document_date="2025-12-12",
        author="ĐẢNG BỘ THÀNH PHỐ HỒ CHÍ MINH ĐẢNG ỦY PHƯỜNG BÌNH TIÊN",
        security_level="--Chọn độ mật--",
        signer_name="Nguyễn Hữu Vĩnh",
    )
    raw_text = (
        "DANG BỘ THÀNH PHÓ HỎ CHIMINH ~~ PANG CỘNG SAN VIỆT NAM\n"
        "ĐẢNG ỦY PHƯỜNG BÌNH TIỀN Bình Tiên, ngày 12 tháng 12 năm 2025\n"
        "*\nSố 270-BC/ĐU\nBÁO CÁO\n"
        "việc trién khai thực hiện Kế hoạch sô 249-KH/UBKTTW\n"
        "ngày 24 tháng 7 năm 2025 của Ủy ban Kiểm tra Trung ương\n"
        "(K báo cáo: Ngày 12/12/2025)\n-_-__\n"
        "Thực hiện Công văn số 04-CV/TCT ngày 17 tháng 11 năm 2025 của Tô Công tác\n"
        "sô 13 theo Quyêt định sô 632-QĐ/TU về việc dé nghị Đảng ủy phường, xã được giám\n"
        "sát báo cáo bô sung: BAN THƯỜNG VỤ ĐẢNG ỦY phường Bình Tiên báo cáo như sau:\n"
        "ngày 24 tháng 7 năm 2025 của Uy ban Kiểm tra Trung ương "
        "(Kv bao cáo: Ngày 12/12/2025) ah | Na I Ưen l\n"
        "PANG BỘ THANHPHOHO CHIMINH ~~ DANG CONG SAN VIỆT NAM\n"
        "PANG UY PHUONG BINH TIEN Bình Tiên, ngày 12 tháng 12 năm 2025\n"
        "*\nSố 270-BC/ĐU\nBÁO CÁO\n"
        "việc triên khai thực hiện Kế hoạch sô 249-KH/UBKTTW\n"
        "ngày 24 tháng 7 năm 2025 của Ủy ban Kiểm tra Trung ương\n"
        "(K báo cáo: Ngày 12/12/2025)\n"
        "Thực hiện Công văn số 04-CV/TCT ngày 17 tháng 11 năm 2025"
    )
    result = _parser().parse(
        raw_text,
        source=DataSource.TESSERACT_OCR,
        source_confidence=0.0,
        existing_form=existing,
    )
    DocumentValidator(0.82).validate(result)

    assert result.abstract.value == existing.abstract
    assert "existing-form-confirmed:abstract" in result.abstract.source_text
    assert result.overall_confidence >= 0.82
    assert DocumentValidator.can_auto_submit(result)


def test_actual_body_sentence_is_still_cut_after_a_normal_title() -> None:
    value = (
        "về kết quả công tác phát triển đảng viên năm 2025 "
        "Thực hiện Công văn số 384-CV/BTCTU ngày 27 tháng 11 năm 2025"
    )
    assert repair_report_title(value) == "về kết quả công tác phát triển đảng viên năm 2025"
