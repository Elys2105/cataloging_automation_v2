from __future__ import annotations

import re

from cataloging_tool.domain.enums import Severity
from cataloging_tool.domain.models import ParsedDocument, ParsedField, ValidationIssue

from .document_header import (
    clean_cong_van_title,
    cong_van_title_has_visible_garbage,
)
from .normalizer import fold_vietnamese
from .ocr import abstract_has_visible_ocr_corruption, vietnamese_text_quality


class DocumentValidator:
    def __init__(
        self,
        minimum_confidence: float = 0.82,
        *,
        require_author: bool = False,
    ) -> None:
        self.minimum_confidence = minimum_confidence
        self.require_author = require_author

    @staticmethod
    def _repair_bounded_cong_van_abstract(document: ParsedDocument) -> None:
        """Keep only the Công văn italic title block before ``Kính gửi``.

        This is deliberately Công-văn-only.  A stale form value or a noisy OCR
        candidate may contain the correct title followed by ``Kính gửi`` or the
        first body sentence.  The bounded title cleaner already knows those
        boundaries, so validation should repair that value instead of turning
        every otherwise usable record into ``needs_review``.
        """
        if document.document_type.value != "Công văn":
            return
        original = (document.abstract.value or "").strip()
        if not original:
            return
        cleaned = clean_cong_van_title(original)
        cleaned_key = fold_vietnamese(cleaned)
        valid_start = cleaned_key.startswith(("ve ", "v/v ", "bao cao ve "))
        if (
            cleaned
            and valid_start
            and not cong_van_title_has_visible_garbage(cleaned)
            and cleaned != original
        ):
            document.abstract = ParsedField(
                cleaned,
                max(document.abstract.confidence, 0.94),
                f"{document.abstract.source_text}|cv-bounded-validation-repair".strip("|"),
            )

    @staticmethod
    def _cong_van_structure_is_safe(document: ParsedDocument) -> bool:
        if document.document_type.value != "Công văn":
            return False
        number = (document.document_number.value or "").strip()
        symbol = (document.symbol.value or "").strip().upper()
        abstract = (document.abstract.value or "").strip()
        abstract_key = fold_vietnamese(abstract)
        if not re.fullmatch(r"\d{1,6}", number):
            return False
        if not re.fullmatch(r"CV/[A-ZĐ0-9]{1,15}", symbol):
            return False
        if not abstract_key.startswith(("ve ", "v/v ", "bao cao ve ")):
            return False
        if len(abstract) < 8 or len(abstract) > 650:
            return False
        if cong_van_title_has_visible_garbage(abstract):
            return False
        forbidden = ("kinh gui", "can cu", "noi nhan", "dieu 1", "trich yeu noi dung")
        return not any(token in abstract_key for token in forbidden)

    def validate(self, document: ParsedDocument) -> list[ValidationIssue]:
        self._repair_bounded_cong_van_abstract(document)
        issues = list(document.issues)
        required = {
            "document_number": document.document_number,
            "symbol": document.symbol,
            "document_type": document.document_type,
            "abstract": document.abstract,
        }
        for name, field in required.items():
            if not field.value.strip():
                issues.append(
                    ValidationIssue(
                        code="REQUIRED_FIELD_EMPTY",
                        field=name,
                        message=f"Thiếu trường bắt buộc: {name}",
                        severity=Severity.ERROR,
                    )
                )
        if self.require_author and not document.author.strip():
            issues.append(
                ValidationIssue(
                    code="AUTHOR_NOT_RECOVERED",
                    field="author",
                    message=(
                        "Không xác định được Tác giả văn bản từ đầu trang PDF sau "
                        "khi đã thử OCR vùng cơ quan ban hành"
                    ),
                    severity=Severity.ERROR,
                )
            )
        if document.document_number.value and not re.fullmatch(r"\d{1,6}", document.document_number.value):
            issues.append(ValidationIssue("INVALID_NUMBER", "Số văn bản không hợp lệ", Severity.ERROR, "document_number"))
        if document.symbol.value and not re.fullmatch(r"[A-ZĐ0-9]{1,10}(?:/[A-ZĐ0-9]{1,15})+", document.symbol.value):
            issues.append(ValidationIssue("INVALID_SYMBOL", "Ký hiệu văn bản không hợp lệ", Severity.ERROR, "symbol"))

        cv_structure_safe = self._cong_van_structure_is_safe(document)
        if document.document_type.value == "Công văn":
            if document.symbol.value and not document.symbol.value.startswith("CV/"):
                issues.append(
                    ValidationIssue(
                        "CV_SYMBOL_MISMATCH",
                        "Ký hiệu nhánh Công văn phải bắt đầu bằng CV/",
                        Severity.ERROR,
                        "symbol",
                    )
                )
            # Do not use a language-quality score as a hard blocker.  It caused
            # valid short/faint Công văn titles to be marked red en masse.  Only
            # clear structural/body/garbage violations remain blocking errors.
            if document.abstract.value and not cv_structure_safe:
                issues.append(
                    ValidationIssue(
                        "CV_ABSTRACT_INVALID",
                        "Trích yếu Công văn không phải khối tiêu đề sạch trước Kính gửi",
                        Severity.ERROR,
                        "abstract",
                    )
                )

        abstract_key = fold_vietnamese(document.abstract.value)
        forbidden = ("kinh gui", "can cu", "noi nhan", "dieu 1", "trich yeu noi dung")
        if any(token in abstract_key for token in forbidden):
            issues.append(
                ValidationIssue(
                    "ABSTRACT_BODY_LEAK",
                    "Trích yếu có dấu hiệu dính phần thân/UI",
                    Severity.ERROR,
                    "abstract",
                )
            )

        # Reject only *visible* OCR corruption. ``vietnamese_text_quality`` is
        # useful for ranking OCR candidates, but is not a hard abstract gate.
        if len(document.abstract.value) >= 40 and abstract_has_visible_ocr_corruption(
            document.abstract.value
        ):
            language_quality = vietnamese_text_quality(document.abstract.value)
            issues.append(
                ValidationIssue(
                    "CORRUPTED_VIETNAMESE",
                    f"Trích yếu có mẫu mất chữ OCR rõ ràng (quality={language_quality:.2f})",
                    Severity.ERROR,
                    "abstract",
                )
            )

        if document.overall_confidence < self.minimum_confidence:
            # A bounded Công văn header with all required fields is stronger
            # than the average confidence of the whole scanned page.  Do not
            # create a false review solely because a faint page averaged 0.60.
            if cv_structure_safe and not any(
                issue.severity == Severity.ERROR for issue in issues
            ):
                document.overall_confidence = max(document.overall_confidence, 0.90)
            else:
                issues.append(
                    ValidationIssue(
                        "LOW_CONFIDENCE",
                        f"Độ tin cậy {document.overall_confidence:.2f} thấp hơn ngưỡng {self.minimum_confidence:.2f}",
                        Severity.ERROR,
                    )
                )
        document.issues = issues
        return issues

    @staticmethod
    def can_auto_submit(document: ParsedDocument) -> bool:
        return not any(issue.severity == Severity.ERROR for issue in document.issues)
