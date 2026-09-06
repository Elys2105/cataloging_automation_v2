from __future__ import annotations

from cataloging_tool.document.cong_van_sequence import (
    CongVanNumberEvidence,
    CongVanNumberSequence,
)
from cataloging_tool.document.validator import DocumentValidator
from cataloging_tool.domain.enums import DataSource, Severity
from cataloging_tool.domain.models import ParsedDocument, ParsedField


def _cv(number: str, abstract: str, confidence: float = 0.60) -> ParsedDocument:
    return ParsedDocument(
        document_number=ParsedField(number, 0.90, "single-header-crop"),
        symbol=ParsedField("CV/ĐU", 0.99, "header"),
        document_type=ParsedField("Công văn", 0.99, "header"),
        abstract=ParsedField(abstract, 0.60, "header"),
        source=DataSource.PADDLE_OCR,
        overall_confidence=confidence,
    )


def test_weak_first_cv_number_is_not_used_as_sequence_anchor_without_confirmation() -> None:
    sequence = CongVanNumberSequence()
    document = sequence.reconcile(
        _cv("237", "Về việc xác minh thái độ chính trị phục vụ công tác cán bộ"),
        record_position=1,
        evidence=CongVanNumberEvidence(support=1, score=8.0, candidate_count=1),
    )
    assert document.document_number.value == "237"
    assert document.document_number.source_text == "single-header-crop"
    assert sequence.previous_number is None
    assert any(issue.code == "CV_NUMBER_NOT_CONFIRMED" for issue in document.issues)


def test_weak_first_cv_number_is_not_truncated_without_independent_evidence() -> None:
    sequence = CongVanNumberSequence()
    document = sequence.reconcile(
        _cv("56234", "Về việc xác minh thái độ chính trị phục vụ công tác cán bộ"),
        record_position=1,
        evidence=CongVanNumberEvidence(support=1, score=8.0, candidate_count=1),
    )
    assert document.document_number.value == "56234"
    assert sequence.previous_number is None
    assert any(issue.code == "CV_NUMBER_NOT_CONFIRMED" for issue in document.issues)


def test_clean_complete_cv_is_not_rejected_only_for_page_confidence() -> None:
    document = _cv(
        "237",
        "Về việc xác minh thái độ chính trị hiện nay phục vụ công tác cán bộ",
        confidence=0.60,
    )
    issues = DocumentValidator().validate(document)
    assert not any(issue.severity == Severity.ERROR for issue in issues)
    assert document.overall_confidence >= 0.82
    assert DocumentValidator.can_auto_submit(document)


def test_cv_validator_cuts_recipient_and_body_instead_of_false_review() -> None:
    document = _cv(
        "236",
        "Về việc xác minh lý lịch người xin vào Đảng Kính gửi: Ban Chỉ huy Công an phường Căn cứ hồ sơ",
        confidence=0.60,
    )
    issues = DocumentValidator().validate(document)
    assert document.abstract.value == "Về việc xác minh lý lịch người xin vào Đảng"
    assert not any(issue.severity == Severity.ERROR for issue in issues)
    assert DocumentValidator.can_auto_submit(document)


def test_clear_cv_garbage_still_blocks_submission() -> None:
    document = _cv("235", "VE vide văn minh nu mm | E", confidence=0.60)
    issues = DocumentValidator().validate(document)
    assert any(issue.severity == Severity.ERROR for issue in issues)
    assert not DocumentValidator.can_auto_submit(document)


def test_non_cv_low_confidence_rule_is_unchanged() -> None:
    document = _cv("1", "Về kế hoạch công tác", confidence=0.60)
    document.symbol = ParsedField("KH/ĐU", 0.99, "header")
    document.document_type = ParsedField("Kế hoạch", 0.99, "header")
    issues = DocumentValidator().validate(document)
    assert any(issue.code == "LOW_CONFIDENCE" for issue in issues)
