from __future__ import annotations

from pathlib import Path

from cataloging_tool.document.metadata import canonical_author_from_text
from cataloging_tool.document.parser import DocumentParser
from cataloging_tool.document.text_extractor import DocumentTextExtractor
from cataloging_tool.domain.enums import DataSource
from cataloging_tool.domain.models import FormSnapshot, OcrResult


def _author(value: str) -> str:
    return canonical_author_from_text(value, "", default_author="")


def test_author_recovers_issuer_when_ocr_splits_prefix_across_lines() -> None:
    assert _author(
        "QUẬN ỦY\nQUẬN 6\nĐẢNG ỦY\nPHƯỜNG 1"
    ) == "ĐẢNG ỦY PHƯỜNG 1 QUẬN ỦY QUẬN 6"


def test_author_recovers_city_pair_when_ocr_splits_physical_lines() -> None:
    assert _author(
        "ĐẢNG BỘ THÀNH PHỐ\nHỒ CHÍ MINH\nĐẢNG ỦY\nPHƯỜNG BÌNH TIÊN"
    ) == (
        "ĐẢNG ỦY PHƯỜNG BÌNH TIÊN "
        "ĐẢNG BỘ THÀNH PHỐ HỒ CHÍ MINH"
    )


class _AuthorCropPipeline:
    def prepare_author_header_crops(self, source_image: Path, artifact_dir: Path) -> list[Path]:
        return [artifact_dir / "left.png", artifact_dir / "wide.png"]

    def preprocess_for_ocr(
        self,
        crop: Path,
        output_path: Path,
        *,
        mode: str,
        target_width: int,
    ) -> Path:
        return crop


class _ComplementaryAuthorOcr:
    def recognize_header_candidates(self, image_path: Path) -> list[OcrResult]:
        if image_path.name == "left.png":
            return [
                OcrResult(
                    raw_text="ĐẢNG ỦY PHƯỜNG 1",
                    confidence=0.94,
                    engine="test",
                )
            ]
        return [
            OcrResult(
                raw_text="QUẬN ỦY QUẬN 6",
                confidence=0.95,
                engine="test",
            )
        ]


def test_focused_author_recovery_merges_complementary_ocr_candidates(tmp_path: Path) -> None:
    extractor = DocumentTextExtractor(
        _AuthorCropPipeline(),  # type: ignore[arg-type]
        _ComplementaryAuthorOcr(),  # type: ignore[arg-type]
        tmp_path,
    )

    recovered = extractor._recover_author_header(
        tmp_path / "page.png",
        tmp_path,
    )

    assert _author(recovered) == "ĐẢNG ỦY PHƯỜNG 1 QUẬN ỦY QUẬN 6"


def test_existing_canonical_author_does_not_rescue_local_only_author_ocr() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = DocumentParser(root / "rules", "", "Thường")

    parsed = parser.parse(
        """
        Số 12-QĐ/ĐU
        QUYẾT ĐỊNH
        Về việc thành lập Tổ công tác
        -----
        Điều 1. Thành lập Tổ công tác
        """,
        source=DataSource.PADDLE_OCR,
        source_confidence=0.98,
        existing_form=FormSnapshot(
            document_number="12",
            symbol="QĐ/ĐU",
            document_type="Quyết định",
            abstract="Về việc thành lập Tổ công tác",
            author="ĐẢNG ỦY PHƯỜNG 1 QUẬN ỦY QUẬN 6",
        ),
        author_evidence_text="ĐẢNG ỦY PHƯỜNG 1",
    )

    assert parsed.author == ""
    assert parsed.author_confidence == 0.0
    assert parsed.author_source_text == "existing-form-rejected:author-not-corroborated"
