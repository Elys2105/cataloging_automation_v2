from __future__ import annotations

from cataloging_tool.document.cong_van_sequence import (
    CongVanNumberEvidence,
    CongVanNumberSequence,
)
from cataloging_tool.domain.enums import DataSource, Severity
from cataloging_tool.domain.models import ParsedDocument, ParsedField


def _doc(
    number: str,
    *,
    source: DataSource = DataSource.PADDLE_OCR,
    confidence: float = 0.90,
) -> ParsedDocument:
    return ParsedDocument(
        document_number=ParsedField(number, confidence, f"ocr:number:{number}"),
        symbol=ParsedField("CV/ĐU", 0.95, "header"),
        document_type=ParsedField("Công văn", 0.95, "header"),
        abstract=ParsedField("Về việc kiểm tra số văn bản", 0.95, "header"),
        source=source,
        overall_confidence=0.90,
    )


def _strong() -> CongVanNumberEvidence:
    return CongVanNumberEvidence(support=2, score=14.0, candidate_count=2)


def _weak() -> CongVanNumberEvidence:
    return CongVanNumberEvidence(support=1, score=9.0, candidate_count=1)


def test_strong_scanned_number_wins_over_previous_minus_one() -> None:
    seq = CongVanNumberSequence()
    seq.prime(position=10, number="300")

    result = seq.reconcile(_doc("297"), record_position=11, evidence=_strong())

    assert result.document_number.value == "297"
    assert result.document_number.source_text == "cv-sequence-ocr"
    assert seq.previous_number == 297


def test_pdf_text_number_always_wins_over_countdown() -> None:
    seq = CongVanNumberSequence()
    seq.prime(position=10, number="300")

    result = seq.reconcile(
        _doc("287", source=DataSource.PDF_TEXT),
        record_position=11,
        evidence=CongVanNumberEvidence(),
    )

    assert result.document_number.value == "287"
    assert result.document_number.source_text == "cv-sequence-pdf-text"


def test_countdown_is_used_only_when_current_pdf_has_no_numeric_candidate() -> None:
    seq = CongVanNumberSequence()
    seq.prime(position=10, number="300")

    result = seq.reconcile(_doc("", confidence=0.0), record_position=11, evidence=_weak())

    assert result.document_number.value == "299"
    assert result.document_number.source_text == "cv-sequence-fallback"
    assert any(issue.code == "CV_NUMBER_SEQUENCE_APPLIED" for issue in result.issues)


def test_weak_conflicting_scan_is_never_replaced_by_countdown() -> None:
    seq = CongVanNumberSequence()
    seq.prime(position=10, number="300")

    result = seq.reconcile(_doc("297", confidence=0.76), record_position=11, evidence=_weak())

    assert result.document_number.value == "297"
    assert result.document_number.value != "299"
    assert result.document_number.confidence < 0.82
    assert any(
        issue.code == "CV_NUMBER_OCR_UNCONFIRMED" and issue.severity == Severity.ERROR
        for issue in result.issues
    )
    # Ambiguity must not poison all later rows with a guessed sequence.
    assert seq.previous_number is None


def test_expected_number_can_confirm_one_weak_read_without_extra_retry() -> None:
    seq = CongVanNumberSequence()
    seq.prime(position=10, number="300")

    doc = _doc("299", confidence=0.72)
    assert not seq.needs_ocr_retry(doc, record_position=11, evidence=_weak())

    result = seq.reconcile(doc, record_position=11, evidence=_weak())
    assert result.document_number.value == "299"
    assert result.document_number.source_text == "cv-sequence-confirmed"


def test_missing_number_requests_focused_retry_before_fallback() -> None:
    seq = CongVanNumberSequence()
    seq.prime(position=10, number="300")

    assert seq.needs_ocr_retry(
        _doc("", confidence=0.0), record_position=11, evidence=CongVanNumberEvidence()
    )


def test_conflicting_weak_number_requests_focused_retry() -> None:
    seq = CongVanNumberSequence()
    seq.prime(position=10, number="300")

    assert seq.needs_ocr_retry(_doc("297"), record_position=11, evidence=_weak())


def test_conflicting_strong_number_does_not_need_retry() -> None:
    seq = CongVanNumberSequence()
    seq.prime(position=10, number="300")

    assert not seq.needs_ocr_retry(_doc("297"), record_position=11, evidence=_strong())


def test_first_anchor_weak_read_gets_retry_instead_of_seeding_sequence() -> None:
    seq = CongVanNumberSequence()
    doc = _doc("300", confidence=0.75)

    assert seq.needs_ocr_retry(doc, record_position=1, evidence=_weak())

    result = seq.reconcile(doc, record_position=1, evidence=_weak())
    assert result.document_number.value == "300"
    assert seq.previous_number is None
    assert any(issue.code == "CV_NUMBER_NOT_CONFIRMED" for issue in result.issues)


def test_retry_can_replace_previous_fallback_when_number_becomes_readable() -> None:
    seq = CongVanNumberSequence()
    seq.prime(position=10, number="300")

    first = seq.reconcile(
        _doc("", confidence=0.0), record_position=11, evidence=CongVanNumberEvidence()
    )
    assert first.document_number.value == "299"

    second = seq.reconcile(_doc("297"), record_position=11, evidence=_strong())
    assert second.document_number.value == "297"
    assert second.document_number.source_text == "cv-sequence-retry-ocr"
    assert seq.decisions[11] == 297


def test_retry_does_not_freeze_old_fallback_over_new_weak_candidate() -> None:
    seq = CongVanNumberSequence()
    seq.prime(position=10, number="300")
    seq.reconcile(_doc("", confidence=0.0), record_position=11, evidence=CongVanNumberEvidence())

    second = seq.reconcile(_doc("297", confidence=0.70), record_position=11, evidence=_weak())

    assert second.document_number.value == "297"
    assert second.document_number.value != "299"
    assert seq.previous_number is None


def test_two_matching_forced_passes_promote_number_to_strong_evidence() -> None:
    first_doc = _doc("297", confidence=0.72)
    second_doc = _doc("297", confidence=0.73)
    first = CongVanNumberEvidence(support=1, score=8.0, candidate_count=1)
    second = CongVanNumberEvidence(support=1, score=9.0, candidate_count=1)

    merged = CongVanNumberSequence.merge_retry_evidence(first_doc, first, second_doc, second)

    assert merged.support >= 2
    assert merged.score >= 12.0
    assert merged.strong


def test_disagreeing_forced_passes_do_not_fake_consensus() -> None:
    first_doc = _doc("297", confidence=0.72)
    second_doc = _doc("296", confidence=0.73)
    first = CongVanNumberEvidence(support=1, score=8.0, candidate_count=1)
    second = CongVanNumberEvidence(support=1, score=9.0, candidate_count=1)

    merged = CongVanNumberSequence.merge_retry_evidence(first_doc, first, second_doc, second)

    assert merged.support == 1
    assert not merged.strong


def test_non_cong_van_is_never_touched_by_sequence() -> None:
    seq = CongVanNumberSequence()
    seq.prime(position=10, number="300")
    doc = _doc("25")
    doc.document_type = ParsedField("Báo cáo", 0.95, "header")

    result = seq.reconcile(doc, record_position=11, evidence=CongVanNumberEvidence())

    assert result.document_number.value == "25"
    assert result.document_number.source_text == "ocr:number:25"
