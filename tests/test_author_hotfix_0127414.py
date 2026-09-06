from __future__ import annotations

from pathlib import Path

import pytest

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


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (
            "ĐẢNG BỘ QUẬN 6\nĐẢNG ỦY PHƯỜNG 1\nSố 153-CV/ĐU",
            "ĐẢNG ỦY PHƯỜNG 1 ĐẢNG BỘ QUẬN 6",
        ),
        (
            "QUẬN ỦY QUẬN 6\nĐẢNG ỦY PHƯỜNG 1\nSố 147-CV/ĐU",
            "ĐẢNG ỦY PHƯỜNG 1 QUẬN ỦY QUẬN 6",
        ),
        (
            "ĐẢNG BỘ\nQUẬN 6\nĐẢNG ỦY\nPHƯỜNG 1\nSố 137-CV/ĐU",
            "ĐẢNG ỦY PHƯỜNG 1 ĐẢNG BỘ QUẬN 6",
        ),
        (
            "QUẬN ỦY - Q.6\nĐẢNG ỦY: P.1\nSố 126-CV/ĐU",
            "ĐẢNG ỦY PHƯỜNG 1 QUẬN ỦY QUẬN 6",
        ),
        (
            "ĐẢNG BỘ QUẬN 6\nĐẢNG CỘNG SẢN VIỆT NAM\nĐẢNG ỦY PHƯỜNG 1\nSố 125-CV/ĐU",
            "ĐẢNG ỦY PHƯỜNG 1 ĐẢNG BỘ QUẬN 6",
        ),
        (
            "QUẬN ỦY QUẬN 6\nĐẢNG CỘNG SẢN VIỆT NAM\nĐẢNG ỦY PHƯỜNG 1\nSố 85-CV/ĐU",
            "ĐẢNG ỦY PHƯỜNG 1 QUẬN ỦY QUẬN 6",
        ),
    ],
)
def test_supplied_failure_family_headers_resolve_per_document(
    header: str,
    expected: str,
) -> None:
    assert _author(header) == expected




@pytest.mark.parametrize(
    ("document_number", "parent_header", "expected"),
    [
        ("153", "ĐẢNG BỘ QUẬN 6", "ĐẢNG ỦY PHƯỜNG 1 ĐẢNG BỘ QUẬN 6"),
        ("147", "QUẬN ỦY QUẬN 6", "ĐẢNG ỦY PHƯỜNG 1 QUẬN ỦY QUẬN 6"),
        ("145", "QUẬN ỦY QUẬN 6", "ĐẢNG ỦY PHƯỜNG 1 QUẬN ỦY QUẬN 6"),
        ("137", "ĐẢNG BỘ QUẬN 6", "ĐẢNG ỦY PHƯỜNG 1 ĐẢNG BỘ QUẬN 6"),
        ("126", "QUẬN ỦY QUẬN 6", "ĐẢNG ỦY PHƯỜNG 1 QUẬN ỦY QUẬN 6"),
        ("125", "ĐẢNG BỘ QUẬN 6", "ĐẢNG ỦY PHƯỜNG 1 ĐẢNG BỘ QUẬN 6"),
        ("117", "ĐẢNG BỘ QUẬN 6", "ĐẢNG ỦY PHƯỜNG 1 ĐẢNG BỘ QUẬN 6"),
        ("74", "ĐẢNG BỘ QUẬN 6", "ĐẢNG ỦY PHƯỜNG 1 ĐẢNG BỘ QUẬN 6"),
        ("105", "ĐẢNG BỘ QUẬN 6", "ĐẢNG ỦY PHƯỜNG 1 ĐẢNG BỘ QUẬN 6"),
        ("103", "ĐẢNG BỘ QUẬN 6", "ĐẢNG ỦY PHƯỜNG 1 ĐẢNG BỘ QUẬN 6"),
        ("99", "ĐẢNG BỘ QUẬN 6", "ĐẢNG ỦY PHƯỜNG 1 ĐẢNG BỘ QUẬN 6"),
        ("88", "ĐẢNG BỘ QUẬN 6", "ĐẢNG ỦY PHƯỜNG 1 ĐẢNG BỘ QUẬN 6"),
        ("86", "ĐẢNG BỘ QUẬN 6", "ĐẢNG ỦY PHƯỜNG 1 ĐẢNG BỘ QUẬN 6"),
        ("85", "QUẬN ỦY QUẬN 6", "ĐẢNG ỦY PHƯỜNG 1 QUẬN ỦY QUẬN 6"),
    ],
)
def test_all_supplied_corrected_records_are_locked_as_regression_fixtures(
    document_number: str,
    parent_header: str,
    expected: str,
) -> None:
    header = (
        f"{parent_header}\n"
        "ĐẢNG ỦY PHƯỜNG 1\n"
        f"Số {document_number}-CV/ĐU\n"
        "V/v nội dung công văn"
    )
    assert _author(header) == expected


def test_same_dossier_can_alternate_parent_kind_without_state_leak() -> None:
    parser = _parser()
    common = """
    Số 99-CV/ĐU
    V/v kiểm tra công tác
    Kính gửi: Các chi bộ trực thuộc
    """

    expected = [
        "ĐẢNG ỦY PHƯỜNG 1 ĐẢNG BỘ QUẬN 6",
        "ĐẢNG ỦY PHƯỜNG 1 QUẬN ỦY QUẬN 6",
        "ĐẢNG ỦY PHƯỜNG 1 ĐẢNG BỘ QUẬN 6",
        "ĐẢNG ỦY PHƯỜNG 1 QUẬN ỦY QUẬN 6",
    ]
    headers = [
        "ĐẢNG BỘ QUẬN 6\nĐẢNG ỦY PHƯỜNG 1",
        "QUẬN ỦY QUẬN 6\nĐẢNG ỦY PHƯỜNG 1",
        "ĐẢNG BỘ QUẬN 6\nĐẢNG ỦY PHƯỜNG 1",
        "QUẬN ỦY QUẬN 6\nĐẢNG ỦY PHƯỜNG 1",
    ]

    actual = []
    for header in headers:
        parsed = parser.parse(
            common,
            source=DataSource.PADDLE_OCR,
            source_confidence=0.95,
            author_evidence_text=header,
        )
        actual.append(parsed.author)

    assert actual == expected


def test_duplicate_phuong_token_is_normalized_once() -> None:
    assert _author(
        "ĐẢNG ỦY PHƯỜNG PHƯỜNG 1 ĐẢNG BỘ QUẬN 6"
    ) == "ĐẢNG ỦY PHƯỜNG 1 ĐẢNG BỘ QUẬN 6"


def test_duplicate_quan_token_is_normalized_once() -> None:
    assert _author(
        "QUẬN ỦY QUẬN QUẬN 6\nĐẢNG ỦY PHƯỜNG 1"
    ) == "ĐẢNG ỦY PHƯỜNG 1 QUẬN ỦY QUẬN 6"


def test_single_letter_number_ocr_artifact_is_not_accepted_as_unit() -> None:
    assert _author(
        "ĐẢNG BỘ QUẬN G\nĐẢNG ỦY PHƯỜNG I\nSố 99-CV/ĐU"
    ) == ""


def test_document_number_is_hard_boundary_for_parent_body_reference() -> None:
    header = """
    ĐẢNG ỦY PHƯỜNG 1
    Số 99-CV/ĐU
    V/v xin ý kiến QUẬN ỦY QUẬN 6 về công tác cán bộ
    Kính gửi: Ban Tổ chức Quận ủy Quận 6
    """
    assert _author(header) == ""


def test_header_parent_before_number_remains_authoritative() -> None:
    header = """
    ĐẢNG BỘ QUẬN 6
    ĐẢNG ỦY PHƯỜNG 1
    Số 99-CV/ĐU
    V/v xin ý kiến QUẬN ỦY QUẬN 6
    """
    assert _author(header) == "ĐẢNG ỦY PHƯỜNG 1 ĐẢNG BỘ QUẬN 6"


def test_conflicting_parent_kinds_do_not_default_to_quan_uy() -> None:
    ambiguous = """
    ĐẢNG BỘ QUẬN 6
    QUẬN ỦY QUẬN 6
    ĐẢNG ỦY PHƯỜNG 1
    Số 99-CV/ĐU
    """
    assert _author(ambiguous) == ""


def test_existing_author_rescue_requires_same_parent_kind_hint() -> None:
    existing = "ĐẢNG ỦY PHƯỜNG 1 ĐẢNG BỘ QUẬN 6"
    assert existing_author_matches_pdf_evidence(
        existing,
        "ĐẢNG ỦY PHƯỜNG 1\nĐẢNG BỘ QUẬN\nSố 99-CV/ĐU",
    )


def test_existing_author_is_not_rescued_from_local_party_alone() -> None:
    existing = "ĐẢNG ỦY PHƯỜNG 1 ĐẢNG BỘ QUẬN 6"
    assert not existing_author_matches_pdf_evidence(
        existing,
        "ĐẢNG ỦY PHƯỜNG 1\nSố 99-CV/ĐU",
    )


def test_existing_dang_bo_cannot_rescue_quan_uy_hint() -> None:
    existing = "ĐẢNG ỦY PHƯỜNG 1 ĐẢNG BỘ QUẬN 6"
    assert not existing_author_matches_pdf_evidence(
        existing,
        "ĐẢNG ỦY PHƯỜNG 1\nQUẬN ỦY QUẬN\nSố 99-CV/ĐU",
    )


def test_existing_quan_uy_cannot_rescue_dang_bo_hint() -> None:
    existing = "ĐẢNG ỦY PHƯỜNG 1 QUẬN ỦY QUẬN 6"
    assert not existing_author_matches_pdf_evidence(
        existing,
        "ĐẢNG ỦY PHƯỜNG 1\nĐẢNG BỘ QUẬN\nSố 99-CV/ĐU",
    )


def test_pdf_header_overwrites_stale_wrong_parent_kind_on_form() -> None:
    parser = _parser()
    parsed = parser.parse(
        """
        Số 153-CV/ĐU
        V/v nhắc các chi bộ thực hiện quy trình kiểm tra, giám sát
        Kính gửi: Các chi bộ trực thuộc
        """,
        source=DataSource.PADDLE_OCR,
        source_confidence=0.96,
        existing_form=FormSnapshot(
            document_number="153",
            symbol="CV/ĐU",
            document_type="Công văn",
            abstract="V/v nhắc các chi bộ thực hiện quy trình kiểm tra, giám sát",
            author="ĐẢNG ỦY PHƯỜNG 1 QUẬN ỦY QUẬN 6",
        ),
        author_evidence_text="ĐẢNG BỘ QUẬN 6\nĐẢNG ỦY PHƯỜNG 1",
    )
    assert parsed.author == "ĐẢNG ỦY PHƯỜNG 1 ĐẢNG BỘ QUẬN 6"
    assert "existing-form-conflict-ignored" in parsed.author_source_text


class _FourCropPipeline:
    def prepare_author_header_crops(
        self,
        source_image: Path,
        artifact_dir: Path,
    ) -> list[Path]:
        del source_image
        return [
            artifact_dir / "core.png",
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
        del crop, mode, target_width
        return output_path


class _DangBoConsensusOcr:
    def recognize_header_candidates(self, image_path: Path) -> list[OcrResult]:
        if "1-enhanced" in image_path.name:
            return [
                OcrResult(
                    raw_text="ĐẢNG BỘ QUẬN 6\nĐẢNG ỦY PHƯỜNG 1",
                    confidence=0.95,
                    engine="paddle",
                ),
                OcrResult(
                    raw_text="ĐẢNG BỘ QUẬN 6\nĐẢNG ỦY PHƯỜNG 1",
                    confidence=0.91,
                    engine="tesseract-vie",
                ),
            ]
        if "2-enhanced" in image_path.name:
            return [
                OcrResult(
                    raw_text="QUẬN ỦY QUẬN 6\nĐẢNG ỦY PHƯỜNG 1",
                    confidence=0.86,
                    engine="paddle",
                )
            ]
        return []


def test_consensus_prefers_two_engine_dang_bo_over_single_wrong_quan_uy(
    tmp_path: Path,
) -> None:
    extractor = DocumentTextExtractor(
        _FourCropPipeline(),  # type: ignore[arg-type]
        _DangBoConsensusOcr(),  # type: ignore[arg-type]
        tmp_path,
    )
    recovered = extractor._recover_author_header(
        tmp_path / "page.png",
        tmp_path,
    )
    assert _author(recovered) == "ĐẢNG ỦY PHƯỜNG 1 ĐẢNG BỘ QUẬN 6"


class _ThresholdBreaksTieOcr:
    def recognize_header_candidates(self, image_path: Path) -> list[OcrResult]:
        name = image_path.name
        if "enhanced" in name:
            if "1-enhanced" in name:
                return [
                    OcrResult(
                        raw_text="ĐẢNG BỘ QUẬN 6\nĐẢNG ỦY PHƯỜNG 1",
                        confidence=0.91,
                        engine="paddle",
                    )
                ]
            if "2-enhanced" in name:
                return [
                    OcrResult(
                        raw_text="QUẬN ỦY QUẬN 6\nĐẢNG ỦY PHƯỜNG 1",
                        confidence=0.91,
                        engine="paddle",
                    )
                ]
            return []
        if "threshold" in name:
            return [
                OcrResult(
                    raw_text="ĐẢNG BỘ QUẬN 6\nĐẢNG ỦY PHƯỜNG 1",
                    confidence=0.94,
                    engine="tesseract-vie",
                )
            ]
        return []


def test_threshold_pass_breaks_close_parent_kind_tie(tmp_path: Path) -> None:
    extractor = DocumentTextExtractor(
        _FourCropPipeline(),  # type: ignore[arg-type]
        _ThresholdBreaksTieOcr(),  # type: ignore[arg-type]
        tmp_path,
    )
    recovered = extractor._recover_author_header(
        tmp_path / "page.png",
        tmp_path,
    )
    assert _author(recovered) == "ĐẢNG ỦY PHƯỜNG 1 ĐẢNG BỘ QUẬN 6"


class _PermanentTieOcr:
    def recognize_header_candidates(self, image_path: Path) -> list[OcrResult]:
        if "1-" in image_path.name:
            return [
                OcrResult(
                    raw_text="ĐẢNG BỘ QUẬN 6\nĐẢNG ỦY PHƯỜNG 1",
                    confidence=0.92,
                    engine="paddle",
                )
            ]
        if "2-" in image_path.name:
            return [
                OcrResult(
                    raw_text="QUẬN ỦY QUẬN 6\nĐẢNG ỦY PHƯỜNG 1",
                    confidence=0.92,
                    engine="paddle",
                )
            ]
        return []


def test_unresolved_parent_kind_tie_never_chooses_by_order(tmp_path: Path) -> None:
    extractor = DocumentTextExtractor(
        _FourCropPipeline(),  # type: ignore[arg-type]
        _PermanentTieOcr(),  # type: ignore[arg-type]
        tmp_path,
    )
    recovered = extractor._recover_author_header(
        tmp_path / "page.png",
        tmp_path,
    )
    assert recovered == ""


class _ComplementaryOcr:
    def recognize_header_candidates(self, image_path: Path) -> list[OcrResult]:
        if "1-enhanced" in image_path.name:
            return [
                OcrResult(
                    raw_text="ĐẢNG ỦY PHƯỜNG 1",
                    confidence=0.94,
                    engine="paddle",
                )
            ]
        if "2-enhanced" in image_path.name:
            return [
                OcrResult(
                    raw_text="ĐẢNG BỘ QUẬN 6",
                    confidence=0.95,
                    engine="tesseract-vie",
                )
            ]
        return []


def test_complementary_crops_still_merge_when_not_conflicting(tmp_path: Path) -> None:
    extractor = DocumentTextExtractor(
        _FourCropPipeline(),  # type: ignore[arg-type]
        _ComplementaryOcr(),  # type: ignore[arg-type]
        tmp_path,
    )
    recovered = extractor._recover_author_header(
        tmp_path / "page.png",
        tmp_path,
    )
    assert _author(recovered) == "ĐẢNG ỦY PHƯỜNG 1 ĐẢNG BỘ QUẬN 6"


def test_old_unversioned_author_cache_is_ignored_and_new_cache_is_bound_to_pdf_hash(
    tmp_path: Path,
) -> None:
    extractor = DocumentTextExtractor(
        _FourCropPipeline(),  # type: ignore[arg-type]
        _ComplementaryOcr(),  # type: ignore[arg-type]
        tmp_path,
    )
    (tmp_path / "author-header-ocr.txt").write_text(
        "QUẬN ỦY QUẬN 6\nĐẢNG ỦY PHƯỜNG 1",
        encoding="utf-8",
    )
    assert extractor._load_author_header_cache(tmp_path, "hash-a") == ""

    correct = "ĐẢNG BỘ QUẬN 6\nĐẢNG ỦY PHƯỜNG 1"
    extractor._save_author_header_cache(tmp_path, "hash-a", correct)
    assert extractor._load_author_header_cache(tmp_path, "hash-a") == correct
    assert extractor._load_author_header_cache(tmp_path, "hash-b") == ""


def test_office_rule_is_unchanged() -> None:
    assert _author(
        "ĐẢNG ỦY PHƯỜNG BÌNH TIÊN\nVĂN PHÒNG\nSố 01-CV/VP"
    ) == "VĂN PHÒNG ĐẢNG ỦY PHƯỜNG BÌNH TIÊN"
