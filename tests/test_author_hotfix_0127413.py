from __future__ import annotations

from pathlib import Path

from cataloging_tool.document.metadata import (
    canonical_author_from_text,
    existing_author_matches_pdf_evidence,
)
from cataloging_tool.document.parser import DocumentParser
from cataloging_tool.document.text_extractor import DocumentTextExtractor
from cataloging_tool.domain.enums import DataSource
from cataloging_tool.domain.models import FormSnapshot, OcrResult


def _author(header: str, raw: str = "") -> str:
    return canonical_author_from_text(header, raw, default_author="")


def _parser() -> DocumentParser:
    root = Path(__file__).resolve().parents[1]
    return DocumentParser(root / "rules", "", "Thường")


def _base_text() -> str:
    return """
    Số 135-NQ/ĐU
    NGHỊ QUYẾT
    Đề nghị công nhận đảng viên chính thức
    -----
    Ngày 06 tháng 11 năm 2023, BCH Đảng bộ Phường 1 đã họp.
    """


def test_screenshot_header_wins_over_stale_binh_tien_form_author() -> None:
    parsed = _parser().parse(
        _base_text(),
        source=DataSource.PADDLE_OCR,
        source_confidence=0.96,
        existing_form=FormSnapshot(
            document_number="135",
            symbol="NQ/ĐU",
            document_type="Nghị quyết",
            abstract="Đề nghị công nhận đảng viên chính thức",
            author=(
                "ĐẢNG ỦY PHƯỜNG BÌNH TIÊN "
                "ĐẢNG BỘ THÀNH PHỐ HỒ CHÍ MINH"
            ),
        ),
        author_evidence_text=(
            "QUẬN ỦY QUẬN 6\n"
            "ĐẢNG ỦY PHƯỜNG 1\n"
            "Số 135-NQ/ĐU"
        ),
    )

    assert parsed.author == "ĐẢNG ỦY PHƯỜNG 1 QUẬN ỦY QUẬN 6"
    assert parsed.author_confidence >= 0.99
    assert "existing-form-conflict-ignored" in parsed.author_source_text


def test_stale_existing_author_cannot_rescue_conflicting_partial_pdf_evidence() -> None:
    parsed = _parser().parse(
        _base_text(),
        source=DataSource.PADDLE_OCR,
        source_confidence=0.96,
        existing_form=FormSnapshot(
            document_number="135",
            symbol="NQ/ĐU",
            document_type="Nghị quyết",
            abstract="Đề nghị công nhận đảng viên chính thức",
            author=(
                "ĐẢNG ỦY PHƯỜNG BÌNH TIÊN "
                "ĐẢNG BỘ THÀNH PHỐ HỒ CHÍ MINH"
            ),
        ),
        # OCR sees the current ward but misses the parent. That is enough to
        # prove that a BÌNH TIÊN existing value is stale and must not rescue.
        author_evidence_text="ĐẢNG ỦY PHƯỜNG 1",
    )

    assert parsed.author == ""
    assert parsed.author_confidence == 0.0
    assert parsed.author_source_text == "existing-form-rejected:author-not-corroborated"


def test_matching_existing_author_requires_parent_kind_hint() -> None:
    existing = "ĐẢNG ỦY PHƯỜNG 1 QUẬN ỦY QUẬN 6"
    assert not existing_author_matches_pdf_evidence(
        existing,
        "ĐẢNG ỦY PHƯỜNG 1\nSố 135-NQ/ĐU",
    )
    assert existing_author_matches_pdf_evidence(
        existing,
        "ĐẢNG ỦY PHƯỜNG 1\nQUẬN ỦY QUẬN\nSố 135-NQ/ĐU",
    )


def test_issuer_parser_accepts_common_q_p_abbreviations_and_separators() -> None:
    assert _author(
        "QUẬN ỦY - Q.6\n"
        "ĐẢNG ỦY: P.1\n"
        "Số 135-NQ/ĐU"
    ) == "ĐẢNG ỦY PHƯỜNG 1 QUẬN ỦY QUẬN 6"


def test_body_citation_cannot_complete_partial_header_author() -> None:
    header = """
    ĐẢNG ỦY PHƯỜNG 1
    NGHỊ QUYẾT
    Đề nghị công nhận đảng viên chính thức
    """
    raw = """
    ĐẢNG ỦY PHƯỜNG 1
    NGHỊ QUYẾT
    Đề nghị công nhận đảng viên chính thức
    Kính gửi: BAN THƯỜNG VỤ QUẬN ỦY QUẬN 6
    """
    assert _author(header, raw) == ""


class _ThresholdAuthorPipeline:
    def prepare_author_header_crops(
        self,
        source_image: Path,
        artifact_dir: Path,
    ) -> list[Path]:
        return [
            artifact_dir / "tight.png",
            artifact_dir / "left.png",
            artifact_dir / "wide.png",
        ]

    def preprocess_for_ocr(
        self,
        crop: Path,
        output_path: Path,
        *,
        mode: str,
        target_width: int,
    ) -> Path:
        del crop, target_width
        return output_path


class _ThresholdAuthorOcr:
    def recognize_header_candidates(self, image_path: Path) -> list[OcrResult]:
        if "threshold" in image_path.name:
            return [
                OcrResult(
                    raw_text="QUẬN ỦY QUẬN 6\nĐẢNG ỦY PHƯỜNG 1",
                    confidence=0.93,
                    engine="threshold-test",
                )
            ]
        return [
            OcrResult(
                raw_text="ĐẢNG ỦY PHƯỜNG",
                confidence=0.91,
                engine="enhanced-test",
            )
        ]


def test_author_recovery_uses_threshold_only_after_enhanced_pass_is_incomplete(
    tmp_path: Path,
) -> None:
    extractor = DocumentTextExtractor(
        _ThresholdAuthorPipeline(),  # type: ignore[arg-type]
        _ThresholdAuthorOcr(),  # type: ignore[arg-type]
        tmp_path,
    )

    recovered = extractor._recover_author_header(
        tmp_path / "page.png",
        tmp_path,
    )

    assert _author(recovered) == "ĐẢNG ỦY PHƯỜNG 1 QUẬN ỦY QUẬN 6"
