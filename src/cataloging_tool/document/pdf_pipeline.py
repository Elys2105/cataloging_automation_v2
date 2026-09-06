from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from cataloging_tool.domain.errors import PdfRenderError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PdfTextResult:
    text: str
    page_count: int
    usable: bool


@dataclass(frozen=True, slots=True)
class RenderedPage:
    full_page: Path
    header_crop: Path
    width: int
    height: int
    dpi: int


class PdfPipeline:
    def __init__(self, output_dir: Path, *, render_dpi: int = 300, minimum_text_length: int = 80) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.render_dpi = render_dpi
        self.minimum_text_length = minimum_text_length

    @staticmethod
    def _is_fresh_output(output_path: Path, source_path: Path) -> bool:
        try:
            return (
                output_path.exists()
                and output_path.stat().st_size > 0
                and output_path.stat().st_mtime_ns >= source_path.stat().st_mtime_ns
            )
        except OSError:
            return False

    def extract_text(self, pdf_path: Path, max_pages: int = 2) -> PdfTextResult:
        try:
            import fitz

            with fitz.open(pdf_path) as document:
                page_count = document.page_count
                parts: list[str] = []
                for index in range(min(page_count, max_pages)):
                    parts.append(cast(str, document.load_page(index).get_text("text")))
            text = self._clean_text("\n".join(parts))
            return PdfTextResult(text=text, page_count=page_count, usable=self.looks_usable_text(text))
        except Exception as exc:
            raise PdfRenderError(
                f"Không đọc được PDF {pdf_path.name}: {exc}", step="pdf_text", retryable=False
            ) from exc


    def extract_last_page_text(self, pdf_path: Path) -> str:
        """Read only the final PDF page; this is cheap and targets signer metadata."""
        try:
            import fitz

            with fitz.open(pdf_path) as document:
                if document.page_count < 1:
                    return ""
                text = cast(str, document.load_page(document.page_count - 1).get_text("text"))
            return self._clean_text(text)
        except Exception:
            return ""

    def render_last_page_signature_crop(self, pdf_path: Path, record_key: str) -> Path | None:
        """Render the bottom-right signature/stamp area of the final page."""
        target_dir = self.output_dir / record_key
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / "last-page-signature.png"
        if self._is_fresh_output(target, pdf_path):
            return target
        try:
            import fitz

            with fitz.open(pdf_path) as document:
                if document.page_count < 1:
                    return None
                page = document.load_page(document.page_count - 1)
                rect = page.rect
                clip = fitz.Rect(
                    rect.x0 + rect.width * 0.34,
                    rect.y0 + rect.height * 0.42,
                    rect.x1,
                    rect.y1,
                )
                zoom = self.render_dpi / 72.0
                pixmap = page.get_pixmap(
                    matrix=fitz.Matrix(zoom, zoom),
                    clip=clip,
                    alpha=False,
                )
                pixmap.save(target)
            return target if target.exists() and target.stat().st_size > 1000 else None
        except Exception as exc:
            logger.debug("Không render được vùng chữ ký trang cuối: %s", exc)
            return None

    def prepare_signature_crop_from_image(
        self, image_path: Path, record_key: str
    ) -> Path | None:
        """Crop the signature/stamp area from a browser-captured final-page image."""
        target_dir = self.output_dir / record_key
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / "viewer-last-page-signature.png"
        if self._is_fresh_output(target, image_path):
            return target
        try:
            from PIL import Image

            with Image.open(image_path) as source:
                image = source.convert("RGB")
                left, top, right, bottom = self._find_page_bounds(image_path, image.size)
                page = image.crop((left, top, right, bottom))
                width, height = page.size
                crop = page.crop((
                    int(width * 0.34),
                    int(height * 0.42),
                    width,
                    height,
                ))
                crop.save(target, format="PNG", compress_level=1)
            return target if target.exists() and target.stat().st_size > 1000 else None
        except Exception as exc:
            logger.debug("Không tạo được crop chữ ký từ ảnh viewer: %s", exc)
            return None

    def prepare_image_first_page(
        self,
        image_path: Path,
        record_key: str,
        header_ratio: float = 0.55,
    ) -> RenderedPage:
        """Use a viewer screenshot directly instead of PDF -> PNG round-tripping."""
        if not 0.35 <= header_ratio <= 1.0:
            raise ValueError("header_ratio phải trong khoảng 0.35 đến 1.0")
        try:
            from PIL import Image

            target_dir = self.output_dir / record_key
            target_dir.mkdir(parents=True, exist_ok=True)
            header_path = target_dir / "page-1-header.png"

            with Image.open(image_path) as image:
                width, height = image.size
                crop_height = max(1, int(height * header_ratio))
                recreate = (
                    not header_path.exists()
                    or header_path.stat().st_mtime_ns < image_path.stat().st_mtime_ns
                )
                if recreate:
                    header = image.crop((0, 0, width, crop_height))
                    header.save(header_path, format="PNG", compress_level=1)

            return RenderedPage(
                full_page=image_path,
                header_crop=header_path,
                width=width,
                height=height,
                dpi=self.render_dpi,
            )
        except Exception as exc:
            raise PdfRenderError(
                f"Không chuẩn bị được ảnh viewer {image_path.name}: {exc}",
                step="pdf_render",
                retryable=False,
            ) from exc

    def render_first_page(self, pdf_path: Path, record_key: str, header_ratio: float = 0.65) -> RenderedPage:
        if not 0.35 <= header_ratio <= 1.0:
            raise ValueError("header_ratio phải trong khoảng 0.35 đến 1.0")
        try:
            import fitz
            from PIL import Image

            target_dir = self.output_dir / record_key
            target_dir.mkdir(parents=True, exist_ok=True)
            full_path = target_dir / "page-1.png"
            header_path = target_dir / "page-1-header.png"

            if not full_path.exists():
                with fitz.open(pdf_path) as document:
                    if document.page_count < 1:
                        raise PdfRenderError("PDF không có trang.", step="pdf_render")
                    page = document.load_page(0)
                    zoom = self.render_dpi / 72.0
                    pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                    pixmap.save(full_path)

            with Image.open(full_path) as image:
                width, height = image.size
                crop_height = max(1, int(height * header_ratio))
                if not header_path.exists():
                    header = image.crop((0, 0, width, crop_height))
                    header.save(header_path, format="PNG", compress_level=1)

            return RenderedPage(
                full_page=full_path,
                header_crop=header_path,
                width=width,
                height=height,
                dpi=self.render_dpi,
            )
        except PdfRenderError:
            raise
        except Exception as exc:
            raise PdfRenderError(
                f"Không render được PDF {pdf_path.name}: {exc}", step="pdf_render", retryable=False
            ) from exc

    def prepare_author_header_crops(
        self,
        image_path: Path,
        output_dir: Path,
    ) -> list[Path]:
        """Create small top-page crops dedicated to the issuing organization.

        The normal document-header recovery canonicalizes number/title evidence
        and can intentionally discard issuer text.  Author recovery therefore
        has its own crops and keeps the OCR text verbatim for the organization
        parser.  The crops stop before the title/body to avoid leaking document
        headings into the author.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        names = (
            "author-header-core.png",
            "author-header-tight.png",
            "author-header-left.png",
            "author-header-wide.png",
        )
        cached_paths = [output_dir / name for name in names]
        if all(self._is_fresh_output(path, image_path) for path in cached_paths):
            logger.info("Dùng lại crop cơ quan ban hành đã tạo")
            return cached_paths
        try:
            from PIL import Image

            with Image.open(image_path) as source:
                image = source.convert("RGB")
                left, top, right, bottom = self._find_page_bounds(image_path, image.size)
                page = image.crop((left, top, right, bottom))
                width, height = page.size
                specs = (
                    # Core crop is deliberately centered on the upper-left
                    # organization block visible across the supplied failures.
                    # It excludes most of the national-heading/right column.
                    (0.040, 0.012, 0.48, 0.145, "author-header-core.png"),
                    # Overlapping crops make the recovery tolerant of page
                    # margin/scan alignment differences without reading body
                    # prose.
                    (0.015, 0.004, 0.50, 0.17, "author-header-tight.png"),
                    (0.015, 0.005, 0.62, 0.19, "author-header-left.png"),
                    (0.015, 0.005, 0.82, 0.22, "author-header-wide.png"),
                )
                results: list[Path] = []
                for x1, y1, x2, y2, name in specs:
                    crop = page.crop((
                        int(width * x1),
                        int(height * y1),
                        max(int(width * x2), int(width * x1) + 1),
                        max(int(height * y2), int(height * y1) + 1),
                    ))
                    target = output_dir / name
                    if not self._is_fresh_output(target, image_path):
                        crop.save(target, format="PNG", compress_level=1)
                    results.append(target)
                return results
        except Exception as exc:
            logger.warning("Không tạo được crop cơ quan ban hành: %s", exc)
            return []

    def prepare_document_header_crops(
        self,
        image_path: Path,
        output_dir: Path,
        *,
        cong_van: bool = False,
    ) -> list[Path]:
        """Create focused crops for the own document number and CV title block.

        Generic header OCR previously used the top 55% of the page. On Công văn
        records that area contains cited instruments in the body, so a clean
        ``9871-CV/...`` body reference could beat a handwritten ``338-CV/ĐU``
        header. These crops stop before the body and magnify the handwritten
        number plus the italic abstract directly below it.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        names = [
            "document-header-wide.png",
            "document-header-centre.png",
        ]
        if cong_van:
            # A narrow left-title crop magnifies the small italic block while
            # excluding the date column and nearly all body text.  It is created
            # only for Công văn so no other document branch pays the OCR cost.
            names.extend((
                "document-title-left.png",
                "document-title-left-tall.png",
            ))
        names.extend((
            "document-number-left-wide.png",
            "document-number-left-tight.png",
        ))
        cached_paths = [output_dir / name for name in names]
        if all(self._is_fresh_output(path, image_path) for path in cached_paths):
            logger.info("Dùng lại crop đầu văn bản đã tạo")
            return cached_paths
        try:
            from PIL import Image

            with Image.open(image_path) as source:
                image = source.convert("RGB")
                left, top, right, bottom = self._find_page_bounds(image_path, image.size)
                page = image.crop((left, top, right, bottom))
                width, height = page.size
                specs = [
                    # Includes issuer, date, number, italic title and Kính gửi.
                    (0.03, 0.01, 0.97, 0.36, "document-header-wide.png"),
                    # Magnifies the central number/title block while retaining both columns.
                    (0.10, 0.035, 0.90, 0.29, "document-header-centre.png"),
                ]
                if cong_van:
                    specs.extend((
                        # Tight title strip for the common two/three-line case.
                        (0.055, 0.085, 0.64, 0.255, "document-title-left.png"),
                        # Taller overlapping strip for four/five-line Công văn
                        # abstracts.  It intentionally includes the Kính gửi band
                        # so OCR can prove the lower title boundary instead of
                        # returning a clean but truncated prefix.
                        (0.035, 0.070, 0.67, 0.355, "document-title-left-tall.png"),
                    ))
                specs.extend((
                    # Tight left-column crops dedicated to the handwritten own number.
                    # They intentionally exclude the date column and most of the title so
                    # strokes cannot be concatenated with unrelated printed characters.
                    (0.10, 0.060, 0.55, 0.195, "document-number-left-wide.png"),
                    (0.15, 0.075, 0.49, 0.170, "document-number-left-tight.png"),
                ))
                results: list[Path] = []
                for x1, y1, x2, y2, name in specs:
                    crop = page.crop((
                        int(width * x1),
                        int(height * y1),
                        max(int(width * x2), int(width * x1) + 1),
                        max(int(height * y2), int(height * y1) + 1),
                    ))
                    target = output_dir / name
                    if not self._is_fresh_output(target, image_path):
                        crop.save(target, format="PNG", compress_level=1)
                    results.append(target)
                return results
        except Exception as exc:
            logger.warning("Không tạo được crop đầu văn bản: %s", exc)
            return []

    def prepare_special_report_title_crops(
        self,
        image_path: Path,
        output_dir: Path,
    ) -> list[Path]:
        """Create high-value title crops for wide/daily Báo cáo layouts.

        The website often scales a landscape first page to fit the viewer.  The
        generic header crop then contains a lot of table/body text while the
        title itself is very small.  This method locates the white paper region
        when possible and creates two overlapping top-centre crops.  It is used
        only as a recovery pass for ``BC/...`` records, so normal documents keep
        the fast path.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        names = (
            "report-title-top.png",
            "report-title-wide.png",
            "report-title-centre.png",
        )
        cached_paths = [output_dir / name for name in names]
        if all(self._is_fresh_output(path, image_path) for path in cached_paths):
            logger.info("Dùng lại crop tiêu đề Báo cáo đã tạo")
            return cached_paths
        try:
            from PIL import Image

            with Image.open(image_path) as source:
                image = source.convert("RGB")
                left, top, right, bottom = self._find_page_bounds(image_path, image.size)
                page = image.crop((left, top, right, bottom))
                width, height = page.size

                # The first crop keeps the number line and complete title block.
                # The second zooms further into the centred title, which is the
                # critical fallback when the page is very wide.
                specs = (
                    # Tight top strip first: it magnifies the two title lines and
                    # excludes the prose paragraph/table that caused overrun.
                    (0.08, 0.03, 0.92, 0.31, "report-title-top.png"),
                    (0.03, 0.02, 0.97, 0.52, "report-title-wide.png"),
                    (0.12, 0.08, 0.88, 0.43, "report-title-centre.png"),
                )
                results: list[Path] = []
                for x1, y1, x2, y2, name in specs:
                    crop = page.crop((
                        int(width * x1),
                        int(height * y1),
                        max(int(width * x2), int(width * x1) + 1),
                        max(int(height * y2), int(height * y1) + 1),
                    ))
                    target = output_dir / name
                    if not self._is_fresh_output(target, image_path):
                        crop.save(target, format="PNG", compress_level=1)
                    results.append(target)
                return results
        except Exception as exc:
            logger.warning("Không tạo được crop tiêu đề Báo cáo đặc biệt: %s", exc)
            return []

    @staticmethod
    def _find_page_bounds(image_path: Path, fallback_size: tuple[int, int]) -> tuple[int, int, int, int]:
        """Locate the largest light page rectangle inside a viewer screenshot."""
        width, height = fallback_size
        try:
            import cv2

            gray = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
            if gray is None:
                return 0, 0, width, height
            _, mask = cv2.threshold(gray, 185, 255, cv2.THRESH_BINARY)
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            image_area = width * height
            candidates: list[tuple[float, tuple[int, int, int, int]]] = []
            for contour in contours:
                x, y, w, h = cv2.boundingRect(contour)
                area = w * h
                if area < image_area * 0.18 or w < 250 or h < 140:
                    continue
                aspect = w / max(1, h)
                # Prefer a landscape paper region, but accept a full-page crop if
                # the viewer screenshot itself already contains only the page.
                aspect_bonus = 1.35 if 1.08 <= aspect <= 2.2 else 1.0
                candidates.append((area * aspect_bonus, (x, y, x + w, y + h)))
            if candidates:
                return max(candidates, key=lambda item: item[0])[1]
        except Exception:
            pass
        return 0, 0, width, height

    def preprocess_for_ocr(
        self,
        image_path: Path,
        output_path: Path,
        *,
        mode: str = "enhanced",
        target_width: int = 2200,
    ) -> Path:
        """Prepare a high-resolution OCR image without erasing Vietnamese marks.

        ``enhanced`` preserves grayscale strokes. ``threshold`` is a second,
        high-contrast candidate used only when the first OCR pass is weak.
        """
        if mode not in {"enhanced", "threshold"}:
            raise ValueError(f"Chế độ tiền xử lý OCR không hợp lệ: {mode}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if self._is_fresh_output(output_path, image_path):
            logger.info("Dùng lại ảnh tiền xử lý OCR: %s", output_path.name)
            return output_path
        try:
            import cv2

            image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
            if image is None:
                raise ValueError("OpenCV không đọc được ảnh")

            height, width = image.shape[:2]
            # PaddleOCR internally limits the longest side to about 4000 px.
            # Resize once here so Paddle does not allocate and resize the same
            # 4200+ px image again for every OCR candidate. No OCR information
            # is removed beyond the resize Paddle already performs internally.
            model_max_side = 4000
            requested_width = max(1200, int(target_width))
            desired_width = min(requested_width, model_max_side)
            upscale = min(5.0, desired_width / max(1, width))
            longest_side = max(width, height)
            downscale = model_max_side / longest_side if longest_side > model_max_side else 1.0
            scale = downscale if downscale < 1.0 else max(1.0, upscale)
            if abs(scale - 1.0) > 0.001:
                image = cv2.resize(
                    image,
                    None,
                    fx=scale,
                    fy=scale,
                    interpolation=(
                        cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
                    ),
                )

            normalized = cv2.createCLAHE(
                clipLimit=1.6,
                tileGridSize=(8, 8),
            ).apply(image)
            if mode == "threshold":
                # Adaptive threshold copes with grey scan backgrounds while the
                # small block size keeps Vietnamese accent marks connected.
                prepared = cv2.adaptiveThreshold(
                    normalized,
                    255,
                    cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                    cv2.THRESH_BINARY,
                    31,
                    11,
                )
                prepared = cv2.morphologyEx(
                    prepared,
                    cv2.MORPH_CLOSE,
                    cv2.getStructuringElement(cv2.MORPH_RECT, (1, 2)),
                )
            else:
                blurred = cv2.GaussianBlur(normalized, (0, 0), 1.0)
                prepared = cv2.addWeighted(normalized, 1.55, blurred, -0.55, 0)

            if not cv2.imwrite(
                str(output_path),
                prepared,
                [cv2.IMWRITE_PNG_COMPRESSION, 1],
            ):
                raise ValueError("OpenCV không ghi được ảnh")
            return output_path
        except ImportError:
            from PIL import Image, ImageEnhance, ImageFilter, ImageOps

            with Image.open(image_path) as image:
                gray = ImageOps.grayscale(image)
                model_max_side = 4000
                target_width = min(model_max_side, max(1200, int(target_width)))
                ratio = 1.0
                if max(gray.size) > model_max_side:
                    ratio = model_max_side / max(gray.size)
                elif gray.width < target_width:
                    ratio = min(3.5, target_width / max(1, gray.width))
                if abs(ratio - 1.0) > 0.001:
                    gray = gray.resize(
                        (int(gray.width * ratio), int(gray.height * ratio)),
                        (
                            Image.Resampling.LANCZOS
                            if ratio > 1.0
                            else Image.Resampling.BOX
                        ),
                    )
                enhanced = ImageEnhance.Contrast(gray).enhance(1.18)
                if mode == "threshold":
                    enhanced = enhanced.point([0 if pixel <= 175 else 255 for pixel in range(256)])
                else:
                    enhanced = enhanced.filter(
                        ImageFilter.UnsharpMask(radius=1.2, percent=145, threshold=2)
                    )
                enhanced.save(output_path, format="PNG", compress_level=1)
            return output_path
        except Exception as exc:
            logger.warning("Tiền xử lý ảnh thất bại, dùng ảnh gốc: %s", exc)
            return image_path

    @staticmethod
    def _clean_text(text: str) -> str:
        lines = [" ".join(line.split()) for line in text.replace("\r", "\n").split("\n")]
        return "\n".join(line for line in lines if line).strip()

    def looks_usable_text(self, text: str) -> bool:
        if len(text or "") < self.minimum_text_length:
            return False
        normalized = (text or "").casefold()
        markers = (
            "số ",
            "kế hoạch",
            "công văn",
            "quyết định",
            "báo cáo",
            "thông báo",
            "tờ trình",
            "nghị quyết",
            "chỉ thị",
            "đảng cộng sản",
        )
        return any(marker in normalized for marker in markers)

    def _looks_usable(self, text: str) -> bool:
        return self.looks_usable_text(text)
