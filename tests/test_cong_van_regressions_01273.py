from __future__ import annotations

from pathlib import Path

import pytest

from cataloging_tool.document.cong_van_sequence import (
    CongVanNumberEvidence,
    CongVanNumberSequence,
)
from cataloging_tool.document.document_header import (
    build_canonical_document_header_details,
    clean_cong_van_title,
    cong_van_title_is_clean,
    normalize_header_symbol,
)
from cataloging_tool.document.parser import DocumentParser
from cataloging_tool.document.validator import DocumentValidator
from cataloging_tool.domain.enums import DataSource
from cataloging_tool.domain.models import FormSnapshot, ParsedDocument, ParsedField


@pytest.fixture()
def parser() -> DocumentParser:
    root = Path(__file__).resolve().parents[1]
    return DocumentParser(root / "rules", "Tác giả", "Thường")


def _cv(number: str, *, source: DataSource = DataSource.PADDLE_OCR) -> ParsedDocument:
    return ParsedDocument(
        document_number=ParsedField(number, 0.99, "ocr"),
        symbol=ParsedField("CV/ĐU", 0.99, "header"),
        document_type=ParsedField("Công văn", 0.99, "header"),
        abstract=ParsedField(
            "Về việc xác minh thái độ chính trị phục vụ công tác cán bộ",
            0.99,
            "header",
        ),
        source=source,
        overall_confidence=0.95,
    )


def test_number_consensus_beats_one_confident_wrong_handwritten_reading() -> None:
    details = build_canonical_document_header_details(
        [
            "Số 227-CV/ĐU\nVE vide văn minh\nKính gửi:",
            "Số 237-CV/ĐU\nVề việc xác minh thái độ chính trị hiện nay\n"
            "phục vụ công tác cán bộ\nKính gửi:",
            "Số 237-CV/PDU\nVề việc xác minh thái độ chính trị hiện nay "
            "phục vụ công tác cán bộ\nKính gửi:",
        ],
        symbol_hint="CV/ĐU",
        type_hint="Công văn",
        known_codes=("CV", "BC"),
    )
    assert details.number == "237"
    assert details.symbol == "CV/ĐU"
    assert details.number_support == 2
    assert details.text.startswith("Số 237-CV/ĐU")
    assert "VE vide" not in details.text


def test_leading_handwriting_prefix_is_merged_only_with_independent_suffix_reading() -> None:
    details = build_canonical_document_header_details(
        [
            "Số 5224-CV/ĐU\nVề việc xác minh lý lịch người xin vào Đảng\nKính gửi:",
            "Số 224-CV/ĐU\nVề việc xác minh lý lịch người xin vào Đảng\nKính gửi:",
        ],
        symbol_hint="CV/ĐU",
        type_hint="Công văn",
        known_codes=("CV",),
    )
    assert details.number == "224"
    assert details.number_support == 2


def test_cv_symbol_repairs_short_pdu_noise_but_preserves_real_office_suffix() -> None:
    issuer = "ĐẢNG BỘ THÀNH PHỐ HỒ CHÍ MINH\nĐẢNG ỦY PHƯỜNG BÌNH TIÊN"
    assert normalize_header_symbol(
        "CV/PDU", known_codes=("CV",), issuer_text=issuer
    ) == "CV/ĐU"
    assert normalize_header_symbol(
        "CV/UBKTTU", known_codes=("CV",), issuer_text=issuer
    ) == "CV/UBKTTU"
    assert normalize_header_symbol(
        "CV/BTCTU", known_codes=("CV",), issuer_text=issuer
    ) == "CV/BTCTU"


def test_cv_title_removes_body_boundary_duplicate_and_visible_garbage() -> None:
    value = clean_cong_van_title(
        "ND 000 V/L Về việc xác minh lý lịch người xin vào Đảng "
        "Về việc xác minh lý lịch người xin vào Đảng nu mm | ˆ E "
        "Kính gửi: Ban Chỉ huy Công an phường"
    )
    assert value == "Về việc xác minh lý lịch người xin vào Đảng"
    assert cong_van_title_is_clean(value)


def test_cv_visible_garbage_is_not_considered_a_clean_abstract() -> None:
    assert not cong_van_title_is_clean("VE vide văn minh")
    assert not cong_van_title_is_clean(
        "Về việc xác minh nơi cư trú với CC TT T | ˆ E"
    )


def test_parser_uses_only_bounded_cv_italic_block_and_ignores_stale_body_text(
    parser: DocumentParser,
) -> None:
    header = """
    ĐẢNG BỘ THÀNH PHỐ HỒ CHÍ MINH
    ĐẢNG ỦY PHƯỜNG BÌNH TIÊN
    Số 237-CV/PDU
    Về việc xác minh thái độ chính trị hiện nay
    phục vụ công tác cán bộ
    Kính gửi: Ban Chỉ huy Công an phường.
    """
    result = parser.parse(
        "Để có cơ sở xem xét, bố trí cán bộ đối với đồng chí A",
        source=DataSource.PADDLE_OCR,
        source_confidence=0.60,
        header_evidence_text=header,
        existing_form=FormSnapshot(
            document_number="227",
            symbol="CV/PDU",
            document_type="Công văn",
            abstract="VE vide văn minh Để có cơ sở xem xét, bố trí cán bộ",
        ),
    )
    assert result.document_number.value == "237"
    assert result.symbol.value == "CV/ĐU"
    assert result.document_type.value == "Công văn"
    assert result.abstract.value == (
        "Về việc xác minh thái độ chính trị hiện nay phục vụ công tác cán bộ"
    )
    assert DocumentValidator().can_auto_submit(result) or not DocumentValidator().validate(result)


def test_cv_number_sequence_falls_back_only_when_number_is_missing() -> None:
    sequence = CongVanNumberSequence()
    first = sequence.reconcile(
        _cv("237"),
        record_position=1,
        evidence=CongVanNumberEvidence(support=2, score=30.0, candidate_count=5),
    )
    assert first.document_number.value == "237"

    missing = sequence.reconcile(
        _cv(""),
        record_position=2,
        evidence=CongVanNumberEvidence(support=0, score=0.0, candidate_count=0),
    )
    assert missing.document_number.value == "236"
    assert missing.document_number.source_text == "cv-sequence-fallback"


def test_cv_number_sequence_never_overwrites_a_numeric_ocr_candidate_with_countdown() -> None:
    sequence = CongVanNumberSequence()
    sequence.reconcile(
        _cv("237"),
        record_position=1,
        evidence=CongVanNumberEvidence(support=2, score=30.0),
    )
    weak = sequence.reconcile(
        _cv("227"),
        record_position=2,
        evidence=CongVanNumberEvidence(support=1, score=30.0, candidate_count=4),
    )
    assert weak.document_number.value == "227"
    assert weak.document_number.value != "236"
    assert any(issue.code == "CV_NUMBER_OCR_UNCONFIRMED" for issue in weak.issues)

    # Start a fresh sequence: independent OCR agreement accepts a genuine gap
    # immediately. The current PDF number wins over arithmetic previous-1.
    sequence.reset()
    sequence.reconcile(
        _cv("237"),
        record_position=1,
        evidence=CongVanNumberEvidence(support=2, score=30.0, candidate_count=4),
    )
    result = sequence.reconcile(
        _cv("230"),
        record_position=2,
        evidence=CongVanNumberEvidence(support=2, score=25.0, candidate_count=4),
    )
    assert result.document_number.value == "230"
    assert result.document_number.source_text == "cv-sequence-ocr"


def test_cv_sequence_never_changes_other_document_types() -> None:
    sequence = CongVanNumberSequence()
    document = _cv("99")
    document.document_type = ParsedField("Báo cáo", 0.99, "header")
    result = sequence.reconcile(
        document,
        record_position=1,
        evidence=CongVanNumberEvidence(support=3, score=30.0),
    )
    assert result.document_number.value == "99"
    assert sequence.previous_number is None

@pytest.mark.parametrize(
    "value",
    [
        "Về việc xác minh nơi cureR với CC TT T",
        "Về việc xác minh thái độ chính trị Pang Lee nu",
        "Về việc thống kê danh sách cán bộ danh sách cái",
        "Về việc thẩm tra lý lịch của cấp ủy địa phương hi",
    ],
)
def test_cv_rejects_recurring_visible_ocr_fragments(value: str) -> None:
    assert not cong_van_title_is_clean(value)


def test_cv_cleanup_cuts_trailing_recognizer_fragments() -> None:
    assert clean_cong_van_title(
        "Về việc xác minh thái độ chính trị phục vụ công tác kết nạp Đảng Pang Lee nu"
    ) == "Về việc xác minh thái độ chính trị phục vụ công tác kết nạp Đảng"
    assert clean_cong_van_title(
        "Về việc thẩm tra lý lịch của cấp ủy địa phương hi"
    ) == "Về việc thẩm tra lý lịch của cấp ủy địa phương"


def test_cv_sequence_uses_position_distance_only_when_ocr_number_is_missing() -> None:
    sequence = CongVanNumberSequence()
    sequence.prime(position=10, number="228")
    result = sequence.reconcile(
        _cv(""),
        record_position=13,
        evidence=CongVanNumberEvidence(),
    )
    assert result.document_number.value == "225"
    assert result.document_number.source_text == "cv-sequence-fallback"


def test_cv_sequence_does_not_use_position_distance_over_a_scanned_number() -> None:
    sequence = CongVanNumberSequence()
    sequence.prime(position=10, number="228")
    result = sequence.reconcile(
        _cv("999"),
        record_position=13,
        evidence=CongVanNumberEvidence(support=1, score=7.0),
    )
    assert result.document_number.value == "999"
    assert result.document_number.value != "225"
    assert any(issue.code == "CV_NUMBER_OCR_UNCONFIRMED" for issue in result.issues)
