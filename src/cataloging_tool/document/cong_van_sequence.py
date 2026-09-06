from __future__ import annotations

import re
from dataclasses import dataclass, field

from cataloging_tool.domain.enums import DataSource, Severity
from cataloging_tool.domain.models import ParsedDocument, ParsedField, ValidationIssue


@dataclass(frozen=True, slots=True)
class CongVanNumberEvidence:
    support: int = 0
    score: float = 0.0
    candidate_count: int = 0

    @property
    def strong(self) -> bool:
        # Two independent OCR/crop readings agreeing on the same own header are
        # enough to trust the number printed/written on the current PDF.
        return self.support >= 2 and self.score >= 12.0

    @property
    def exceptional(self) -> bool:
        # Kept for backward compatibility/diagnostics. 0.1.27.4.19 no longer
        # requires ``exceptional`` evidence merely because a readable current
        # PDF number differs from the arithmetic sequence. A readable PDF wins.
        return (
            self.support >= 2
            and self.score >= 18.0
            and self.candidate_count >= 3
        )


@dataclass(slots=True)
class CongVanNumberSequence:
    """Reconcile Công văn numbers in website order without overriding OCR.

    Hard rule from 0.1.27.4.19:

    * If the current PDF yields a numeric own-header ``Số văn bản``, that value
      is never replaced merely because it differs from the previous number - 1.
    * The decreasing-sequence fallback is allowed only when the current PDF did
      not yield any numeric candidate after the caller's focused OCR retry.
    * A weak/conflicting candidate is preserved and marked for review instead
      of silently replacing it with a guessed countdown value.

    This prevents the old failure mode where a real sequence gap (or simply a
    successfully scanned number) was overwritten by ``previous - 1``.
    """

    previous_number: int | None = None
    previous_position: int | None = None
    decisions: dict[int, int] = field(default_factory=dict)
    decision_sources: dict[int, str] = field(default_factory=dict)

    def reset(self) -> None:
        self.previous_number = None
        self.previous_position = None
        self.decisions.clear()
        self.decision_sources.clear()

    def prime(self, *, position: int, number: str) -> None:
        if re.fullmatch(r"\d{1,6}", number or ""):
            value = int(number)
            if value > 0:
                self.previous_number = value
                self.previous_position = position
                self.decisions[position] = value
                self.decision_sources[position] = "cv-sequence-prime"

    @staticmethod
    def _numeric_candidate(document: ParsedDocument) -> int | None:
        raw_value = (document.document_number.value or "").strip()
        if not re.fullmatch(r"\d{1,6}", raw_value):
            return None
        value = int(raw_value)
        return value if value > 0 else None

    def expected_number(self, *, record_position: int) -> int | None:
        if self.previous_number is None:
            return None
        if self.previous_position is None:
            step = 1
        else:
            delta = record_position - self.previous_position
            if delta <= 0:
                return None
            step = delta
        expected = self.previous_number - step
        return expected if expected > 0 else None

    @classmethod
    def merge_retry_evidence(
        cls,
        first_document: ParsedDocument,
        first: CongVanNumberEvidence,
        second_document: ParsedDocument,
        second: CongVanNumberEvidence,
    ) -> CongVanNumberEvidence:
        support = max(first.support, second.support)
        score = max(first.score, second.score)
        candidate_count = max(first.candidate_count, second.candidate_count)

        # The second pass bypasses OCR/cache and reruns the focused number crops.
        # Matching numeric results across both passes count as independent
        # confirmation even when each canonical pass individually reports one
        # source of support.
        first_candidate = cls._numeric_candidate(first_document)
        second_candidate = cls._numeric_candidate(second_document)
        if first_candidate is not None and first_candidate == second_candidate:
            support = max(support, 2)
            score = max(score, 12.0)
            candidate_count = max(candidate_count, 2)

        return CongVanNumberEvidence(
            support=support,
            score=score,
            candidate_count=candidate_count,
        )

    def needs_ocr_retry(
        self,
        document: ParsedDocument,
        *,
        record_position: int,
        evidence: CongVanNumberEvidence,
    ) -> bool:
        """Return True only when another focused number scan can add value.

        PDF text is already exact. Raster OCR gets one forced, cache-bypassing
        focused pass when the first reading is missing or conflicts with the
        arithmetic sequence without independent agreement.
        """

        if document.document_type.value != "Công văn":
            return False
        if document.source == DataSource.PDF_TEXT:
            return False

        candidate = self._numeric_candidate(document)

        # A retry of the same workflow record may already have a remembered
        # decision. If OCR is still blank, repeating the exact forced pass adds
        # no value; reconcile() can reuse that decision. If a candidate appears,
        # reconcile() is allowed to supersede a previous fallback.
        if record_position in self.decisions and candidate is None:
            return False

        if candidate is None:
            return True
        if evidence.strong:
            return False

        expected = self.expected_number(record_position=record_position)
        if expected is None:
            # First anchor: do not seed the whole sequence from one weak read.
            return True

        # If the weak scan already agrees with the expected number, the sequence
        # itself is the second independent signal. Otherwise force another OCR
        # pass before considering any fallback/review decision.
        return candidate != expected

    def reconcile(
        self,
        document: ParsedDocument,
        *,
        record_position: int,
        evidence: CongVanNumberEvidence,
    ) -> ParsedDocument:
        if document.document_type.value != "Công văn":
            return document

        candidate = self._numeric_candidate(document)
        direct_text = document.source == DataSource.PDF_TEXT
        candidate_strong = direct_text or evidence.strong

        # Workflow retries must not freeze an old fallback forever. If a later
        # attempt finally scans a real number, that new current-PDF evidence is
        # evaluated and can replace the remembered fallback.
        prior_decision = self.decisions.get(record_position)
        if prior_decision is not None:
            prior_source = self.decision_sources.get(
                record_position, "cv-sequence-retry"
            )
            if candidate is None:
                return self._replace_number(
                    document,
                    prior_decision,
                    source="cv-sequence-retry",
                    message="Dùng lại số Công văn đã quyết định cho lần thử trước vì OCR hiện vẫn không đọc được số",
                )
            if candidate == prior_decision:
                self.previous_number = candidate
                self.previous_position = record_position
                self.decisions[record_position] = candidate
                self.decision_sources[record_position] = "cv-sequence-retry-confirmed"
                return self._replace_number(
                    document,
                    candidate,
                    source="cv-sequence-retry-confirmed",
                    message="OCR lần thử lại xác nhận số Công văn đã quyết định trước đó",
                )
            if candidate_strong:
                self.previous_number = candidate
                self.previous_position = record_position
                self.decisions[record_position] = candidate
                self.decision_sources[record_position] = "cv-sequence-retry-ocr"
                return self._replace_number(
                    document,
                    candidate,
                    source="cv-sequence-retry-ocr",
                    message=(
                        "OCR/PDF hiện tại đã đọc được số Công văn; ưu tiên số trên PDF "
                        f"thay cho quyết định cũ ({prior_source})"
                    ),
                )

            # A newly visible but still ambiguous number must never be hidden by
            # an old guessed countdown. Stop propagating the sequence until the
            # current record is confirmed.
            self.decisions.pop(record_position, None)
            self.decision_sources.pop(record_position, None)
            self.previous_number = None
            self.previous_position = None
            return self._mark_unconfirmed_candidate(
                document,
                message=(
                    f"OCR hiện đọc '{candidate}' khác số đã nhớ '{prior_decision}' nhưng "
                    "chưa có đủ bằng chứng độc lập; không được tự đếm ngược đè lên số OCR"
                ),
            )

        # Establish the first anchor only from exact PDF text or independent
        # focused OCR agreement. One weak read must not seed every later row.
        if self.previous_number is None:
            if candidate is None:
                return document
            if not candidate_strong:
                return self._mark_unconfirmed_candidate(
                    document,
                    code="CV_NUMBER_NOT_CONFIRMED",
                    message=(
                        "Số Công văn đầu chuỗi chỉ có một bằng chứng OCR; cần OCR/crop "
                        "độc lập xác nhận trước khi dùng làm mốc"
                    ),
                )

            self.previous_number = candidate
            self.previous_position = record_position
            self.decisions[record_position] = candidate
            self.decision_sources[record_position] = "cv-sequence-anchor"
            return self._replace_number(
                document,
                candidate,
                source="cv-sequence-anchor",
                message="Đã xác lập số đầu chuỗi Công văn từ PDF/đa bằng chứng OCR",
            )

        expected = self.expected_number(record_position=record_position)

        # If a numeric candidate exists, it is the current document's evidence.
        # NEVER replace it solely with previous-1. Strong/current PDF evidence
        # becomes the new anchor even when there is a legitimate archive gap.
        if candidate is not None:
            if expected is not None and candidate == expected:
                self.previous_number = candidate
                self.previous_position = record_position
                self.decisions[record_position] = candidate
                self.decision_sources[record_position] = "cv-sequence-confirmed"
                return self._replace_number(
                    document,
                    candidate,
                    source="cv-sequence-confirmed",
                    message="OCR khớp đúng số giảm dần của chuỗi Công văn",
                )

            if candidate_strong:
                self.previous_number = candidate
                self.previous_position = record_position
                self.decisions[record_position] = candidate
                self.decision_sources[record_position] = (
                    "cv-sequence-pdf-text" if direct_text else "cv-sequence-ocr"
                )
                return self._replace_number(
                    document,
                    candidate,
                    source=(
                        "cv-sequence-pdf-text" if direct_text else "cv-sequence-ocr"
                    ),
                    message=(
                        "Số Công văn lấy trực tiếp từ PDF; số đọc được trên văn bản "
                        "được ưu tiên hơn phép đếm ngược"
                    ),
                )

            # The caller already performed its one forced focused retry before
            # reaching here. Preserve the candidate but block auto-submit rather
            # than fabricate a countdown number. Also clear the sequence anchor
            # so one ambiguous row cannot corrupt all following rows.
            self.previous_number = None
            self.previous_position = None
            return self._mark_unconfirmed_candidate(
                document,
                message=(
                    f"OCR đọc được số Công văn '{candidate}' nhưng chưa đủ bằng chứng "
                    "độc lập; giữ nguyên số OCR và dừng chuỗi đếm ngược để tránh điền sai"
                ),
            )

        # Countdown fallback is now intentionally here and only here: the
        # current PDF yielded NO numeric candidate after focused OCR retry.
        if expected is None:
            return document

        self.previous_number = expected
        self.previous_position = record_position
        self.decisions[record_position] = expected
        self.decision_sources[record_position] = "cv-sequence-fallback"
        return self._replace_number(
            document,
            expected,
            source="cv-sequence-fallback",
            message=(
                "Không quét được Số văn bản sau OCR tập trung; mới dùng fallback "
                f"đếm ngược về {expected}"
            ),
        )

    @staticmethod
    def _mark_unconfirmed_candidate(
        document: ParsedDocument,
        *,
        message: str,
        code: str = "CV_NUMBER_OCR_UNCONFIRMED",
    ) -> ParsedDocument:
        # Keep the number that OCR actually saw. Cap confidence below the normal
        # auto-submit threshold so validation cannot silently submit ambiguity.
        field = document.document_number
        if field.value:
            document.document_number = ParsedField(
                field.value,
                min(field.confidence, 0.79),
                field.source_text or "cv-number-ocr-unconfirmed",
            )
        document.issues.append(
            ValidationIssue(
                code=code,
                message=message,
                severity=Severity.ERROR,
                field="document_number",
            )
        )
        return document

    @staticmethod
    def _replace_number(
        document: ParsedDocument,
        value: int,
        *,
        source: str,
        message: str,
    ) -> ParsedDocument:
        original = document.document_number.value
        document.document_number = ParsedField(str(value), 0.995, source)
        if original != str(value):
            document.issues.append(
                ValidationIssue(
                    code="CV_NUMBER_SEQUENCE_APPLIED",
                    message=f"{message} (OCR/form='{original or 'trống'}', chọn='{value}')",
                    severity=Severity.INFO,
                    field="document_number",
                )
            )
        field_confidence = min(
            document.document_number.confidence,
            document.symbol.confidence,
            document.document_type.confidence,
            document.abstract.confidence,
        )
        if all(
            field.value
            for field in (
                document.document_number,
                document.symbol,
                document.document_type,
                document.abstract,
            )
        ):
            document.overall_confidence = max(
                document.overall_confidence,
                min(field_confidence, 0.95),
            )
        return document
