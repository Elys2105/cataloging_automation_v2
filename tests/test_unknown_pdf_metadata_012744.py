from __future__ import annotations

import asyncio
from pathlib import Path

from cataloging_tool.automation.pages import DocumentEditPage
from cataloging_tool.document.metadata import (
    canonical_author_from_text,
    extract_document_date,
    extract_security_level,
    extract_signer_name,
)
from cataloging_tool.document.parser import DocumentParser
from cataloging_tool.document.validator import DocumentValidator
from cataloging_tool.domain.enums import DataSource
from cataloging_tool.domain.models import FormSnapshot


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUTHOR = "ĐẢNG ỦY PHƯỜNG BÌNH TIÊN ĐẢNG BỘ THÀNH PHỐ HỒ CHÍ MINH"


def _parser() -> DocumentParser:
    return DocumentParser(ROOT / "rules", DEFAULT_AUTHOR, "Thường")


def _unknown_form(**values: str) -> FormSnapshot:
    base = dict(
        document_number="Không xác định",
        symbol="Ký hiệu văn bản",
        document_type="--Tên thể loại văn bản--",
        abstract="",
        document_date="",
        author="",
        signer_name="",
    )
    base.update(values)
    return FormSnapshot(**base)


def test_unknown_record_with_pdf_is_parsed_and_metadata_is_filled() -> None:
    header = """ĐẢNG BỘ THÀNH PHỐ HỒ CHÍ MINH
ĐẢNG ỦY PHƯỜNG BÌNH TIÊN
ĐẢNG CỘNG SẢN VIỆT NAM
Bình Tiên, ngày 03 tháng 12 năm 2025
Số 254-BC/ĐU
BÁO CÁO KIỂM ĐIỂM
TỰ ĐÁNH GIÁ, XẾP LOẠI CHẤT LƯỢNG
CỦA TẬP THỂ BAN THƯỜNG VỤ ĐẢNG ỦY
Năm 2025
-----
Thực hiện Kế hoạch số 13-KH/TU
A. NỘI DUNG KIỂM ĐIỂM"""
    signature = """Nơi nhận:
- Văn phòng Thành ủy
T/L BAN THƯỜNG VỤ
CHÁNH VĂN PHÒNG
Lê Thị Nguyệt Hương"""

    result = _parser().parse(
        header,
        source=DataSource.PADDLE_OCR,
        source_confidence=0.90,
        existing_form=_unknown_form(),
        header_evidence_text=header,
        signature_evidence_text=signature,
    )
    issues = DocumentValidator().validate(result)

    assert result.document_number.value == "254"
    assert result.symbol.value == "BC/ĐU"
    assert result.document_type.value == "Báo cáo"
    assert result.abstract.value == (
        "KIỂM ĐIỂM TỰ ĐÁNH GIÁ, XẾP LOẠI CHẤT LƯỢNG "
        "CỦA TẬP THỂ BAN THƯỜNG VỤ ĐẢNG ỦY Năm 2025"
    )
    assert result.document_date.value == "2025-12-03"
    assert result.signer_name.value == "Lê Thị Nguyệt Hương"
    assert result.author == DEFAULT_AUTHOR
    assert result.overall_confidence >= 0.82
    assert not issues


def test_parsed_document_exposes_per_field_confidence_and_sources() -> None:
    header = """ĐẢNG BỘ THÀNH PHỐ HỒ CHÍ MINH
ĐẢNG ỦY PHƯỜNG BÌNH TIÊN
ĐẢNG CỘNG SẢN VIỆT NAM
MẬT
Bình Tiên, ngày 03 tháng 12 năm 2025
Số 12-CV/ĐU
CÔNG VĂN
Về việc kiểm tra hồ sơ
Kính gửi: Ban Tổ chức"""
    result = _parser().parse(
        header,
        source=DataSource.PDF_TEXT,
        source_confidence=0.99,
        existing_form=_unknown_form(),
        header_evidence_text=header,
        author_evidence_text=header,
        signature_evidence_text="CHÁNH VĂN PHÒNG\nLê Thị Nguyệt Hương",
    )
    confidences = result.confidence_map()
    sources = result.source_map()
    assert set(confidences) == {
        "document_number", "symbol", "document_type", "abstract",
        "document_date", "author", "signer_name", "security_level",
    }
    assert confidences["author"] >= 0.96
    assert confidences["security_level"] >= 0.99
    assert sources["author"] == "focused-author-header"
    assert sources["security_level"].startswith("security-")


def test_date_must_come_from_top_national_heading_not_body_citation() -> None:
    header = """ĐẢNG CỘNG SẢN VIỆT NAM
Bình Tiên, ngày 04 tháng 12 năm 2025
Số 254-BC/ĐU"""
    raw = header + "\n" + ("Nội dung\n" * 50) + "Báo cáo ngày 01 tháng 01 năm 2024"
    assert extract_document_date(header, raw).value == "2025-12-04"
    assert extract_document_date("", "Nội dung\n" * 40 + "ngày 01 tháng 01 năm 2024").value == ""


def test_security_requires_explicit_header_label_not_red_stamp_or_body_phrase() -> None:
    assert extract_security_level("ĐẢNG CỘNG SẢN VIỆT NAM\nMẬT\nSố 12-CV/ĐU").value == "Mật"
    assert extract_security_level("ĐẢNG CỘNG SẢN VIỆT NAM\nTỐI MẬT\nSố 12-CV/ĐU").value == "Tối mật"
    assert extract_security_level("ĐẢNG CỘNG SẢN VIỆT NAM\nTUYỆT MẬT\nSố 12-CV/ĐU").value == "Tuyệt mật"
    assert extract_security_level(
        "ĐẢNG CỘNG SẢN VIỆT NAM\nSố 12-CV/ĐU",
        "Nội dung này viện dẫn một tài liệu mật ở phần thân.",
    ).value == ""


def test_parser_keeps_existing_security_when_pdf_has_no_explicit_marking() -> None:
    raw = """ĐẢNG ỦY PHƯỜNG BÌNH TIÊN
ĐẢNG CỘNG SẢN VIỆT NAM
Bình Tiên, ngày 03 tháng 12 năm 2025
Số 12-CV/ĐU
CÔNG VĂN
Về việc kiểm tra hồ sơ
Kính gửi: Ban Tổ chức"""
    result = _parser().parse(
        raw,
        source=DataSource.PDF_TEXT,
        source_confidence=0.99,
        existing_form=_unknown_form(security_level="Mật"),
        header_evidence_text=raw,
    )
    assert result.security_level == "Mật"
    assert result.security_source_text == "existing-form-confirmed:security"


def test_explicit_pdf_security_overrides_existing_form_security() -> None:
    raw = """ĐẢNG ỦY PHƯỜNG BÌNH TIÊN
ĐẢNG CỘNG SẢN VIỆT NAM
TỐI MẬT
Bình Tiên, ngày 03 tháng 12 năm 2025
Số 12-CV/ĐU
CÔNG VĂN
Về việc kiểm tra hồ sơ
Kính gửi: Ban Tổ chức"""
    result = _parser().parse(
        raw,
        source=DataSource.PDF_TEXT,
        source_confidence=0.99,
        existing_form=_unknown_form(security_level="Thường"),
        header_evidence_text=raw,
    )
    assert result.security_level == "Tối mật"
    assert result.security_source_text.startswith("security-")


def test_author_mapping_uses_only_pdf_issuer_evidence() -> None:
    assert canonical_author_from_text(
        "ĐẢNG ỦY PHƯỜNG BÌNH TIÊN\nVĂN PHÒNG",
        "",
        default_author="Mặc định",
    ) == "VĂN PHÒNG ĐẢNG ỦY PHƯỜNG BÌNH TIÊN"
    assert canonical_author_from_text(
        "ĐẢNG BỘ THÀNH PHỐ HỒ CHÍ MINH\nĐẢNG ỦY PHƯỜNG BÌNH TIÊN",
        "",
        default_author="Mặc định",
    ) == DEFAULT_AUTHOR
    assert canonical_author_from_text(
        "ỦY BAN NHÂN DÂN PHƯỜNG KHÁC",
        "",
        default_author="Mặc định",
    ) == ""


def test_signature_reader_uses_person_near_signature_role() -> None:
    text = """Nơi nhận
T/M BAN THƯỜNG VỤ
PHÓ BÍ THƯ THƯỜNG TRỰC
DƯƠNG QUANG TRÍ"""
    parsed = extract_signer_name(text)
    assert parsed.value == "Dương Quang Trí"
    assert parsed.confidence >= 0.90


def test_signer_reader_does_not_guess_person_without_signature_role() -> None:
    text = """Nơi nhận:
- Ban Tổ chức
Nguyễn Văn A
Trần Thị B"""
    parsed = extract_signer_name(text)
    assert parsed.value == ""


def test_existing_date_and_signer_are_never_overwritten() -> None:
    raw = """ĐẢNG CỘNG SẢN VIỆT NAM
Bình Tiên, ngày 03 tháng 12 năm 2025
Số 254-BC/ĐU
BÁO CÁO
Nội dung báo cáo
-----"""
    result = _parser().parse(
        raw,
        source=DataSource.PDF_TEXT,
        source_confidence=0.99,
        existing_form=_unknown_form(
            document_date="2025-12-02",
            signer_name="Nguyễn Văn A",
        ),
        header_evidence_text=raw,
        signature_evidence_text="CHÁNH VĂN PHÒNG\nLê Thị Nguyệt Hương",
    )
    assert result.document_date.value == "2025-12-02"
    assert result.signer_name.value == "Nguyễn Văn A"


class _DateContext:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.selected: dict[str, str] = {}
        self.month_ready = False
        self.day_ready = False

    async def evaluate(self, _script: str, payload: dict[str, str]) -> bool:
        action = payload["action"]
        component = payload["component"]
        wanted = payload["wanted"]
        self.calls.append((action, component, wanted))

        if action == "has-option":
            if component == "year":
                return True
            if component == "month":
                return self.month_ready
            if component == "day":
                return self.day_ready
        if action == "set":
            self.selected[component] = wanted
            if component == "year":
                self.month_ready = True
            elif component == "month":
                self.day_ready = True
            return True
        if action == "selected":
            return self.selected.get(component) == wanted
        return False


class _DatePage:
    def __init__(self, context: _DateContext) -> None:
        self.frames = [context]


class _DateEditPage(DocumentEditPage):
    async def _read_document_date(self) -> str:
        return "2025-12-03"


def test_date_field_writer_waits_for_dependent_dropdowns_in_order() -> None:
    context = _DateContext()
    edit = _DateEditPage(page=_DatePage(context), pdf_acquirer=None)
    asyncio.run(edit._fill_document_date("2025-12-03"))

    assert context.selected == {"year": "2025", "month": "12", "day": "03"}
    set_calls = [call for call in context.calls if call[0] == "set"]
    assert set_calls == [
        ("set", "year", "2025"),
        ("set", "month", "12"),
        ("set", "day", "03"),
    ]
    # Month is not even available until the year change has been dispatched;
    # day is not available until month has been dispatched.
    assert context.calls.index(("set", "year", "2025")) < context.calls.index(
        ("has-option", "month", "12")
    )
    assert context.calls.index(("set", "month", "12")) < context.calls.index(
        ("has-option", "day", "03")
    )

