from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, cast

from cataloging_tool.domain.enums import DataSource
from cataloging_tool.domain.models import OcrLine, OcrResult

from .document_header import (
    build_canonical_document_header_details,
    cong_van_title_is_clean,
    cong_van_title_looks_truncated,
    document_header_score,
    extract_cong_van_title,
)
from .metadata import canonical_author_from_text, extract_signer_name
from .normalizer import fold_vietnamese
from .ocr import (
    OcrEngine,
    save_ocr_result,
    score_ocr_result,
    text_has_document_header,
    vietnamese_text_quality,
)
from .pdf_pipeline import PdfPipeline, RenderedPage
from .report_title import (
    choose_better_report_title,
    extract_report_title_block,
    extract_special_report_title,
    recover_special_report_title_from_candidates,
    report_abstract_is_garbage,
    report_title_needs_recovery,
    report_title_score,
    special_report_title_score,
)

logger = logging.getLogger(__name__)

OCR_CACHE_VERSION = "0.1.27.3-cong-van-v13"
CV_HEADER_CACHE_VERSION = "0.1.27.4.16-document-header-v16"
AUTHOR_HEADER_CACHE_VERSION = "0.1.27.4.14-author-header-v4"


@dataclass(frozen=True, slots=True)
class ExtractedDocumentText:
    text: str
    source: DataSource
    confidence: float
    rendered: RenderedPage | None = None
    ocr_result: OcrResult | None = None
    ocr_text_path: Path | None = None
    is_landscape: bool = False
    special_report_title: str = ""
    header_evidence_text: str = ""
    author_evidence_text: str = ""
    cv_number_support: int = 0
    cv_number_score: float = 0.0
    cv_number_candidate_count: int = 0
    signature_evidence_text: str = ""


class DocumentTextExtractor:
    def __init__(
        self,
        pdf_pipeline: PdfPipeline,
        ocr_engine: OcrEngine,
        artifact_root: Path,
        *,
        reuse_ocr_cache: bool = True,
        direct_viewer_image: bool = True,
    ) -> None:
        self.pdf_pipeline = pdf_pipeline
        self.ocr_engine = ocr_engine
        self.artifact_root = artifact_root
        self.reuse_ocr_cache = reuse_ocr_cache
        self.direct_viewer_image = direct_viewer_image

    def extract(
        self,
        pdf_path: Path,
        record_key: str,
        *,
        preferred_text: str = "",
        source_image: Path | None = None,
        document_symbol_hint: str = "",
        document_type_hint: str = "",
        document_date_hint: str = "",
        metadata_recovery: bool = False,
        force_metadata_recovery: bool = False,
        signature_source_image: Path | None = None,
        signer_name_hint: str = "",
        stage_callback: Callable[[str, str], None] | None = None,
    ) -> ExtractedDocumentText:
        def stage(code: str, message: str) -> None:
            if stage_callback is not None:
                stage_callback(code, message)

        is_landscape = self._detect_landscape(pdf_path, source_image)
        signature_evidence = ""
        if metadata_recovery and not signer_name_hint.strip():
            stage("SIGNATURE", "Đọc vùng chữ ký trang cuối")
            signature_evidence = self._recover_signature_evidence(
                pdf_path,
                record_key,
                source_image=source_image,
                signature_source_image=signature_source_image,
            )

        # A PDF.js text layer preserves Vietnamese accents better than OCR.
        if (
            not force_metadata_recovery
            and preferred_text
            and self.pdf_pipeline.looks_usable_text(preferred_text)
        ):
            stage("PDF TEXT", "Dùng text layer từ viewer")
            return ExtractedDocumentText(
                text=preferred_text,
                source=DataSource.PDF_TEXT,
                confidence=0.995,
                is_landscape=is_landscape,
                special_report_title=extract_report_title_block(preferred_text, document_date=document_date_hint),
                header_evidence_text=preferred_text,
                author_evidence_text=preferred_text,
                signature_evidence_text=signature_evidence,
            )

        if source_image is None or not self.direct_viewer_image:
            layer = self.pdf_pipeline.extract_text(pdf_path)
            if layer.usable and not force_metadata_recovery:
                stage("PDF TEXT", "Dùng text layer từ PDF")
                return ExtractedDocumentText(
                    text=layer.text,
                    source=DataSource.PDF_TEXT,
                    confidence=0.98,
                    is_landscape=is_landscape,
                    special_report_title=extract_report_title_block(layer.text, document_date=document_date_hint),
                    header_evidence_text=layer.text,
                    author_evidence_text=layer.text,
                    signature_evidence_text=signature_evidence,
                )

        if source_image is not None and self.direct_viewer_image:
            rendered = self.pdf_pipeline.prepare_image_first_page(
                source_image,
                record_key,
                header_ratio=0.55,
            )
        else:
            rendered = self.pdf_pipeline.render_first_page(
                pdf_path,
                record_key,
                header_ratio=0.55,
            )

        artifact_dir = self.artifact_root / record_key
        input_hash = self._sha256(rendered.full_page)
        cached = None if force_metadata_recovery else self._load_cache(artifact_dir, input_hash)
        if cached is not None:
            stage("OCR CACHE", "Dùng lại kết quả OCR cache")
            logger.info("Dùng lại OCR cache cho %s", record_key)
            selected = cached
            report_header_path = artifact_dir / "report-header-ocr.txt"
            document_header_path = artifact_dir / "document-header-ocr.txt"
            header_evidence = (
                report_header_path.read_text(encoding="utf-8")
                if report_header_path.exists()
                else document_header_path.read_text(encoding="utf-8")
                if document_header_path.exists()
                else ""
            )
            cv_hint = (
                self._is_cong_van_hint(document_symbol_hint, document_type_hint)
                or self._looks_like_cong_van_text(selected.raw_text)
                or self._looks_like_cong_van_text(header_evidence)
            )
            weak_unidentified_header = (
                not document_symbol_hint.strip()
                and not document_type_hint.strip()
                and (
                    not text_has_document_header(selected.raw_text)
                    or score_ocr_result(selected) < 0.72
                    or vietnamese_text_quality(selected.raw_text) < 0.55
                )
            )
            # Author OCR has its own versioned cache. Older author-header.txt
            # files are deliberately ignored because they may contain exactly
            # the ĐẢNG BỘ/QUẬN ỦY mix-up fixed in 0.1.27.4.14.
            author_evidence = self._load_author_header_cache(
                artifact_dir, input_hash
            )
            author_source_image = source_image or rendered.full_page
            if not author_evidence and author_source_image is not None:
                stage("AUTHOR RECOVERY", "Focused OCR cơ quan ban hành")
                recovered_author = self._recover_author_header(
                    author_source_image,
                    artifact_dir,
                    seed_text="\n".join(
                        part
                        for part in (selected.raw_text, header_evidence)
                        if part
                    ),
                )
                if recovered_author:
                    author_evidence = recovered_author
                    self._save_author_header_cache(
                        artifact_dir, input_hash, recovered_author
                    )
            if not author_evidence:
                author_evidence = selected.raw_text
            cv_meta = self._load_document_header_meta(artifact_dir)
            metadata_source_image = source_image or rendered.full_page
            if (
                metadata_source_image is not None
                and (metadata_recovery or cv_hint or weak_unidentified_header)
                and (
                    (metadata_recovery and not cv_meta)
                    or not header_evidence
                    or (cv_hint and int(cv_meta.get("number_support", 0)) < 2)
                    or (cv_hint and float(cv_meta.get("title_score", 0.0)) < 0.70)
                )
            ):
                header_evidence = self._recover_document_header(
                    metadata_source_image,
                    artifact_dir,
                    document_symbol_hint=document_symbol_hint,
                    document_type_hint=document_type_hint,
                    force_cong_van=cv_hint,
                    force_full_metadata=metadata_recovery,
                )
                cv_meta = self._load_document_header_meta(artifact_dir)
                if header_evidence:
                    document_header_path.write_text(header_evidence, encoding="utf-8")
            report_hint = (
                self._is_bao_cao_hint(document_symbol_hint, document_type_hint)
                or self._looks_like_bao_cao_text(selected.raw_text)
                or self._looks_like_bao_cao_text(header_evidence)
            )
            saved_report_title_path = artifact_dir / "special-report-title.txt"
            saved_report_title = (
                saved_report_title_path.read_text(encoding="utf-8").strip()
                if saved_report_title_path.exists()
                else ""
            )
            report_title = choose_better_report_title(
                extract_report_title_block(
                    selected.raw_text, document_date=document_date_hint
                ),
                extract_report_title_block(
                    header_evidence, document_date=document_date_hint
                ),
                saved_report_title,
            )
            # A completed dedicated crop is persisted in special-report-title.txt.
            # Re-running the same expensive Paddle/Tesseract recovery on every
            # cache hit added minutes without adding any new evidence. Recover
            # again only when the persisted title is absent or still incomplete.
            if (
                metadata_source_image is not None
                and report_hint
                and (metadata_recovery or report_title_needs_recovery(report_title))
            ):
                recovered = self._recover_special_report_title(
                    metadata_source_image,
                    artifact_dir,
                    document_date_hint=document_date_hint,
                )
                if recovered is not None:
                    recovered_title = extract_report_title_block(
                        recovered.raw_text, document_date=document_date_hint
                    )
                    report_title = choose_better_report_title(
                        report_title, recovered_title
                    )
                    header_evidence = recovered.raw_text
                    report_header_path.write_text(header_evidence, encoding="utf-8")
            if report_title:
                (artifact_dir / "special-report-title.txt").write_text(
                    report_title, encoding="utf-8"
                )
            text_path = artifact_dir / "raw-ocr.txt"
            return ExtractedDocumentText(
                text=selected.raw_text,
                source=(
                    DataSource.TESSERACT_OCR
                    if "tesseract" in selected.engine
                    else DataSource.PADDLE_OCR
                ),
                confidence=selected.confidence,
                rendered=rendered,
                ocr_result=selected,
                ocr_text_path=text_path if text_path.exists() else None,
                is_landscape=is_landscape,
                special_report_title=report_title,
                header_evidence_text=header_evidence or selected.raw_text,
                author_evidence_text=author_evidence or selected.raw_text,
                cv_number_support=int(cv_meta.get("number_support", 0)),
                cv_number_score=float(cv_meta.get("number_score", 0.0)),
                cv_number_candidate_count=int(cv_meta.get("number_candidate_count", 0)),
                signature_evidence_text=signature_evidence,
            )

        stage("OCR HEADER", "OCR vùng đầu trang")
        header_processed = self.pdf_pipeline.preprocess_for_ocr(
            rendered.header_crop,
            artifact_dir / "header-preprocessed.png",
            mode="enhanced",
        )
        header_result = self.ocr_engine.recognize(header_processed)
        candidates = [header_result]

        # Run the expensive threshold variant only for visibly weak OCR.
        if (
            score_ocr_result(header_result) < 0.68
            or vietnamese_text_quality(header_result.raw_text) < 0.50
        ):
            threshold_header = self.pdf_pipeline.preprocess_for_ocr(
                rendered.header_crop,
                artifact_dir / "header-threshold.png",
                mode="threshold",
            )
            candidates.append(self.ocr_engine.recognize(threshold_header))

        selected = max(candidates, key=score_ocr_result)

        # Full-page OCR is a last resort only. Most fields live in the header.
        if not text_has_document_header(selected.raw_text):
            full_processed = self.pdf_pipeline.preprocess_for_ocr(
                rendered.full_page,
                artifact_dir / "full-page-preprocessed.png",
                mode="enhanced",
            )
            full_result = self.ocr_engine.recognize(full_processed)
            if score_ocr_result(full_result) > score_ocr_result(selected):
                selected = full_result

        # Every Công văn raster record gets a focused top-header pass. The
        # canonical result contains only the document's own number/symbol and the
        # italic abstract below it, never cited instruments from the body.
        cv_hint = (
            self._is_cong_van_hint(document_symbol_hint, document_type_hint)
            or self._looks_like_cong_van_text(selected.raw_text)
        )
        # Unidentified records with weak generic OCR must also receive the
        # focused header pass. Otherwise handwritten numbers and short italic
        # abstracts are never recovered when stale form metadata is empty.
        weak_unidentified_header = (
            not document_symbol_hint.strip()
            and not document_type_hint.strip()
            and (
                not text_has_document_header(selected.raw_text)
                or score_ocr_result(selected) < 0.72
                or vietnamese_text_quality(selected.raw_text) < 0.55
            )
        )
        document_header_evidence = ""
        metadata_source_image = source_image or rendered.full_page
        if metadata_source_image is not None and (metadata_recovery or weak_unidentified_header or cv_hint):
            document_header_evidence = self._recover_document_header(
                metadata_source_image,
                artifact_dir,
                document_symbol_hint=document_symbol_hint,
                document_type_hint=document_type_hint,
                force_cong_van=cv_hint,
                force_full_metadata=(metadata_recovery or force_metadata_recovery),
            )
            if document_header_evidence:
                (artifact_dir / "document-header-ocr.txt").write_text(
                    document_header_evidence, encoding="utf-8"
                )
                logger.info("Đã đối chiếu đầu Công văn bằng crop chuyên dụng")

        # Author is mandatory and this dossier legitimately mixes two parent
        # labels (ĐẢNG BỘ QUẬN / QUẬN ỦY QUẬN).  Therefore raster documents
        # always get one small focused author pass for the current cache
        # version, even when whole-page OCR appears plausible.  This costs only
        # a few tiny crops and is then cached per PDF hash.
        author_evidence = self._load_author_header_cache(artifact_dir, input_hash)
        author_source_image = source_image or rendered.full_page
        if not author_evidence and author_source_image is not None:
            stage("AUTHOR RECOVERY", "Focused OCR cơ quan ban hành")
            recovered_author = self._recover_author_header(
                author_source_image,
                artifact_dir,
                seed_text="\n".join(
                    part
                    for part in (selected.raw_text, document_header_evidence)
                    if part
                ),
            )
            if recovered_author:
                author_evidence = recovered_author
                self._save_author_header_cache(
                    artifact_dir, input_hash, recovered_author
                )
        if not author_evidence:
            author_evidence = selected.raw_text

        # Every BC/... raster record gets one dedicated title recovery pass.
        # Generic OCR can return a plausible but truncated title, so checking
        # only for an empty value caused alternating success/failure on visually
        # identical reports.  The recovered crop is bounded before comparison.
        report_hint = (
            self._is_bao_cao_hint(document_symbol_hint, document_type_hint)
            or self._looks_like_bao_cao_text(selected.raw_text)
            or self._looks_like_bao_cao_text(document_header_evidence)
        )
        report_title = extract_report_title_block(
            selected.raw_text, document_date=document_date_hint
        )
        header_evidence = ""
        report_title_is_strong = (
            bool(report_title)
            and not report_title_needs_recovery(report_title)
            and report_title_score(report_title) >= 0.94
            and vietnamese_text_quality(report_title) >= 0.62
        )
        if (
            metadata_source_image is not None
            and report_hint
            and (metadata_recovery or force_metadata_recovery or not report_title_is_strong)
        ):
            stage("OCR TITLE", "Focused OCR khối tiêu đề/trích yếu")
            recovered = self._recover_special_report_title(
                metadata_source_image,
                artifact_dir,
                document_date_hint=document_date_hint,
            )
            if recovered is not None:
                recovered_title = extract_report_title_block(
                    recovered.raw_text, document_date=document_date_hint
                )
                better_title = choose_better_report_title(
                    report_title, recovered_title
                )
                if better_title:
                    report_title = better_title
                    header_evidence = recovered.raw_text
                    (artifact_dir / "report-header-ocr.txt").write_text(
                        header_evidence, encoding="utf-8"
                    )
                    logger.info(
                        "Đã đối chiếu tiêu đề Báo cáo bằng crop chuyên dụng"
                    )

        if report_title:
            (artifact_dir / "special-report-title.txt").write_text(
                report_title, encoding="utf-8"
            )

        text_path, _ = save_ocr_result(selected, artifact_dir)
        self._save_cache(artifact_dir, input_hash, selected)
        source = (
            DataSource.TESSERACT_OCR
            if "tesseract" in selected.engine
            else DataSource.PADDLE_OCR
        )
        cv_meta = self._load_document_header_meta(artifact_dir)
        return ExtractedDocumentText(
            text=selected.raw_text,
            source=source,
            confidence=selected.confidence,
            rendered=rendered,
            ocr_result=selected,
            ocr_text_path=text_path,
            is_landscape=is_landscape,
            special_report_title=report_title,
            header_evidence_text=(
                header_evidence or document_header_evidence or selected.raw_text
            ),
            author_evidence_text=author_evidence,
            cv_number_support=int(cv_meta.get("number_support", 0)),
            cv_number_score=float(cv_meta.get("number_score", 0.0)),
            cv_number_candidate_count=int(cv_meta.get("number_candidate_count", 0)),
            signature_evidence_text=signature_evidence,
        )


    @staticmethod
    def _has_author_evidence(value: str) -> bool:
        return bool(
            canonical_author_from_text(
                value,
                value,
                default_author="",
            )
        )

    @staticmethod
    def _author_engine_family(engine: str) -> str:
        key = (engine or "unknown").lower()
        if "paddle" in key:
            return "paddle"
        if "tesseract" in key:
            return "tesseract"
        if "pdf" in key or "text" in key:
            return "text"
        return key or "unknown"

    def _load_author_header_cache(self, artifact_dir: Path, input_hash: str) -> str:
        if not self.reuse_ocr_cache:
            return ""
        meta_path = artifact_dir / "author-header-meta.json"
        text_path = artifact_dir / "author-header-ocr.txt"
        if not meta_path.exists() or not text_path.exists():
            return ""
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return ""
            if payload.get("cache_version") != AUTHOR_HEADER_CACHE_VERSION:
                return ""
            if payload.get("input_sha256") != input_hash:
                return ""
            evidence = text_path.read_text(encoding="utf-8").strip()
        except Exception:
            return ""
        return evidence if self._has_author_evidence(evidence) else ""

    def _save_author_header_cache(
        self,
        artifact_dir: Path,
        input_hash: str,
        evidence: str,
    ) -> None:
        if not evidence or not self._has_author_evidence(evidence):
            return
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "author-header-ocr.txt").write_text(
            evidence, encoding="utf-8"
        )
        (artifact_dir / "author-header-meta.json").write_text(
            json.dumps(
                {
                    "cache_version": AUTHOR_HEADER_CACHE_VERSION,
                    "input_sha256": input_hash,
                    "canonical_author": canonical_author_from_text(
                        evidence,
                        evidence,
                        default_author="",
                    ),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _recover_author_header(
        self,
        source_image: Path,
        artifact_dir: Path,
        *,
        seed_text: str = "",
    ) -> str:
        """Recover the current document's issuer from focused top-left OCR.

        Reliability rules are intentionally asymmetric:
        - focused crops outrank whole-page seed text;
        - agreement across engines/crops increases support;
        - ĐẢNG BỘ QUẬN and QUẬN ỦY QUẬN are distinct facts, never aliases;
        - a close conflict triggers the threshold pass instead of choosing by
          candidate order;
        - if the conflict remains unresolved, return no complete author rather
          than writing a wrong parent organization.
        """
        crops = self.pdf_pipeline.prepare_author_header_crops(
            source_image, artifact_dir
        )
        if not crops:
            return ""

        evidence_parts: list[str] = []
        seen_parts: set[str] = set()
        complete_candidates: list[dict[str, object]] = []

        def remember(value: str) -> None:
            raw = (value or "").strip()
            if not raw:
                return
            key = fold_vietnamese(raw)
            if key in seen_parts:
                return
            seen_parts.add(key)
            evidence_parts.append(raw)

        def add_complete_candidate(
            raw: str,
            result: OcrResult,
            *,
            crop_index: int,
            mode: str,
        ) -> None:
            canonical = canonical_author_from_text(
                raw,
                raw,
                default_author="",
            )
            if not canonical:
                return
            crop_bonus = max(0.0, 0.045 - 0.010 * max(0, crop_index - 1))
            score = (
                score_ocr_result(result)
                + 0.20 * vietnamese_text_quality(raw)
                + crop_bonus
                + (0.025 if mode == "enhanced" else 0.0)
            )
            complete_candidates.append(
                {
                    "canonical": canonical,
                    "raw": raw,
                    "score": float(score),
                    "engine": self._author_engine_family(result.engine),
                    "crop": crop_index,
                    "mode": mode,
                }
            )

        def choose_complete_candidate() -> str:
            if not complete_candidates:
                return ""

            groups: dict[str, list[dict[str, object]]] = {}
            for item in complete_candidates:
                key = fold_vietnamese(str(item["canonical"]))
                groups.setdefault(key, []).append(item)

            ranked: list[tuple[float, int, int, str, list[dict[str, object]]]] = []
            for items in groups.values():
                engines = {str(item["engine"]) for item in items}
                crop_ids = {cast(int, item["crop"]) for item in items}
                max_score = max(cast(float, item["score"]) for item in items)
                support = len(items)
                aggregate = (
                    max_score
                    + 0.075 * max(0, len(engines) - 1)
                    + 0.035 * max(0, len(crop_ids) - 1)
                    + 0.015 * max(0, support - 1)
                )
                ranked.append(
                    (
                        aggregate,
                        len(engines),
                        len(crop_ids),
                        str(items[0]["canonical"]),
                        items,
                    )
                )

            ranked.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3]))
            top = ranked[0]
            top_items = top[4]
            best_raw = str(max(top_items, key=lambda item: cast(float, item["score"]))["raw"])

            if len(ranked) == 1:
                return best_raw

            second = ranked[1]
            margin = top[0] - second[0]

            # Two-engine agreement is the strongest tie-breaker.  Otherwise
            # require either a clear score margin or substantially more crop
            # support.  This avoids an arbitrary choice when one engine reads
            # ĐẢNG BỘ and another reads QUẬN ỦY on the same page.
            if top[1] >= 2 and second[1] < 2:
                return best_raw
            if margin >= 0.16:
                return best_raw
            if top[2] >= second[2] + 2 and margin >= 0.07:
                return best_raw
            return ""

        def merged_complete() -> str:
            merged = "\n".join(evidence_parts)
            if not merged:
                return ""
            # metadata.py now treats a close parent-kind conflict as ambiguous,
            # so this merge is safe for complementary local/parent fragments.
            return merged if self._has_author_evidence(merged) else ""

        def recognize_crop(crop: Path, index: int, mode: str) -> None:
            processed = self.pdf_pipeline.preprocess_for_ocr(
                crop,
                artifact_dir / f"author-header-{index}-{mode}.png",
                mode=mode,
                target_width=3900 if mode == "enhanced" else 3800,
            )
            try:
                recognize_candidates = getattr(
                    self.ocr_engine, "recognize_header_candidates", None
                )
                results = (
                    cast(list[OcrResult], recognize_candidates(processed))
                    if callable(recognize_candidates)
                    else [self.ocr_engine.recognize(processed)]
                )
            except Exception as exc:
                logger.warning(
                    "OCR cơ quan ban hành thất bại (%s/%s): %s",
                    index,
                    mode,
                    exc,
                )
                return

            for result in results:
                raw = result.raw_text.strip()
                if not raw:
                    continue
                remember(raw)
                add_complete_candidate(
                    raw,
                    result,
                    crop_index=index,
                    mode=mode,
                )

        # Whole-page/header seed is supporting evidence only. It is useful for
        # complementary fragments but is never allowed to win a parent-kind
        # conflict over the focused OCR crops.
        remember(seed_text)

        # Pass 1: all focused crops with grayscale enhancement.
        for index, crop in enumerate(crops, start=1):
            recognize_crop(crop, index, "enhanced")

        decisive = choose_complete_candidate()
        if decisive:
            return decisive

        merged = merged_complete()
        if merged:
            return merged

        # Pass 2: high contrast on every crop except the widest body-prone crop.
        # This is intentionally conditional and is only paid when pass 1 did not
        # settle the author.
        threshold_crops = crops[:-1] if len(crops) > 1 else crops
        for index, crop in enumerate(threshold_crops, start=1):
            recognize_crop(crop, index, "threshold")

        decisive = choose_complete_candidate()
        if decisive:
            return decisive

        merged = merged_complete()
        if merged:
            logger.info(
                "Khôi phục Tác giả bằng evidence bổ sung từ %s OCR candidate",
                len(evidence_parts),
            )
            return merged

        logger.warning(
            "Không đủ đồng thuận OCR để xác định chính xác Tác giả; không chọn mặc định"
        )
        return ""

    @staticmethod
    def _is_bao_cao_hint(symbol: str, document_type: str) -> bool:
        symbol_code = (symbol or "").strip().upper().split("/", 1)[0]
        folded_type = (document_type or "").casefold()
        return symbol_code == "BC" or "báo cáo" in folded_type or "bao cao" in folded_type

    @staticmethod
    def _looks_like_bao_cao_text(value: str) -> bool:
        """Detect a report from OCR even when stale form metadata says otherwise."""
        import re
        import unicodedata

        text = unicodedata.normalize("NFD", value or "")
        text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
        text = text.replace("đ", "d").replace("Đ", "D").casefold()
        text = re.sub(r"\s+", " ", text)
        return bool(
            re.search(r"\bbao\s+cao\b", text)
            or re.search(r"\b\d{1,6}\s*[-–—]\s*bc\s*/", text)
            or (
                "tinh hinh, ket qua" in text
                and any(token in text for token in ("stt", "tom tat noi dung", "don vi tinh"))
            )
        )

    @staticmethod
    def _is_cong_van_hint(symbol: str, document_type: str) -> bool:
        symbol_code = (symbol or "").strip().upper().split("/", 1)[0]
        folded_type = (document_type or "").casefold()
        return symbol_code == "CV" or "công văn" in folded_type or "cong van" in folded_type

    @staticmethod
    def _looks_like_cong_van_text(value: str) -> bool:
        import re
        import unicodedata

        text = unicodedata.normalize("NFD", value or "")
        text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
        text = text.replace("đ", "d").replace("Đ", "D").casefold()
        text = re.sub(r"\s+", " ", text)
        return bool(
            re.search(r"\b[0-9oqdilszgeatb|]{1,7}\s*[-–—]\s*(?:[a-z0-9]-)?cv\s*/", text)
            or ("kinh gui" in text and re.search(r"\bve\s+(?:viec|lanh dao|gui|gop y|xac minh)", text))
        )

    @staticmethod
    def _has_report_title(value: str) -> bool:
        return bool(extract_report_title_block(value))

    def _recover_document_header(
        self,
        source_image: Path,
        artifact_dir: Path,
        *,
        document_symbol_hint: str = "",
        document_type_hint: str = "",
        force_cong_van: bool = False,
        force_full_metadata: bool = False,
    ) -> str:
        cv_hint = force_cong_van or self._is_cong_van_hint(
            document_symbol_hint, document_type_hint
        )
        crops = self.pdf_pipeline.prepare_document_header_crops(
            source_image, artifact_dir, cong_van=cv_hint
        )
        raw_candidates: list[str] = []
        known_codes = (
            "KH", "CV", "QĐ", "QD", "BC", "TB", "NQ", "CT", "HD",
            "TTR", "BB", "CTR", "QC", "KL",
        )
        for index, crop in enumerate(crops, start=1):
            # Wide/centre crops recover the complete italic title. Tight crops
            # recover the handwritten number. A Công văn never stops before at
            # least one tight number crop has been compared.
            is_number_crop = crop.name.startswith("document-number-")
            is_title_crop = crop.name.startswith("document-title-")
            modes = ["enhanced"]
            if force_full_metadata or (cv_hint and (is_number_crop or is_title_crop)):
                modes.append("threshold")

            current_best = 0.0
            for mode in modes:
                processed = self.pdf_pipeline.preprocess_for_ocr(
                    crop,
                    artifact_dir / f"document-header-{index}-{mode}.png",
                    mode=mode,
                    target_width=(
                        4400 if is_number_crop
                        else 4200 if is_title_crop
                        else 3800
                    ),
                )
                try:
                    if is_number_crop:
                        recognize_candidates = getattr(
                            self.ocr_engine, "recognize_header_number_candidates", None
                        )
                    else:
                        recognize_candidates = getattr(
                            self.ocr_engine, "recognize_header_candidates", None
                        )
                    results = (
                        cast(list[OcrResult], recognize_candidates(processed))
                        if callable(recognize_candidates)
                        else [self.ocr_engine.recognize(processed)]
                    )
                except Exception as exc:
                    logger.warning(
                        "OCR crop đầu Công văn thất bại (%s/%s): %s",
                        index, mode, exc,
                    )
                    continue

                texts = [item.raw_text for item in results if item.raw_text.strip()]
                raw_candidates.extend(texts)
                current_best = max(
                    current_best,
                    max(
                        (
                            document_header_score(
                                text,
                                symbol_hint=document_symbol_hint,
                                type_hint=document_type_hint,
                                known_codes=known_codes,
                            )
                            for text in texts
                        ),
                        default=0.0,
                    ),
                )

                if cv_hint and is_title_crop and mode == "enhanced":
                    strong_complete = False
                    for candidate_text in texts:
                        title_candidate = extract_cong_van_title(
                            candidate_text,
                            expected_symbol=document_symbol_hint,
                            known_codes=known_codes,
                        )
                        if (
                            title_candidate.value
                            and title_candidate.strong_boundary
                            and cong_van_title_is_clean(title_candidate.value)
                            and not cong_van_title_looks_truncated(title_candidate.value)
                        ):
                            strong_complete = True
                            break
                    if strong_complete:
                        # The enhanced pass already saw both a complete title and
                        # its lower boundary; skip threshold for this crop.
                        break

            # For ordinary non-CV records preserve the former quick exit.
            # Fully unidentified records deliberately inspect every focused crop
            # so number/type/date/title evidence cannot depend on one lucky OCR pass.
            if not cv_hint and not force_full_metadata and current_best >= 0.92:
                break

            if cv_hint and is_number_crop:
                details = build_canonical_document_header_details(
                    raw_candidates,
                    symbol_hint=document_symbol_hint,
                    type_hint=document_type_hint,
                    known_codes=known_codes,
                )
                title = extract_cong_van_title(
                    details.text,
                    expected_number=details.number,
                    expected_symbol=details.symbol,
                    known_codes=known_codes,
                )
                title_is_strong = (
                    bool(title.value)
                    and cong_van_title_is_clean(title.value)
                    and title.strong_boundary
                    and details.title_score >= 0.70
                )
                if details.number_support >= 2 and title_is_strong:
                    break

        details = build_canonical_document_header_details(
            raw_candidates,
            symbol_hint=document_symbol_hint,
            type_hint=document_type_hint,
            known_codes=known_codes,
        )
        if raw_candidates:
            (artifact_dir / "document-header-candidates.txt").write_text(
                "\n\n===== CANDIDATE =====\n\n".join(raw_candidates),
                encoding="utf-8",
            )
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "document-header-meta.json").write_text(
            json.dumps(
                {
                    "cache_version": CV_HEADER_CACHE_VERSION,
                    "number": details.number,
                    "symbol": details.symbol,
                    "number_support": details.number_support,
                    "number_score": details.number_score,
                    "number_candidate_count": details.number_candidate_count,
                    "title_score": details.title_score,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return details.text

    @staticmethod
    def _load_document_header_meta(artifact_dir: Path) -> dict[str, Any]:
        """Load only Công-văn header evidence produced by the current rules.

        The whole-page OCR cache is intentionally left untouched for speed and
        for every non-Công-văn branch.  Older focused-header artefacts may contain
        the exact recurring errors fixed in this release (5218/5224 prefixes,
        body/UI leakage and truncated italic lines), so they must never be trusted
        after the parser changes.  Returning an empty mapping makes the cached
        extraction path rerun only the small Công-văn header crops.
        """
        path = artifact_dir / "document-header-meta.json"
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}
        if payload.get("cache_version") != CV_HEADER_CACHE_VERSION:
            return {}
        return payload

    def _recover_special_report_title(
        self,
        source_image: Path,
        artifact_dir: Path,
        *,
        document_date_hint: str = "",
    ) -> OcrResult | None:
        crops = self.pdf_pipeline.prepare_special_report_title_crops(
            source_image, artifact_dir
        )
        candidates: list[OcrResult] = []
        for index, crop in enumerate(crops, start=1):
            for mode in ("enhanced", "threshold"):
                processed = self.pdf_pipeline.preprocess_for_ocr(
                    crop,
                    artifact_dir / f"report-title-{index}-{mode}.png",
                    mode=mode,
                    target_width=3600,
                )
                try:
                    recognize_candidates = getattr(
                        self.ocr_engine, "recognize_title_candidates", None
                    )
                    results = (
                        cast(list[OcrResult], recognize_candidates(processed))
                        if callable(recognize_candidates)
                        else [self.ocr_engine.recognize(processed)]
                    )
                except Exception as exc:
                    logger.warning(
                        "OCR crop Báo cáo thất bại (%s/%s): %s",
                        index, mode, exc,
                    )
                    continue
                candidates.extend(results)
                if any(report_title_score(item.raw_text) >= 0.97 for item in results):
                    break

        if not candidates:
            return None

        # First prefer any complete bounded title from one crop. If the date
        # and subject were recognised by different crops, combine their evidence
        # into one canonical special-report title.
        ranked = sorted(
            candidates,
            key=lambda item: (
                report_title_score(item.raw_text),
                special_report_title_score(item.raw_text),
                self._special_report_score(item),
                len(extract_report_title_block(
                    item.raw_text, document_date=document_date_hint
                )),
            ),
            reverse=True,
        )
        best = ranked[0]
        best_title = extract_report_title_block(
            best.raw_text, document_date=document_date_hint
        )
        merged_special = recover_special_report_title_from_candidates(
            (item.raw_text for item in candidates),
            document_date=document_date_hint,
        )
        joined_title = extract_report_title_block(
            "\n".join(item.raw_text for item in candidates),
            document_date=document_date_hint,
        )
        chosen_title = choose_better_report_title(
            best_title, merged_special, joined_title
        )
        if chosen_title:
            best = OcrResult(
                raw_text="\n".join(
                    part for part in (best.raw_text, chosen_title) if part
                ),
                confidence=max(item.confidence for item in candidates),
                lines=best.lines,
                engine=f"report-title:{best.engine}",
                duration_ms=sum(item.duration_ms for item in candidates),
            )
            best_title = chosen_title

        (artifact_dir / "special-report-title-ocr.txt").write_text(
            best.raw_text, encoding="utf-8"
        )
        if best_title:
            (artifact_dir / "special-report-title.txt").write_text(
                best_title, encoding="utf-8"
            )
            return best
        return None

    @classmethod
    def _special_report_score(cls, result: OcrResult) -> float:
        import re
        import unicodedata

        text = result.raw_text or ""
        folded = unicodedata.normalize("NFD", text)
        folded = "".join(ch for ch in folded if unicodedata.category(ch) != "Mn")
        folded = folded.replace("đ", "d").replace("Đ", "D").casefold()
        folded = re.sub(r"\s+", " ", folded)
        score = 0.35 * score_ocr_result(result)
        if "bao cao" in folded:
            score += 0.35
        if re.search(r"\b(?:ngay|thang|tuan|quy|nam)\b", folded):
            score += 0.20
        if re.search(r"\bve\b", folded):
            score += 0.20
        if re.search(r"\b\d{1,4}\s*[-–—]\s*bc\s*/", folded):
            score += 0.15
        if "danh sach" in folded or "stt" in folded:
            score += 0.05
        return score

    @staticmethod
    def _combine_ocr_results(base: OcrResult, recovered: OcrResult) -> OcrResult:
        recovered_text = (recovered.raw_text or "").strip()
        base_text = (base.raw_text or "").strip()
        combined_text = "\n".join(
            part for part in (recovered_text, base_text) if part
        )
        return OcrResult(
            raw_text=combined_text,
            confidence=max(base.confidence, recovered.confidence),
            lines=[*recovered.lines, *base.lines],
            engine=f"{base.engine}+report-title:{recovered.engine}",
            duration_ms=base.duration_ms + recovered.duration_ms,
        )


    def _recover_signature_evidence(
        self,
        pdf_path: Path,
        record_key: str,
        *,
        source_image: Path | None,
        signature_source_image: Path | None,
    ) -> str:
        """Read/OCR only the final-page signature area for unknown records."""
        artifact_dir = self.artifact_root / record_key
        artifact_dir.mkdir(parents=True, exist_ok=True)
        cached_path = artifact_dir / "signature-evidence.txt"
        if self.reuse_ocr_cache and cached_path.exists():
            cached = cached_path.read_text(encoding="utf-8").strip()
            if extract_signer_name(cached).value:
                return cached

        # Prefer the PDF text layer from the final page. It is both faster and
        # more accurate than OCR when present.
        final_text = self.pdf_pipeline.extract_last_page_text(pdf_path)
        if extract_signer_name(final_text).value:
            cached_path.write_text(final_text, encoding="utf-8")
            return final_text

        crop: Path | None = None
        if signature_source_image is not None and signature_source_image.exists():
            crop = self.pdf_pipeline.prepare_signature_crop_from_image(
                signature_source_image, record_key
            )
        if crop is None:
            crop = self.pdf_pipeline.render_last_page_signature_crop(
                pdf_path, record_key
            )
        if crop is None and source_image is not None and source_image.exists():
            crop = self.pdf_pipeline.prepare_signature_crop_from_image(
                source_image, record_key
            )
        if crop is None:
            return final_text

        processed = self.pdf_pipeline.preprocess_for_ocr(
            crop,
            artifact_dir / "signature-preprocessed.png",
            mode="enhanced",
            target_width=1800,
        )
        result = self.ocr_engine.recognize(processed)
        evidence = (result.raw_text or "").strip()
        if evidence:
            cached_path.write_text(evidence, encoding="utf-8")
        return evidence or final_text


    @staticmethod
    def _detect_landscape(pdf_path: Path, source_image: Path | None) -> bool:
        """Detect page orientation without adding an OCR pass.

        Viewer screenshots normally contain the first PDF page itself. When a
        real PDF is available, use the first page rectangle. Failure to inspect
        orientation is non-fatal because the parser also recognises the
        ``BÁO CÁO NGÀY/THÁNG...`` heading pattern.
        """
        try:
            if source_image is not None and source_image.exists():
                from PIL import Image

                with Image.open(source_image) as image:
                    return image.width > image.height * 1.10
        except Exception:
            pass
        try:
            import fitz

            with fitz.open(pdf_path) as document:
                if document.page_count < 1:
                    return False
                rect = document.load_page(0).rect
                return rect.width > rect.height * 1.10
        except Exception:
            return False

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _load_cache(self, artifact_dir: Path, input_hash: str) -> OcrResult | None:
        if not self.reuse_ocr_cache:
            return None
        cache_path = artifact_dir / "ocr-cache.json"
        if not cache_path.exists():
            return None
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            if payload.get("cache_version") != OCR_CACHE_VERSION:
                return None
            if payload.get("input_sha256") != input_hash:
                return None
            lines = [
                OcrLine(
                    text=str(item.get("text", "")),
                    confidence=float(item.get("confidence", 0.0)),
                    box=item.get("box"),
                )
                for item in payload.get("lines", [])
            ]
            result = OcrResult(
                raw_text=str(payload.get("raw_text", "")),
                confidence=float(payload.get("confidence", 0.0)),
                lines=lines,
                engine=f"cache:{payload.get('engine', 'ocr')}",
                duration_ms=0,
            )
            if not result.raw_text.strip():
                return None
            return result
        except Exception:
            return None

    def _save_cache(self, artifact_dir: Path, input_hash: str, result: OcrResult) -> None:
        if not self.reuse_ocr_cache:
            return
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "ocr-cache.json").write_text(
            json.dumps(
                {
                    "cache_version": OCR_CACHE_VERSION,
                    "input_sha256": input_hash,
                    "engine": result.engine,
                    "confidence": result.confidence,
                    "raw_text": result.raw_text,
                    "lines": [
                        {
                            "text": line.text,
                            "confidence": line.confidence,
                            "box": line.box,
                        }
                        for line in result.lines
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
