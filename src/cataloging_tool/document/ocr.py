from __future__ import annotations

import csv
import difflib
import json
import logging
import os
import re
import shutil
import subprocess
import time
from collections import OrderedDict, defaultdict
from pathlib import Path
from threading import RLock
from typing import Any, Protocol, cast

from cataloging_tool.config.settings import OcrSettings
from cataloging_tool.domain.errors import OcrError
from cataloging_tool.domain.models import OcrLine, OcrResult

logger = logging.getLogger(__name__)


def _clone_ocr_result(result: OcrResult) -> OcrResult:
    """Return an isolated copy because callers annotate ``engine`` in-place."""
    return OcrResult(
        raw_text=result.raw_text,
        confidence=result.confidence,
        lines=[
            OcrLine(
                line.text,
                line.confidence,
                [list(point) for point in line.box] if line.box else None,
            )
            for line in result.lines
        ],
        engine=result.engine,
        duration_ms=result.duration_ms,
    )


def _image_cache_key(image_path: Path, variant: str) -> tuple[str, int, int, str]:
    stat = image_path.stat()
    return (str(image_path.resolve()), stat.st_size, stat.st_mtime_ns, variant)


class _OcrMemoryCache:
    """Small bounded per-process cache for duplicate OCR calls on one image."""

    def __init__(self, max_entries: int = 96) -> None:
        self.max_entries = max(8, max_entries)
        self._items: OrderedDict[tuple[str, int, int, str], OcrResult] = OrderedDict()
        self._lock = RLock()

    def get(self, key: tuple[str, int, int, str]) -> OcrResult | None:
        with self._lock:
            result = self._items.get(key)
            if result is None:
                return None
            self._items.move_to_end(key)
            return _clone_ocr_result(result)

    def put(self, key: tuple[str, int, int, str], result: OcrResult) -> None:
        with self._lock:
            self._items[key] = _clone_ocr_result(result)
            self._items.move_to_end(key)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)


class _OcrListMemoryCache:
    def __init__(self, max_entries: int = 64) -> None:
        self.max_entries = max(8, max_entries)
        self._items: OrderedDict[tuple[str, int, int, str], list[OcrResult]] = OrderedDict()
        self._lock = RLock()

    def get(self, key: tuple[str, int, int, str]) -> list[OcrResult] | None:
        with self._lock:
            results = self._items.get(key)
            if results is None:
                return None
            self._items.move_to_end(key)
            return [_clone_ocr_result(item) for item in results]

    def put(self, key: tuple[str, int, int, str], results: list[OcrResult]) -> None:
        with self._lock:
            self._items[key] = [_clone_ocr_result(item) for item in results]
            self._items.move_to_end(key)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)


class OcrEngine(Protocol):
    def recognize(self, image_path: Path) -> OcrResult: ...


class PaddleOcrEngine:
    """PaddleOCR adapter hardened for Windows CPU.

    The Windows CPU wheels in PaddlePaddle 3.3.x can fail in the oneDNN/PIR
    conversion path with ``ConvertPirAttribute2RuntimeAttribute``.  This adapter
    disables oneDNN explicitly, uses the lightweight PP-OCRv5 models, and falls
    back to the local Tesseract installation used by the legacy tool.
    """

    def __init__(self, settings: OcrSettings) -> None:
        self.settings = settings
        self._engine: Any | None = None
        self._engine_profile = ""
        self._tesseract = TesseractOcrEngine(settings)
        self._result_cache = _OcrMemoryCache(max_entries=96)

    @staticmethod
    def _prepare_cpu_environment() -> None:
        # These variables must exist before Paddle/PaddleX imports.
        os.environ["FLAGS_use_mkldnn"] = "0"
        os.environ["FLAGS_enable_mkldnn"] = "0"
        os.environ["OMP_NUM_THREADS"] = "1"
        os.environ["MKL_NUM_THREADS"] = "1"
        # Avoid repeated network checks once official models are cached.
        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

    def _engine_kwargs(self, *, minimal: bool = False) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "device": self.settings.device,
            "enable_mkldnn": False,
            "cpu_threads": (
                1
                if str(self.settings.device).casefold() == "cpu"
                else max(1, self.settings.cpu_threads)
            ),
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
        }
        if minimal:
            kwargs["lang"] = self.settings.language
        else:
            kwargs["text_detection_model_name"] = self.settings.text_detection_model_name
            kwargs["text_recognition_model_name"] = self.settings.text_recognition_model_name

        if self.settings.text_detection_model_dir is not None:
            kwargs["text_detection_model_dir"] = str(self.settings.text_detection_model_dir)
        if self.settings.text_recognition_model_dir is not None:
            kwargs["text_recognition_model_dir"] = str(self.settings.text_recognition_model_dir)
        return kwargs

    def _get_engine(self) -> Any:
        if self._engine is not None:
            return self._engine
        self._prepare_cpu_environment()
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise OcrError(
                "Chưa cài PaddleOCR/PaddlePaddle. Hãy chạy scripts\\repair_ocr_windows.ps1.",
                step="ocr_initialize",
                retryable=False,
            ) from exc

        errors: list[str] = []
        for profile, minimal in (("ppocrv5-mobile-safe", False), ("language-safe", True)):
            try:
                self._engine = PaddleOCR(**self._engine_kwargs(minimal=minimal))
                self._engine_profile = profile
                logger.info(
                    "PaddleOCR khởi tạo profile=%s, device=%s, MKL-DNN=off",
                    profile,
                    self.settings.device,
                )
                return self._engine
            except TypeError as exc:
                errors.append(f"{profile}: {exc}")
                self._engine = None
                continue
            except Exception as exc:
                errors.append(f"{profile}: {exc}")
                self._engine = None
                continue
        raise OcrError(
            "Không khởi tạo được PaddleOCR ở cả hai cấu hình an toàn: " + " | ".join(errors),
            step="ocr_initialize",
            retryable=False,
        )

    def recognize(self, image_path: Path) -> OcrResult:
        """Run Paddle first; invoke Tesseract only when Vietnamese quality is weak."""
        if not image_path.exists():
            raise OcrError(f"Không tìm thấy ảnh OCR: {image_path}", step="ocr_input")

        cache_key = _image_cache_key(image_path, "paddle-hybrid-v1")
        cached = self._result_cache.get(cache_key)
        if cached is not None:
            logger.info("Dùng lại kết quả OCR trong bộ nhớ: %s", image_path.name)
            return cached

        candidates: list[OcrResult] = []
        failures: list[str] = []
        started = time.perf_counter()
        paddle_result: OcrResult | None = None

        try:
            engine = self._get_engine()
            raw_results = engine.predict(input=str(image_path))
            lines = extract_paddle_lines(raw_results)
            if not lines:
                # An empty crop/result is valid OCR output, not an engine crash.
                # Keep the initialized Paddle model alive and allow the normal
                # fallback policy to try Tesseract without paying model startup
                # again on the next field/crop.
                failures.append("PaddleOCR: empty-result")
                logger.info("PaddleOCR không nhận diện được dòng chữ nào: %s", image_path.name)
            else:
                confidence = sum(line.confidence for line in lines) / len(lines)
                paddle_result = OcrResult(
                    raw_text="\n".join(line.text for line in lines if line.text.strip()),
                    confidence=confidence,
                    lines=lines,
                    engine=f"paddleocr:{self._engine_profile}",
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )
                candidates.append(paddle_result)
        except Exception as exc:
            # Only a real engine/prediction exception invalidates the Paddle
            # instance.  Empty recognition above deliberately does not reach here.
            self._engine = None
            failures.append(f"PaddleOCR: {exc}")
            logger.exception("PaddleOCR thất bại: %s", exc)

        policy = (self.settings.fallback_policy or "on_demand").casefold()
        run_tesseract = False
        if self.settings.use_tesseract_fallback:
            if paddle_result is None:
                run_tesseract = True
            elif policy == "always":
                run_tesseract = True
            elif policy != "never":
                paddle_score = score_ocr_result(paddle_result)
                paddle_quality = vietnamese_text_quality(paddle_result.raw_text)
                run_tesseract = (
                    paddle_score < self.settings.paddle_accept_score
                    or paddle_quality < self.settings.paddle_accept_vietnamese_quality
                )
                if not run_tesseract:
                    logger.info(
                        "PaddleOCR đạt ngưỡng nhanh; bỏ qua Tesseract (score=%.3f, vi=%.3f)",
                        paddle_score,
                        paddle_quality,
                    )

        if run_tesseract:
            try:
                candidates.append(self._tesseract.recognize(image_path))
            except Exception as exc:
                failures.append(f"Tesseract: {exc}")
                logger.warning("Tesseract không tạo được ứng viên OCR: %s", exc)

        if not candidates:
            raise OcrError(
                "Không OCR được ảnh bằng bất kỳ engine nào. " + " | ".join(failures),
                step="ocr_predict",
                retryable=False,
            )

        if len(candidates) >= 2:
            merged = merge_ocr_results(candidates)
            if merged is not None:
                candidates.append(merged)

        ranked = sorted(candidates, key=score_ocr_result, reverse=True)
        selected = ranked[0]
        logger.info(
            "Đã chọn OCR engine=%s, score=%.3f; ứng viên=%s",
            selected.engine,
            score_ocr_result(selected),
            ", ".join(
                f"{candidate.engine}:{score_ocr_result(candidate):.3f}"
                for candidate in ranked
            ),
        )
        if len(ranked) > 1:
            selected.engine = f"hybrid-selected:{selected.engine}"
        self._result_cache.put(cache_key, selected)
        return _clone_ocr_result(selected)

    def recognize_title_candidates(self, image_path: Path) -> list[OcrResult]:
        """Return independent Paddle and Vietnamese Tesseract title candidates.

        Overall Paddle confidence can be high while Vietnamese title letters are
        missing.  Report title recovery therefore always compares an independent
        ``vie+eng`` Tesseract result instead of trusting one engine's average.
        """
        candidates: list[OcrResult] = []
        try:
            candidates.append(self.recognize(image_path))
        except Exception as exc:
            logger.warning("Paddle title OCR failed: %s", exc)
        try:
            tess = self._tesseract.recognize(image_path)
            if not any(item.raw_text == tess.raw_text for item in candidates):
                candidates.append(tess)
        except Exception as exc:
            logger.warning("Tesseract title OCR failed: %s", exc)
        if not candidates:
            raise OcrError(
                "Không OCR được crop tiêu đề Báo cáo.",
                step="ocr_report_title",
                retryable=False,
            )
        return candidates

    def recognize_header_candidates(self, image_path: Path) -> list[OcrResult]:
        """Return independent OCR candidates for a document's top header.

        This intentionally compares Paddle and Vietnamese Tesseract even when
        Paddle reports a high average confidence. Handwritten number corrections
        and small italic Công văn titles can otherwise be confidently wrong.
        """
        return self.recognize_title_candidates(image_path)

    def recognize_header_number_candidates(self, image_path: Path) -> list[OcrResult]:
        """Return extra candidates specialised for the number/symbol band."""
        candidates: list[OcrResult] = []
        try:
            candidates.append(self.recognize(image_path))
        except Exception as exc:
            logger.warning("Paddle number-band OCR failed: %s", exc)
        try:
            for result in self._tesseract.recognize_number_candidates(image_path):
                if not any(item.raw_text == result.raw_text for item in candidates):
                    candidates.append(result)
        except Exception as exc:
            logger.warning("Tesseract number-band OCR failed: %s", exc)
        if not candidates:
            raise OcrError(
                "Không OCR được vùng số/ký hiệu đầu văn bản.",
                step="ocr_document_number",
                retryable=False,
            )
        return candidates

class TesseractOcrEngine:
    """Local fallback compatible with the legacy tool installation."""

    def __init__(self, settings: OcrSettings) -> None:
        self.settings = settings
        self._command: str | None = None
        self._result_cache = _OcrMemoryCache(max_entries=96)
        self._number_cache = _OcrListMemoryCache(max_entries=64)

    def _find_command(self) -> str:
        if self._command is not None:
            return self._command
        candidates = [
            os.environ.get("TESSERACT_CMD", ""),
            self.settings.tesseract_cmd,
            shutil.which("tesseract") or "",
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]
        for candidate in candidates:
            if candidate and Path(candidate).exists():
                self._command = str(Path(candidate))
                return self._command
        raise OcrError(
            "Không tìm thấy Tesseract dự phòng. Đường dẫn mặc định: "
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            step="ocr_tesseract_initialize",
            retryable=False,
        )

    def recognize(self, image_path: Path) -> OcrResult:
        if not image_path.exists():
            raise OcrError(f"Không tìm thấy ảnh OCR: {image_path}", step="ocr_input")
        cache_key = _image_cache_key(image_path, "tesseract-general-v1")
        cached = self._result_cache.get(cache_key)
        if cached is not None:
            logger.info("Dùng lại Tesseract trong bộ nhớ: %s", image_path.name)
            return cached

        command = self._find_command()
        tesseract_env = os.environ.copy()
        if self.settings.tessdata_dir is not None:
            tesseract_env["TESSDATA_PREFIX"] = str(self.settings.tessdata_dir)
        started = time.perf_counter()
        candidates: list[OcrResult] = []
        errors: list[str] = []

        configurations = [
            ("vie+eng", "6"),
            ("vie+eng", "11"),
            ("vie", "6"),
        ][: max(1, self.settings.tesseract_max_variants)]

        for index, (language, psm) in enumerate(configurations):
            args = [
                command,
                str(image_path),
                "stdout",
                "-l",
                language,
                "--oem",
                "1",
                "--psm",
                psm,
                "-c",
                "preserve_interword_spaces=1",
                "tsv",
            ]
            try:
                process = subprocess.run(
                    args,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    env=tesseract_env,
                    timeout=90,
                    check=False,
                )
            except Exception as exc:
                errors.append(f"{language}/psm{psm}: {exc}")
                continue
            if process.returncode != 0:
                errors.append(
                    f"{language}/psm{psm}: {process.stderr.strip() or process.returncode}"
                )
                continue
            lines = parse_tesseract_tsv(process.stdout)
            if not lines:
                errors.append(f"{language}/psm{psm}: không có dòng")
                continue
            confidence = sum(line.confidence for line in lines) / len(lines)
            result = OcrResult(
                raw_text="\n".join(line.text for line in lines),
                confidence=confidence,
                lines=lines,
                engine=f"tesseract:{language}:psm{psm}",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            candidates.append(result)

            # The common psm=6 pass is often sufficient. Do not run extra
            # Tesseract processes when its result already has usable quality.
            if (
                index == 0
                and score_ocr_result(result) >= self.settings.tesseract_accept_score
                and vietnamese_text_quality(result.raw_text) >= 0.45
            ):
                logger.info(
                    "Tesseract đạt ngưỡng ở biến thể đầu; bỏ qua biến thể còn lại"
                )
                break

        if not candidates:
            raise OcrError(
                "Tesseract không OCR được ảnh: " + " | ".join(errors),
                step="ocr_tesseract_predict",
                retryable=False,
            )
        selected = max(candidates, key=score_ocr_result)
        self._result_cache.put(cache_key, selected)
        return _clone_ocr_result(selected)

    def recognize_number_candidates(self, image_path: Path) -> list[OcrResult]:
        """OCR a tight handwritten number/symbol band with several page modes.

        The whitelist is intentionally confined to the header number crop; it is
        never used for Vietnamese abstract text. This makes overwritten digits
        such as 338/330/321 more likely to survive without damaging title accents.
        """
        if not image_path.exists():
            raise OcrError(f"Không tìm thấy ảnh OCR: {image_path}", step="ocr_input")
        cache_key = _image_cache_key(image_path, "tesseract-number-band-v1")
        cached = self._number_cache.get(cache_key)
        if cached is not None:
            logger.info("Dùng lại OCR số/ký hiệu trong bộ nhớ: %s", image_path.name)
            return cached

        command = self._find_command()
        tesseract_env = os.environ.copy()
        if self.settings.tessdata_dir is not None:
            tesseract_env["TESSDATA_PREFIX"] = str(self.settings.tessdata_dir)
        started = time.perf_counter()
        candidates: list[OcrResult] = []
        whitelist = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZĐ/-:Soố "
        for psm in (7, 6, 11):
            args = [
                command,
                str(image_path),
                "stdout",
                "-l",
                "vie+eng",
                "--oem",
                "1",
                "--psm",
                str(psm),
                "-c",
                f"tessedit_char_whitelist={whitelist}",
                "-c",
                "preserve_interword_spaces=1",
                "tsv",
            ]
            try:
                process = subprocess.run(
                    args,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    env=tesseract_env,
                    timeout=60,
                    check=False,
                )
            except Exception as exc:
                logger.debug("Tesseract number psm=%s failed: %s", psm, exc)
                continue
            if process.returncode != 0:
                continue
            lines = parse_tesseract_tsv(process.stdout)
            if not lines:
                continue
            candidates.append(
                OcrResult(
                    raw_text="\n".join(line.text for line in lines),
                    confidence=sum(line.confidence for line in lines) / len(lines),
                    lines=lines,
                    engine=f"tesseract:number-band:psm{psm}",
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )
            )
        self._number_cache.put(cache_key, candidates)
        return [_clone_ocr_result(item) for item in candidates]

_VIETNAMESE_DIACRITICS = set(
    "ăâđêôơưĂÂĐÊÔƠƯ"
    "áàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệ"
    "íìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữự"
    "ýỳỷỹỵÁÀẢÃẠẤẦẨẪẬẮẰẲẴẶÉÈẺẼẸẾỀỂỄỆ"
    "ÍÌỈĨỊÓÒỎÕỌỐỒỔỖỘỚỜỞỠỢÚÙỦŨỤỨỪỬỮỰÝỲỶỸỴ"
)
_DOCUMENT_MARKERS = (
    "so ", "ke hoach", "cong van", "quyet dinh", "bao cao",
    "thong bao", "to trinh", "nghi quyet", "chi thi", "huong dan",
    "dang uy", "dang cong san viet nam",
)
_CORRUPTION_MARKERS = (
    "kt lun", "thng vu", "dng y", "nhim v", "thc hin", "k hoch",
    "cht lng", "h thng", "thnh ph", "trn th", "ph trng", "qun ly",
    "ch dnh", "di biu", "d hi", "dng b", "ln th", "nhim k",
)


def _box_bounds(line: OcrLine) -> tuple[float, float, float, float] | None:
    if not line.box:
        return None
    try:
        xs = [float(point[0]) for point in line.box]
        ys = [float(point[1]) for point in line.box]
    except (TypeError, ValueError, IndexError):
        return None
    if not xs or not ys:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _line_rank(line: OcrLine) -> float:
    text = (line.text or '').strip()
    quality = vietnamese_text_quality(text)
    confidence = max(0.0, min(1.0, float(line.confidence or 0.0)))
    # A line with proper Vietnamese accents should beat a high-confidence line
    # that visibly lost most accents.
    return 0.72 * quality + 0.28 * confidence


def _same_visual_line(left: OcrLine, right: OcrLine) -> bool:
    a = _box_bounds(left)
    b = _box_bounds(right)
    if a is not None and b is not None:
        _, ay1, _, ay2 = a
        _, by1, _, by2 = b
        overlap = max(0.0, min(ay2, by2) - max(ay1, by1))
        height = max(1.0, min(ay2 - ay1, by2 - by1))
        center_a = (ay1 + ay2) / 2.0
        center_b = (by1 + by2) / 2.0
        if overlap / height >= 0.35 or abs(center_a - center_b) <= max(8.0, height * 0.65):
            return True
    folded_left = fold_ocr_text(left.text)
    folded_right = fold_ocr_text(right.text)
    if not folded_left or not folded_right:
        return False
    return difflib.SequenceMatcher(None, folded_left, folded_right).ratio() >= 0.68


def _line_sort_key(line: OcrLine) -> tuple[float, float]:
    bounds = _box_bounds(line)
    if bounds is None:
        return (10**9, 10**9)
    x1, y1, _, _ = bounds
    return y1, x1


def merge_ocr_results(results: list[OcrResult]) -> OcrResult | None:
    """Merge matching OCR lines, preferring the best Vietnamese spelling.

    Both engines receive the same image, therefore their bounding boxes can be
    aligned. This prevents a whole poor Tesseract result from replacing a much
    better Paddle title merely because its average numeric confidence is higher.
    """
    usable = [result for result in results if result.lines]
    if len(usable) < 2:
        return None
    base = max(usable, key=score_ocr_result)
    merged_lines: list[OcrLine] = []
    used: dict[int, set[int]] = {id(result): set() for result in usable}

    for base_index, base_line in enumerate(sorted(base.lines, key=_line_sort_key)):
        alternatives = [base_line]
        for result in usable:
            if result is base:
                continue
            for index, candidate in enumerate(result.lines):
                if index in used[id(result)]:
                    continue
                if _same_visual_line(base_line, candidate):
                    alternatives.append(candidate)
                    used[id(result)].add(index)
                    break
        chosen = max(alternatives, key=_line_rank)
        merged_lines.append(
            OcrLine(
                text=chosen.text.strip(),
                confidence=max(line.confidence for line in alternatives),
                box=chosen.box or base_line.box,
            )
        )
        used[id(base)].add(base_index)

    # Keep unmatched lines from the other engine only when they are not a
    # duplicate of an already merged line.
    for result in usable:
        if result is base:
            continue
        for index, candidate in enumerate(result.lines):
            if index in used[id(result)] or not candidate.text.strip():
                continue
            if any(_same_visual_line(candidate, current) for current in merged_lines):
                continue
            merged_lines.append(candidate)

    merged_lines.sort(key=_line_sort_key)
    if not merged_lines:
        return None
    confidence = sum(line.confidence for line in merged_lines) / len(merged_lines)
    return OcrResult(
        raw_text='\n'.join(line.text.strip() for line in merged_lines if line.text.strip()),
        confidence=confidence,
        lines=merged_lines,
        engine='hybrid-merged:paddle+tesseract',
        duration_ms=max(result.duration_ms for result in usable),
    )


def fold_ocr_text(value: str) -> str:
    import unicodedata

    decomposed = unicodedata.normalize("NFD", value or "")
    without_marks = "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    )
    return re.sub(
        r"\s+",
        " ",
        without_marks.replace("đ", "d").replace("Đ", "D").casefold(),
    ).strip()


def vietnamese_text_quality(value: str) -> float:
    text = value or ""
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return 0.0
    folded = fold_ocr_text(text)
    marker_count = sum(marker in folded for marker in _DOCUMENT_MARKERS)
    accent_ratio = sum(char in _VIETNAMESE_DIACRITICS for char in letters) / len(letters)
    printable_ratio = sum(char.isprintable() for char in text) / max(1, len(text))
    corruption_count = sum(marker in folded for marker in _CORRUPTION_MARKERS)
    length_score = min(1.0, len(text) / 180.0)
    marker_score = min(1.0, marker_count / 3.0)
    accent_score = min(1.0, accent_ratio / 0.10)
    penalty = min(0.55, corruption_count * 0.09)
    return max(
        0.0,
        min(
            1.0,
            0.22 * length_score
            + 0.30 * marker_score
            + 0.30 * accent_score
            + 0.18 * printable_ratio
            - penalty,
        ),
    )



_ABSTRACT_CORRUPTION_PHRASES = (
    "kt lun ca ban thung vu",
    "ket lun cua ban thung vu",
    "thung vu dng y",
    "thung vu pang uy",
    "the hin nhim v",
    "thc hin nhim v",
    "danh gia kt qua",
    "di voi dng chi",
    "trn th ",
    "pho trng ban",
    "ban qun ly",
    "v bao cao cho thoi la di biu",
    "ch dnh di biu",
    "d hi di biu",
)


def abstract_has_visible_ocr_corruption(value: str) -> bool:
    """Detect obvious OCR damage without rejecting ordinary Vietnamese prose.

    The former validator reused ``vietnamese_text_quality`` (a whole-page OCR
    ranking heuristic) as a hard abstract validator.  Correct abstracts that
    simply contained few accented characters were therefore rejected.  This
    function is intentionally conservative: it returns True only for repeated
    known missing-letter patterns or a fully unaccented fixed Vietnamese
    heading.
    """
    text = (value or "").strip()
    if len(text) < 12:
        return False
    folded = fold_ocr_text(text)
    phrase_hits = sum(phrase in folded for phrase in _ABSTRACT_CORRUPTION_PHRASES)
    marker_hits = sum(marker in folded for marker in _CORRUPTION_MARKERS)
    if phrase_hits >= 1 and marker_hits >= 2:
        return True
    if marker_hits >= 4:
        return True

    letters = [char for char in text if char.isalpha()]
    accent_ratio = (
        sum(char in _VIETNAMESE_DIACRITICS for char in letters) / len(letters)
        if letters else 0.0
    )
    fixed_unaccented_titles = (
        "ket luan cua ban thuong vu dang uy",
        "thong bao ket luan cua ban thuong vu dang uy",
        "bao cao cua ban thuong vu dang uy",
    )
    if accent_ratio < 0.005 and any(title in folded for title in fixed_unaccented_titles):
        return True
    return False

def score_ocr_result(result: OcrResult) -> float:
    confidence = max(0.0, min(1.0, float(result.confidence or 0.0)))
    return 0.40 * confidence + 0.60 * vietnamese_text_quality(result.raw_text)


def text_has_document_header(value: str) -> bool:
    folded = fold_ocr_text(value)
    return len(value or "") >= 50 and any(marker in folded for marker in _DOCUMENT_MARKERS)


def is_pir_onednn_error(exc: Exception | None) -> bool:
    if exc is None:
        return False
    text = str(exc).casefold()
    return (
        "convertpirattribute2runtimeattribute" in text
        or "onednn_instruction" in text
        or "arrayattribute<pir::doubleattribute>" in text
    )


def parse_tesseract_tsv(raw: str) -> list[OcrLine]:
    groups: dict[tuple[str, str, str, str], list[tuple[str, float, list[list[float]]]]] = defaultdict(list)
    reader = csv.DictReader(raw.splitlines(), delimiter="\t")
    for row in reader:
        text = (row.get("text") or "").strip()
        if not text:
            continue
        try:
            confidence_raw = float(row.get("conf") or -1)
        except ValueError:
            confidence_raw = -1
        if confidence_raw < 0:
            continue
        try:
            left = float(row.get("left") or 0)
            top = float(row.get("top") or 0)
            width = float(row.get("width") or 0)
            height = float(row.get("height") or 0)
        except ValueError:
            left = top = width = height = 0
        key = (
            row.get("page_num") or "0",
            row.get("block_num") or "0",
            row.get("par_num") or "0",
            row.get("line_num") or "0",
        )
        box = [
            [left, top],
            [left + width, top],
            [left + width, top + height],
            [left, top + height],
        ]
        groups[key].append((text, confidence_raw / 100.0, box))

    lines: list[OcrLine] = []
    for words in groups.values():
        text = " ".join(word[0] for word in words).strip()
        if not text:
            continue
        confidence = sum(word[1] for word in words) / len(words)
        xs = [point[0] for word in words for point in word[2]]
        ys = [point[1] for word in words for point in word[2]]
        box = [
            [min(xs), min(ys)],
            [max(xs), min(ys)],
            [max(xs), max(ys)],
            [min(xs), max(ys)],
        ]
        lines.append(OcrLine(text=text, confidence=confidence, box=box))
    return lines


def _as_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    json_value = getattr(value, "json", None)
    if callable(json_value):
        json_value = json_value()
    if isinstance(json_value, str):
        try:
            json_value = json.loads(json_value)
        except json.JSONDecodeError:
            return None
    return json_value if isinstance(json_value, dict) else None


def extract_paddle_lines(raw_results: Any) -> list[OcrLine]:
    """Accept PaddleOCR 3.x result objects and legacy nested result lists."""
    lines: list[OcrLine] = []
    if raw_results is None:
        return lines
    if not isinstance(raw_results, (list, tuple)):
        raw_results = list(raw_results) if hasattr(raw_results, "__iter__") else [raw_results]

    for result in raw_results:
        payload = _as_dict(result)
        if payload:
            data = payload.get("res", payload)
            texts = data.get("rec_texts") or data.get("texts") or []
            scores = data.get("rec_scores") or data.get("scores") or []
            boxes = data.get("rec_polys") or data.get("dt_polys") or data.get("boxes") or []
            for index, text in enumerate(texts):
                score = float(scores[index]) if index < len(scores) else 0.0
                box = boxes[index] if index < len(boxes) else None
                if box is not None and hasattr(box, "tolist"):
                    box = cast(Any, box).tolist()
                if str(text).strip():
                    lines.append(OcrLine(text=str(text).strip(), confidence=score, box=box))
            if texts:
                continue

        candidates: list[Any] = []
        if isinstance(result, (list, tuple)):
            if (
                len(result) >= 2
                and isinstance(result[1], (list, tuple))
                and len(result[1]) >= 1
                and isinstance(result[1][0], str)
            ):
                candidates = [result]
            else:
                candidates = list(result)
        for candidate in candidates:
            if not isinstance(candidate, (list, tuple)) or len(candidate) < 2:
                continue
            box, recognition = candidate[0], candidate[1]
            if not isinstance(recognition, (list, tuple)) or not recognition:
                continue
            text = str(recognition[0]).strip()
            score = float(recognition[1]) if len(recognition) > 1 else 0.0
            if hasattr(box, "tolist"):
                box = box.tolist()
            if text:
                lines.append(OcrLine(text=text, confidence=score, box=box))
    return lines


def save_ocr_result(result: OcrResult, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    text_path = output_dir / "raw-ocr.txt"
    json_path = output_dir / "ocr.json"
    text_path.write_text(result.raw_text, encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "engine": result.engine,
                "confidence": result.confidence,
                "duration_ms": result.duration_ms,
                "raw_text": result.raw_text,
                "lines": [
                    {"text": line.text, "confidence": line.confidence, "box": line.box}
                    for line in result.lines
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return text_path, json_path
