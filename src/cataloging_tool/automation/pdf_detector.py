from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from cataloging_tool.domain.errors import PdfAcquisitionError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PdfCandidate:
    source: str
    url: str
    content: bytes | None = None


@dataclass(frozen=True, slots=True)
class AcquiredPdf:
    path: Path
    sha256: str
    source: str
    original_url: str
    size_bytes: int
    image_path: Path | None = None


def looks_like_pdf(data: bytes, content_type: str = "", url: str = "") -> bool:
    header_ok = data.lstrip().startswith(b"%PDF-")
    type_ok = "application/pdf" in content_type.lower()
    url_ok = urlparse(url).path.lower().endswith(".pdf")
    return header_ok and (type_ok or url_ok or len(data) > 100)


def safe_record_key(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    cleaned = cleaned.strip("-._")
    return cleaned[:80] or "document"


_UPLOAD_TEXT = re.compile(
    r"tải\s*file\s*lên|upload|chọn\s*file|browse|scan\s*tài\s*liệu",
    re.IGNORECASE,
)
_SAFE_DOWNLOAD_TEXT = re.compile(
    r"^(?:tải\s*xuống|download|tải\s*pdf|xem\s*pdf)$",
    re.IGNORECASE,
)


def is_safe_download_control(text: str, href: str = "", download_attr: str = "") -> bool:
    """Return True only for controls that cannot reasonably be an upload control.

    The old broad matcher treated ``Tải file lên`` as a download button and could
    open the native Windows file picker. The automation now prefers network/DOM
    extraction and does not click generic toolbar controls.
    """
    label = re.sub(r"\s+", " ", text or "").strip()
    if _UPLOAD_TEXT.search(label):
        return False
    if download_attr:
        return True
    href_key = (href or "").casefold()
    if href_key and any(token in href_key for token in ("download", "attachment", ".pdf")):
        return True
    return bool(_SAFE_DOWNLOAD_TEXT.fullmatch(label))


class PdfResponseCollector:
    """Collect PDF responses while a document page is loading."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[PdfCandidate] = asyncio.Queue()
        self._tasks: set[asyncio.Task[None]] = set()

    def attach(self, page: Any) -> None:
        def on_response(response: Any) -> None:
            task = asyncio.create_task(self._capture_response(response))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

        page.on("response", on_response)

    async def _capture_response(self, response: Any) -> None:
        try:
            headers = await response.all_headers()
            content_type = headers.get("content-type", "")
            url = str(response.url)
            if (
                "application/pdf" not in content_type.lower()
                and not urlparse(url).path.lower().endswith(".pdf")
            ):
                return
            body = await response.body()
            if looks_like_pdf(body, content_type, url):
                await self._queue.put(
                    PdfCandidate(source="network-response", url=url, content=body)
                )
        except Exception as exc:
            logger.debug("Không đọc được response PDF: %s", exc)

    async def get(self, timeout_seconds: float = 1.5) -> PdfCandidate | None:
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout_seconds)
        except TimeoutError:
            return None


class PdfAcquirer:
    """Acquire a document without asking the operator to choose a local file.

    Order:
    1. PDF response already observed on the network.
    2. iframe/embed/object/link URL loaded with the authenticated browser context.
    3. A second short network wait.
    4. Screenshot the PDF viewer already displayed on the right and wrap it as PDF.

    It deliberately never clicks ``Tải file lên`` or another generic toolbar button.
    """

    DOM_SELECTORS = (
        "iframe[src]",
        "embed[src]",
        "object[data]",
        "a[href]",
    )

    def __init__(
        self,
        output_dir: Path,
        collector: PdfResponseCollector | None = None,
        *,
        fast_viewer_fallback: bool = True,
        viewer_ready_timeout_ms: int = 3500,
    ) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.collector = collector or PdfResponseCollector()
        self.fast_viewer_fallback = fast_viewer_fallback
        self.viewer_ready_timeout_ms = max(500, viewer_ready_timeout_ms)
        self._viewer_fallback_confirmed = False

    async def acquire(self, page: Any, record_key: str) -> AcquiredPdf:
        # Sau khi cùng website đã phải dùng viewer screenshot một lần, các bản ghi
        # tiếp theo thường có cùng cơ chế. Bỏ 3 giây dò network/DOM lặp lại.
        if self.fast_viewer_fallback and self._viewer_fallback_confirmed:
            await self._wait_for_viewer_ready(page)
            captured = await self._capture_viewer_as_pdf(page, record_key)
            if captured is not None:
                logger.info("Fast path: chụp trực tiếp PDF viewer bên phải")
                return captured

        candidate = await self.collector.get(timeout_seconds=0.45)
        if candidate and candidate.content:
            logger.info("Lấy PDF từ network response: %s", candidate.url)
            return self._save(candidate, record_key)

        for candidate in await self._find_dom_candidates(page):
            downloaded = await self._download_url(page, candidate.url)
            if downloaded is not None:
                logger.info("Lấy PDF từ DOM URL: %s", candidate.url)
                return self._save(
                    PdfCandidate(
                        source=candidate.source,
                        url=candidate.url,
                        content=downloaded,
                    ),
                    record_key,
                )

        candidate = await self.collector.get(timeout_seconds=0.8)
        if candidate and candidate.content:
            logger.info("Lấy PDF từ network response chờ bổ sung: %s", candidate.url)
            return self._save(candidate, record_key)

        # Fallback giữ đúng tinh thần tool gốc: đọc trực tiếp vùng PDF đang hiển thị,
        # không mở hộp chọn file và không yêu cầu người dùng tải PDF thủ công.
        await self._wait_for_viewer_ready(page)
        captured = await self._capture_viewer_as_pdf(page, record_key)
        if captured is not None:
            self._viewer_fallback_confirmed = True
            logger.info("Không lấy được PDF gốc; dùng ảnh PDF viewer bên phải: %s", captured.path)
            return captured

        raise PdfAcquisitionError(
            "Không tự phát hiện được PDF hoặc vùng PDF đang hiển thị của bản ghi.",
            step="pdf_acquire",
            retryable=True,
        )


    async def _wait_for_viewer_ready(self, page: Any) -> None:
        selector = (
            "#viewer .page:first-child, .pdfViewer .page:first-child, "
            ".page[data-page-number='1'], canvas, iframe[src], embed[src], object[data]"
        )
        try:
            await page.locator(selector).first.wait_for(
                state="visible",
                timeout=self.viewer_ready_timeout_ms,
            )
        except Exception:
            # Một số viewer vẽ trong div riêng; hàm capture vẫn có fallback theo vùng phải.
            pass

    async def _find_dom_candidates(self, page: Any) -> list[PdfCandidate]:
        result: list[PdfCandidate] = []
        base_url = str(page.url)
        seen: set[str] = set()
        for selector in self.DOM_SELECTORS:
            locator = page.locator(selector)
            count = await locator.count()
            for index in range(count):
                element = locator.nth(index)
                attribute = (
                    "data"
                    if selector.startswith("object")
                    else "src"
                    if "[src]" in selector
                    else "href"
                )
                value = await element.get_attribute(attribute)
                if not value or value.startswith(("javascript:", "#", "blob:")):
                    continue
                absolute = urljoin(base_url, value)
                lower = absolute.lower()
                likely_pdf = (
                    lower.endswith(".pdf")
                    or "pdf" in lower
                    or "download" in lower
                    or "attachment" in lower
                )
                if likely_pdf and absolute not in seen:
                    seen.add(absolute)
                    result.append(PdfCandidate(source=f"dom:{selector}", url=absolute))
        return result

    async def _download_url(self, page: Any, url: str) -> bytes | None:
        try:
            response = await page.context.request.get(url, timeout=30_000)
            if not response.ok:
                return None
            headers = await response.all_headers()
            data = await response.body()
            if looks_like_pdf(data, headers.get("content-type", ""), url):
                return data
        except Exception as exc:
            logger.debug("Không tải được PDF từ URL %s: %s", url, exc)
        return None

    async def _capture_viewer_as_pdf(
        self, page: Any, record_key: str
    ) -> AcquiredPdf | None:
        """Capture only the visible PDF area on the right, then wrap it as a PDF.

        This is the Playwright equivalent of the legacy
        ``CapturePdfPageFromBrowserScreenshot`` fallback, but it uses a CSS-pixel
        clip directly and leaves a PNG diagnostic beside the generated PDF.
        """
        try:
            clip = await page.evaluate(
                r"""() => {
                    function visible(el) {
                        if (!el) return false;
                        const r = el.getBoundingClientRect();
                        const st = window.getComputedStyle(el);
                        return r.width > 80 && r.height > 120 &&
                               st.display !== 'none' &&
                               st.visibility !== 'hidden' &&
                               st.opacity !== '0';
                    }

                    function clampRect(r) {
                        const x = Math.max(0, r.left);
                        const y = Math.max(0, r.top);
                        const right = Math.min(window.innerWidth, r.right);
                        const bottom = Math.min(window.innerHeight, r.bottom);
                        return {
                            x,
                            y,
                            width: Math.max(0, right - x),
                            height: Math.max(0, bottom - y)
                        };
                    }

                    // Đưa viewer về đầu trang nhưng tuyệt đối không click toolbar.
                    for (const el of Array.from(document.querySelectorAll(
                        '#viewerContainer, .viewerContainer, .pdfViewer, .pdf-viewer, div'
                    ))) {
                        if (!visible(el)) continue;
                        const r = el.getBoundingClientRect();
                        if (r.left > window.innerWidth * 0.42 && r.height > 200) {
                            try { el.scrollTop = 0; } catch (_) {}
                        }
                    }

                    const selectors = [
                        '#viewer .page:first-child',
                        '.pdfViewer .page:first-child',
                        '.page[data-page-number="1"]',
                        'canvas',
                        'iframe[src]',
                        'embed[src]',
                        'object[data]',
                        '#viewerContainer',
                        '.viewerContainer',
                        '.pdfViewer',
                        '.pdf-viewer'
                    ];
                    const targets = [];
                    for (let priority = 0; priority < selectors.length; priority++) {
                        for (const el of Array.from(document.querySelectorAll(selectors[priority]))) {
                            if (!visible(el)) continue;
                            const r = el.getBoundingClientRect();
                            if (r.left < window.innerWidth * 0.42) continue;
                            const clipped = clampRect(r);
                            if (clipped.width < 120 || clipped.height < 160) continue;
                            targets.push({
                                ...clipped,
                                priority,
                                area: clipped.width * clipped.height
                            });
                        }
                    }

                    if (targets.length) {
                        targets.sort((a, b) => {
                            const priorityDiff = a.priority - b.priority;
                            if (priorityDiff !== 0) return priorityDiff;
                            return b.area - a.area;
                        });
                        const best = targets[0];
                        return {
                            x: best.x,
                            y: best.y,
                            width: best.width,
                            height: best.height,
                            strategy: 'viewer-element',
                            landscape: best.width > best.height * 1.08
                        };
                    }

                    // Dựa vào vị trí thanh công cụ bên phải như tool gốc, chỉ đo vị trí.
                    const toolbar = Array.from(
                        document.querySelectorAll('button, a, span, div, li')
                    ).filter(visible).map(el => {
                        const text = (el.innerText || el.textContent || '')
                            .replace(/\s+/g, ' ').trim().toLowerCase();
                        return { text, rect: el.getBoundingClientRect() };
                    }).filter(x =>
                        x.rect.left > window.innerWidth * 0.42 &&
                        (
                            x.text.includes('nhận dạng') ||
                            x.text.includes('nội dung toàn văn') ||
                            x.text.includes('hiệu chỉnh') ||
                            x.text.includes('file đính kèm') ||
                            x.text.includes('tải file')
                        )
                    );

                    if (toolbar.length) {
                        const left = Math.max(0, Math.min(...toolbar.map(x => x.rect.left)) - 25);
                        const top = Math.max(0, Math.max(...toolbar.map(x => x.rect.bottom)) + 8);
                        const width = window.innerWidth - left - 8;
                        const height = window.innerHeight - top - 8;
                        if (width >= 120 && height >= 160) {
                            return { x: left, y: top, width, height, strategy: 'toolbar-region' };
                        }
                    }

                    // Fallback cuối giống code gốc: 42% bên phải, dưới header.
                    const x = window.innerWidth * 0.58;
                    const y = window.innerHeight * 0.25;
                    const width = window.innerWidth - x - 8;
                    const height = window.innerHeight - y - 8;
                    if (width >= 120 && height >= 160) {
                        return { x, y, width, height, strategy: 'right-side-fallback' };
                    }
                    return null;
                }"""
            )
            if not clip:
                return None

            key = safe_record_key(record_key)
            png_path = self.output_dir / f"{key}-viewer.png"
            clip_payload = {
                "x": float(clip["x"]),
                "y": float(clip["y"]),
                "width": float(clip["width"]),
                "height": float(clip["height"]),
                "scale": 4.0 if bool(clip.get("landscape")) else 2.5,
            }

            # CDP can capture the same visible viewer region at a higher scale than
            # a normal CSS-pixel screenshot. This materially improves Vietnamese
            # diacritics and small italic abstracts.
            captured = False
            cdp = None
            try:
                cdp = await page.context.new_cdp_session(page)
                response = await cdp.send(
                    "Page.captureScreenshot",
                    {
                        "format": "png",
                        "fromSurface": True,
                        "captureBeyondViewport": False,
                        "clip": clip_payload,
                    },
                )
                png_path.write_bytes(base64.b64decode(response["data"]))
                captured = True
            except Exception as exc:
                logger.debug("CDP high-resolution screenshot failed: %s", exc)
            finally:
                if cdp is not None:
                    try:
                        await cdp.detach()
                    except Exception:
                        pass

            if not captured:
                await page.screenshot(
                    path=str(png_path),
                    clip={
                        "x": float(clip["x"]),
                        "y": float(clip["y"]),
                        "width": float(clip["width"]),
                        "height": float(clip["height"]),
                    },
                    animations="disabled",
                    scale="device",
                )
            if not png_path.exists() or png_path.stat().st_size < 1_000:
                return None

            from PIL import Image, ImageEnhance, ImageFilter

            pdf_path = self.output_dir / f"{key}-viewer.pdf"
            with Image.open(png_path) as image:
                rgb = image.convert("RGB")
                if rgb.width < 2200:
                    ratio = min(3.5, 2200 / max(1, rgb.width))
                    rgb = rgb.resize(
                        (int(rgb.width * ratio), int(rgb.height * ratio)),
                        Image.Resampling.LANCZOS,
                    )
                rgb = ImageEnhance.Contrast(rgb).enhance(1.08)
                rgb = rgb.filter(
                    ImageFilter.UnsharpMask(radius=1.1, percent=135, threshold=2)
                )
                rgb.save(png_path, "PNG", optimize=True)
                rgb.save(pdf_path, "PDF", resolution=300.0)

            data = pdf_path.read_bytes()
            if not looks_like_pdf(data, "application/pdf", str(pdf_path)):
                return None
            digest = hashlib.sha256(data).hexdigest()
            final_path = self.output_dir / f"{key}-{digest[:12]}.pdf"
            if final_path != pdf_path:
                if not final_path.exists():
                    final_path.write_bytes(data)
                pdf_path.unlink(missing_ok=True)
            logger.info(
                "Đã chụp vùng PDF viewer bằng chiến lược %s",
                clip.get("strategy", "unknown"),
            )
            return AcquiredPdf(
                path=final_path,
                sha256=digest,
                source=f"viewer-screenshot:{clip.get('strategy', 'unknown')}",
                original_url=str(page.url),
                size_bytes=len(data),
                image_path=png_path,
            )
        except Exception as exc:
            logger.warning("Không chụp được vùng PDF viewer: %s", exc)
            return None

    def _save(self, candidate: PdfCandidate, record_key: str) -> AcquiredPdf:
        if candidate.content is None or not looks_like_pdf(
            candidate.content, url=candidate.url
        ):
            raise PdfAcquisitionError(
                "Dữ liệu nhận được không phải PDF hợp lệ.", step="pdf_validate"
            )
        digest = hashlib.sha256(candidate.content).hexdigest()
        filename = f"{safe_record_key(record_key)}-{digest[:12]}.pdf"
        path = self.output_dir / filename
        if not path.exists():
            path.write_bytes(candidate.content)
        return AcquiredPdf(
            path=path,
            sha256=digest,
            source=candidate.source,
            original_url=candidate.url,
            size_bytes=len(candidate.content),
            image_path=None,
        )
