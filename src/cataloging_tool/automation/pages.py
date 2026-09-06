from __future__ import annotations

import asyncio
import hashlib
import html
import logging
import re
import unicodedata
from pathlib import Path
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import parse_qs, urljoin, urlparse

from cataloging_tool.domain.errors import (
    DocumentNotFoundError,
    ProfileNotFoundError,
    SubmissionError,
    SubmissionUncertainError,
    VerificationError,
)
from cataloging_tool.domain.models import DocumentListItem, FormSnapshot, ParsedDocument

from .pdf_detector import PdfAcquirer

logger = logging.getLogger(__name__)


def normalize_lookup(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "")
    text = text.replace("–", "-").replace("—", "-").replace("−", "-")
    text = re.sub(r"\s*([./-])\s*", r"\1", text)
    return re.sub(r"\s+", " ", text).strip().casefold()



def form_marks_unknown_document(form: FormSnapshot) -> bool:
    """Return True only for the explicit website placeholder record."""
    number = normalize_lookup(form.document_number)
    symbol = normalize_lookup(form.symbol)
    return number in {"không xác định", "khong xac dinh"} and symbol in {
        "",
        "ký hiệu văn bản",
        "ky hieu van ban",
        "không xác định",
        "khong xac dinh",
    }


def form_needs_full_metadata_recovery(form: FormSnapshot) -> bool:
    """Return True for records whose PDF must repopulate the complete metadata form.

    Besides the site's explicit ``Không xác định`` placeholder, some rows expose
    the same state as empty controls.  Treat only a fully empty/placeholder core
    form as recovery mode so partially catalogued normal records keep the legacy
    reconciliation path.
    """
    if form_marks_unknown_document(form):
        return True

    number = normalize_lookup(form.document_number)
    symbol = normalize_lookup(form.symbol)
    document_type = normalize_lookup(form.document_type)
    abstract = normalize_lookup(form.abstract)
    document_date = normalize_lookup(form.document_date)
    author = normalize_lookup(form.author)

    number_empty = number in {"", "không xác định", "khong xac dinh"}
    symbol_empty = symbol in {
        "", "ký hiệu văn bản", "ky hieu van ban",
        "không xác định", "khong xac dinh",
    }
    type_empty = document_type in {
        "", "--tên thể loại văn bản--", "--ten the loai van ban--",
        "tên thể loại văn bản", "ten the loai van ban", "khác", "khac",
    }
    return (
        number_empty
        and symbol_empty
        and type_empty
        and not abstract
        and not document_date
        and not author
    )


def viewer_reports_zero_pages(text: str) -> bool:
    """Return True only when every page-count signal is the explicit 0/0 state.

    The website keeps hidden/stale PDF toolbar nodes in the DOM.  A record with a
    visible ``1 trên 8`` viewer could therefore also expose a hidden ``0 trên 0``
    string and was incorrectly skipped.  Any positive page total is authoritative.
    """
    normalized = normalize_lookup(text)
    matches = re.findall(
        r"(?<!\d)(\d{1,4})\s*(?:trên|tren|of|/)\s*(\d{1,4})(?!\d)",
        normalized,
        flags=re.IGNORECASE,
    )
    if not matches:
        return False
    counts = [(int(current), int(total)) for current, total in matches]
    if any(total > 0 and current >= 1 for current, total in counts):
        return False
    return any(current == 0 and total == 0 for current, total in counts)


def external_id_from_url(url: str) -> str:
    query = parse_qs(urlparse(url).query)
    folded_query = {str(key).casefold(): value for key, value in query.items()}
    for key in (
        "id",
        "documentid",
        "document_id",
        "iddocument",
        "iddoc",
    ):
        if folded_query.get(key):
            return folded_query[key][0]
    return hashlib.sha1(url.encode("utf-8"), usedforsecurity=False).hexdigest()[:20]


_DOCUMENT_ROUTE_PATTERN = re.compile(
    r"(?P<url>(?:https?://[^\s\"'<>]+)?(?:/)?(?:DocumentCataloging/)?"
    r"(?:UpdateDoc|DocView)\?[^\s\"'<>)]*)",
    flags=re.IGNORECASE,
)
_DOCUMENT_CALL_PATTERN = re.compile(
    r"(?P<route>UpdateDoc|DocView)[^0-9]{0,100}(?P<id>[0-9]{2,12})",
    flags=re.IGNORECASE,
)
_DOCUMENT_NAMED_ID_PATTERN = re.compile(
    r"(?:idDocument|documentId|document_id|docId|data-document-id|data-doc-id)"
    r"\s*(?:=|:|,)\s*[\"']?(?P<id>[0-9]{2,12})",
    flags=re.IGNORECASE,
)


def _document_url_for_id(base_url: str, route: str, document_id: str) -> str:
    return urljoin(
        base_url,
        f"/DocumentCataloging/{route}?id={document_id}",
    )


def choose_document_record_url(base_url: str, raw_sources: list[str]) -> str:
    """Find one actionable document URL from a list-table row.

    Catalogued rows normally expose ``UpdateDoc``. Placeholder rows labelled
    ``Không xác định`` often expose only ``DocView`` through an eye icon or a
    JavaScript handler. Both identify a real row and must be inventoried before
    the PDF-existence check is allowed to decide whether the row is skippable.
    """
    candidates: list[str] = []
    for raw in raw_sources:
        value = html.unescape(str(raw or "")).replace(r"\/", "/")
        if not value:
            continue

        for match in _DOCUMENT_ROUTE_PATTERN.finditer(value):
            candidate = match.group("url").rstrip(".,;:")
            absolute = urljoin(base_url, candidate)
            if absolute not in candidates:
                candidates.append(absolute)

        # Some builds use onclick="DocView(536681)" instead of a literal href.
        for match in _DOCUMENT_CALL_PATTERN.finditer(value):
            route = match.group("route")
            document_id = match.group("id")
            absolute = _document_url_for_id(base_url, route, document_id)
            if absolute not in candidates:
                candidates.append(absolute)

        # If the row HTML contains a document-specific id but no literal route,
        # use DocView as the safe read route. Never infer an id from visible row
        # numbers/page counts; only named document-id attributes are accepted.
        if not any(token in value.casefold() for token in ("updatedoc", "docview")):
            for match in _DOCUMENT_NAMED_ID_PATTERN.finditer(value):
                absolute = _document_url_for_id(
                    base_url,
                    "DocView",
                    match.group("id"),
                )
                if absolute not in candidates:
                    candidates.append(absolute)

    # Prefer the edit route when both are present. Otherwise keep DocView; the
    # open step derives/clicks Chỉnh sửa before the form is filled.
    candidates.sort(
        key=lambda value: (0 if "updatedoc" in value.casefold() else 1)
    )
    return candidates[0] if candidates else ""


def update_doc_url_from_view(url: str) -> str:
    """Return the matching UpdateDoc route while preserving query/id."""
    parsed = urlparse(url)
    path = re.sub(r"(?i)/docview$", "/UpdateDoc", parsed.path)
    if path == parsed.path:
        return url
    return parsed._replace(path=path).geturl()


def reported_total_from_texts(texts: list[str]) -> int | None:
    """Read the document-row total without confusing it with total PDF pages.

    The profile page also contains text such as ``Tổng số lượng trang ... 212``.
    Therefore a body-text fallback may only trust counts explicitly tied to
    ``bản ghi`` or a pager range such as ``1 - 10 của 29``.
    """
    explicit_record_counts: list[int] = []
    pager_counts: list[int] = []

    for text in texts:
        folded = normalize_lookup(text)
        for pattern in (
            r"(?:có\s+)?tổng\s+cộng\s*([0-9][0-9.,]*)\s*bản\s*ghi",
            r"tổng\s*số\s*([0-9][0-9.,]*)\s*bản\s*ghi",
        ):
            for match in re.finditer(pattern, folded, flags=re.IGNORECASE):
                try:
                    explicit_record_counts.append(
                        int(re.sub(r"[^0-9]", "", match.group(1)))
                    )
                except ValueError:
                    pass

        for pattern in (
            r"[0-9]+\s*(?:-|đến)\s*[0-9]+\s*(?:/|của|trong\s+tổng\s+số)\s*"
            r"([0-9][0-9.,]*)",
            r"trang\s+[0-9]+\s*(?:/|của)\s*([0-9][0-9.,]*)\s*bản\s*ghi",
        ):
            for match in re.finditer(pattern, folded, flags=re.IGNORECASE):
                try:
                    pager_counts.append(
                        int(re.sub(r"[^0-9]", "", match.group(1)))
                    )
                except ValueError:
                    pass

    if explicit_record_counts:
        return max(explicit_record_counts)
    return max(pager_counts) if pager_counts else None


async def first_visible(*locators: Any) -> Any:
    for locator in locators:
        count = await locator.count()
        for index in range(count):
            candidate = locator.nth(index)
            if await candidate.is_visible():
                return candidate
    raise LookupError("Không tìm thấy element đang hiển thị")


@dataclass(frozen=True)
class ProfileCandidate:
    index: int
    text: str
    href: str | None


def choose_profile_candidate(
    candidates: list[ProfileCandidate], query: str
) -> ProfileCandidate | None:
    wanted = normalize_lookup(query)
    if not wanted:
        return None

    # Ưu tiên container có nguyên mã hồ sơ sau chuẩn hóa.
    for candidate in candidates:
        if wanted in normalize_lookup(candidate.text):
            return candidate
    return None


class ProfileListPage:
    def __init__(self, page: Any, artifact_root: Path | None = None) -> None:
        self.page = page
        self.artifact_root = artifact_root

    async def search_and_open(self, query: str) -> None:
        wanted = normalize_lookup(query)
        if not wanted or wanted == "...":
            raise ValueError("Số/ký hiệu hồ sơ không được để trống")

        # Nếu trình duyệt đã ở đúng danh sách tài liệu của hồ sơ thì không tìm lại.
        current_body = normalize_lookup(await self.page.locator("body").inner_text())
        current_url = str(self.page.url).casefold()
        if "listdocument" in current_url and wanted in current_body:
            logger.info("Đang ở sẵn danh sách hồ sơ %s", query)
            return

        search_input = await first_visible(
            self.page.get_by_placeholder(
                re.compile(r"nhập|số.*ký hiệu|hồ sơ|tiêu đề", re.IGNORECASE)
            ),
            self.page.locator(
                "input[placeholder*='Nhập'], "
                "input[placeholder*='Số'], "
                "input[placeholder*='hồ sơ'], "
                "input[placeholder*='Tiêu đề']"
            ),
            self.page.get_by_role("textbox").first,
        )
        await search_input.fill("")
        await search_input.fill(query)
        await search_input.press("Tab")

        try:
            search_button = await first_visible(
                self.page.get_by_role(
                    "button", name=re.compile(r"tìm kiếm|^tìm$", re.IGNORECASE)
                ),
                self.page.get_by_role(
                    "link", name=re.compile(r"tìm kiếm|^tìm$", re.IGNORECASE)
                ),
                self.page.locator(
                    "button:has-text('Tìm kiếm'), a:has-text('Tìm kiếm'), "
                    "button:has-text('Tìm'), a:has-text('Tìm')"
                ),
            )
            await search_button.click()
        except LookupError:
            # Một số phiên bản trang chỉ submit khi nhấn Enter trong ô tìm kiếm.
            await search_input.press("Enter")

        # Form tìm kiếm điều hướng sang URL có Keyword rồi server/AJAX mới dựng kết quả.
        try:
            await self.page.wait_for_load_state("domcontentloaded")
        except Exception:
            pass

        # Chờ một trong ba dấu hiệu: link hồ sơ, dòng dữ liệu, hoặc thông báo rỗng.
        try:
            await self.page.wait_for_function(
                r"""() => {
                    const body = (document.body?.innerText || document.body?.textContent || '')
                        .toLocaleLowerCase('vi');
                    return document.readyState === 'complete' && (
                        document.querySelectorAll("a[href*='ListDocument'], [onclick*='ListDocument']").length > 0 ||
                        document.querySelectorAll('tbody tr, [role="row"]').length > 1 ||
                        body.includes('không có dữ liệu') ||
                        body.includes('không tìm thấy')
                    );
                }""",
                timeout=30_000,
            )
        except Exception:
            logger.debug("Trang tìm kiếm chưa phát tín hiệu kết quả sau 30 giây: %s", query)

        # Cách ổn định nhất là đọc trực tiếp các link ListDocument và textContent của
        # container gần nhất. innerText có thể rỗng trên một số bảng/skin dù textContent có dữ liệu.
        candidates = await self._collect_profile_candidates()
        selected = choose_profile_candidate(candidates, query)
        if selected is not None:
            link = self.page.locator(
                "a[href*='ListDocument'], [onclick*='ListDocument']"
            ).nth(selected.index)
            if selected.href:
                target = urljoin(str(self.page.url), selected.href)
                logger.info("Đã tìm thấy hồ sơ %s; mở %s", query, target)
                await self.page.goto(target, wait_until="domcontentloaded")
            else:
                await link.click()
            try:
                await self.page.wait_for_url(re.compile(r"ListDocument", re.IGNORECASE))
            except Exception:
                await self.page.wait_for_load_state("domcontentloaded")
            await self._assert_document_list()
            return

        # Fallback: đọc textContent của mọi dòng thay vì chỉ innerText.
        rows = self.page.locator("tr, [role='row']")
        matches: list[Any] = []
        row_samples: list[str] = []
        for index in range(await rows.count()):
            row = rows.nth(index)
            raw_text = await self._locator_text(row)
            if raw_text and len(row_samples) < 12:
                row_samples.append(raw_text)
            if wanted in normalize_lookup(raw_text):
                matches.append(row)

        if matches:
            row = matches[0]
            link = await first_visible(
                row.locator("a[href*='ListDocument']"),
                row.locator("td:nth-child(3) a"),
                row.get_by_role("link", name=re.compile(r"tập lưu", re.IGNORECASE)),
                row.get_by_role("link"),
                row.locator(
                    "td:nth-child(3) [onclick], "
                    ".text-primary, .blue, [style*='blue']"
                ),
            )
            href = await link.get_attribute("href")
            if href:
                await self.page.goto(urljoin(str(self.page.url), href), wait_until="domcontentloaded")
            else:
                await link.click()
            try:
                await self.page.wait_for_url(re.compile(r"ListDocument", re.IGNORECASE))
            except Exception:
                await self.page.wait_for_load_state("domcontentloaded")
            await self._assert_document_list()
            return

        artifact_dir = (self.artifact_root or (Path.cwd() / "runtime" / "artifacts")) / "profile-search"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        safe_query = re.sub(r"[^0-9A-Za-z._-]+", "_", query).strip("_") or "unknown"
        screenshot_path = artifact_dir / f"{safe_query}.png"
        html_path = artifact_dir / f"{safe_query}.html"
        candidate_path = artifact_dir / f"{safe_query}-candidates.txt"
        try:
            await self.page.screenshot(path=str(screenshot_path), full_page=True)
            html_path.write_text(await self.page.content(), encoding="utf-8")
            candidate_path.write_text(
                "\n".join(
                    f"[{item.index}] href={item.href!r} text={item.text!r}"
                    for item in candidates
                )
                or "Không có link ListDocument/onclick ListDocument nào.",
                encoding="utf-8",
            )
        except Exception as exc:
            logger.debug("Không lưu được chẩn đoán tìm hồ sơ: %s", exc)

        sample_text = " | ".join(row_samples[:5]) or "không đọc được dòng bảng nào"
        candidate_sample = " | ".join(item.text for item in candidates[:5]) or "không có link hồ sơ"
        raise ProfileNotFoundError(
            f"Không tìm thấy hồ sơ: {query}. URL hiện tại: {self.page.url}. "
            f"Đã đọc {await rows.count()} dòng. Mẫu dòng: {sample_text}. "
            f"Link ứng viên: {candidate_sample}. "
            f"Ảnh/HTML/chẩn đoán: {artifact_dir}",
            step="search_profile",
            retryable=False,
        )

    async def _collect_profile_candidates(self) -> list[ProfileCandidate]:
        links = self.page.locator(
            "a[href*='ListDocument'], [onclick*='ListDocument']"
        )
        result: list[ProfileCandidate] = []
        for index in range(await links.count()):
            link = links.nth(index)
            try:
                data = await link.evaluate(
                    r"""el => {
                        const container = el.closest(
                            'tr, [role="row"], li, .card, .list-group-item, .dx-row, .k-master-row'
                        ) || el.parentElement || el;
                        const text = (
                            container.innerText || container.textContent ||
                            el.innerText || el.textContent || ''
                        ).replace(/\s+/g, ' ').trim();
                        return {
                            text,
                            href: el.getAttribute('href') || null
                        };
                    }"""
                )
            except Exception:
                continue
            text = re.sub(r"\s+", " ", str(data.get("text") or "")).strip()
            href = data.get("href")
            result.append(ProfileCandidate(index=index, text=text, href=href))
        return result

    @staticmethod
    async def _locator_text(locator: Any) -> str:
        try:
            text = await locator.inner_text(timeout=1_500)
        except Exception:
            text = ""
        if not text.strip():
            try:
                text = await locator.text_content(timeout=1_500) or ""
            except Exception:
                text = ""
        return re.sub(r"\s+", " ", text).strip()

    async def _assert_document_list(self) -> None:
        body = normalize_lookup(await self.page.locator("body").inner_text())
        if "danh sách thành phần hồ sơ" not in body and "listdocument" not in str(self.page.url).casefold():
            raise ProfileNotFoundError(
                "Đã click hồ sơ nhưng không vào được danh sách thành phần hồ sơ.",
                step="open_profile",
                retryable=True,
            )


class DocumentListPage:
    def __init__(self, page: Any) -> None:
        self.page = page

    async def inventory_all(self, max_pages: int = 200) -> list[DocumentListItem]:
        result: list[DocumentListItem] = []
        seen_urls: set[str] = set()
        seen_page_fingerprints: set[str] = set()
        position = 0

        # A previous run may leave Chrome on page 6/7. Always inventory from the
        # first page so progress reflects the entire profile, not only the last 10 rows.
        await self._go_first_page()

        for page_number in range(1, max_pages + 1):
            try:
                await self.page.wait_for_load_state("domcontentloaded")
            except Exception:
                pass
            rows = self.page.locator("table tbody tr, tr[role='row']")
            first_row_text = ""
            page_added = 0
            page_urls: list[str] = []
            unresolved_rows: list[str] = []
            for index in range(await rows.count()):
                row = rows.nth(index)
                cells = row.locator("td")
                if await cells.count() == 0:
                    continue
                try:
                    row_text = re.sub(r"\s+", " ", await row.inner_text()).strip()
                except Exception:
                    row_text = re.sub(r"\s+", " ", await row.text_content() or "").strip()
                if row_text and not first_row_text:
                    first_row_text = row_text
                absolute_url = await self._row_document_url(row)
                if not absolute_url:
                    unresolved_rows.append(row_text[:300])
                    continue
                page_urls.append(absolute_url)
                if absolute_url in seen_urls:
                    continue
                seen_urls.add(absolute_url)
                position += 1
                page_added += 1
                status_text = self._extract_status(row_text)
                result.append(
                    DocumentListItem(
                        external_id=external_id_from_url(absolute_url),
                        edit_url=absolute_url,
                        row_text=row_text,
                        position=position,
                        page_number=page_number,
                        current_status_text=status_text,
                    )
                )

            fingerprint_source = "|".join(page_urls) or first_row_text
            fingerprint = hashlib.sha1(
                fingerprint_source.encode("utf-8"), usedforsecurity=False
            ).hexdigest()
            if fingerprint_source and fingerprint in seen_page_fingerprints:
                raise VerificationError(
                    "Phân trang lặp lại cùng một trang; đã dừng để tránh xử lý trùng.",
                    step="pagination",
                )
            if fingerprint_source:
                seen_page_fingerprints.add(fingerprint)

            logger.info(
                "Đã quét trang danh sách %s: thêm %s bản ghi, tổng cộng %s",
                page_number,
                page_added,
                len(result),
            )
            if unresolved_rows:
                logger.warning(
                    "Trang %s có %s dòng tài liệu nhưng chưa lấy được URL. Mẫu: %s",
                    page_number,
                    len(unresolved_rows),
                    " | ".join(unresolved_rows[:3]),
                )

            if not await self._go_next_page(first_row_text):
                reported_total = await self._reported_total_records()
                if reported_total is not None and reported_total > len(result):
                    raise VerificationError(
                        f"Website báo có {reported_total} bản ghi nhưng tool mới quét được "
                        f"{len(result)}. Bộ phân trang chưa đi hết danh sách.",
                        step="pagination",
                    )
                logger.info(
                    "Hoàn tất kiểm kê: %s bản ghi trên %s trang",
                    len(result),
                    page_number,
                )
                return result

        raise VerificationError(
            f"Danh sách vượt giới hạn an toàn {max_pages} trang.", step="pagination"
        )

    async def _row_document_url(self, row: Any) -> str:
        """Read UpdateDoc/DocView from links, handlers and row HTML."""
        sources: list[str] = []
        try:
            sources.append(await row.evaluate("el => el.outerHTML || ''"))
        except Exception:
            pass

        elements = row.locator(
            "a, button, [onclick], [data-href], [data-url], [data-link], "
            "[data-document-id], [data-doc-id]"
        )
        for index in range(await elements.count()):
            element = elements.nth(index)
            for attribute in (
                "href",
                "onclick",
                "data-href",
                "data-url",
                "data-link",
                "data-document-id",
                "data-doc-id",
            ):
                try:
                    value = await element.get_attribute(attribute)
                except Exception:
                    value = None
                if value:
                    if attribute in {"data-document-id", "data-doc-id"}:
                        sources.append(f"{attribute}={value}")
                    else:
                        sources.append(value)
        return choose_document_record_url(str(self.page.url), sources)

    async def _wait_navigation_settled(self, timeout_ms: int = 6000) -> None:
        """Wait until URL and DOM ready state are stable across several polls."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_ms / 1000.0
        previous_url = ""
        stable_polls = 0
        while loop.time() < deadline:
            current_url = str(self.page.url)
            try:
                ready = await self.page.evaluate("document.readyState")
            except Exception:
                ready = ""
            if current_url == previous_url and ready in {"interactive", "complete"}:
                stable_polls += 1
                if stable_polls >= 3:
                    return
            else:
                stable_polls = 0
                previous_url = current_url
            await self.page.wait_for_timeout(180)

    async def open_record(self, item: DocumentListItem) -> None:
        """Open a record inventoried from either UpdateDoc or DocView.

        Placeholder rows often have no UpdateDoc link in the list. Their eye icon
        opens DocView, which still represents a real PDF-backed record. Try the
        matching UpdateDoc route first, then fall back to DocView + Chỉnh sửa.
        """
        original_target = item.edit_url
        target_id = external_id_from_url(original_target)
        targets = [original_target]
        if "docview" in original_target.casefold():
            derived = update_doc_url_from_view(original_target)
            targets = [derived, original_target] if derived != original_target else targets

        transient_tokens = (
            "err_aborted",
            "interrupted by another navigation",
            "navigation to",
            "execution context was destroyed",
        )

        await self._wait_navigation_settled(timeout_ms=4500)
        last_error: Exception | None = None
        for attempt in range(3):
            target = targets[min(attempt, len(targets) - 1)]
            try:
                await self.page.goto(target, wait_until="commit", timeout=30_000)
            except Exception as exc:
                last_error = exc
                message = str(exc).casefold()
                if any(token in message for token in transient_tokens):
                    # The previous Hoàn thành/redirect may still own the frame.
                    # Do not inspect that stale page as DocView and do not click
                    # its Chỉnh sửa control; retry the requested target directly.
                    await self.page.wait_for_timeout(350 * (attempt + 1))
                    continue

                # A derived UpdateDoc route may be rejected while the original
                # DocView is still valid. Move to that explicit fallback on the
                # next attempt. Other permanent navigation errors remain fatal.
                if target != original_target and "docview" in original_target.casefold():
                    await self.page.wait_for_timeout(350 * (attempt + 1))
                    continue

                raise DocumentNotFoundError(
                    f"Không mở được bản ghi {item.external_id}: {exc}",
                    step="open_record",
                    retryable=True,
                ) from exc

            await self._wait_navigation_settled(timeout_ms=6500)
            current_url = str(self.page.url)
            current_id = external_id_from_url(current_url)
            if (
                "updatedoc" in current_url.casefold()
                and (not target_id or current_id == target_id)
            ):
                try:
                    await self.page.locator("body").wait_for(state="visible", timeout=8000)
                except Exception:
                    pass
                return

            if "docview" in current_url.casefold():
                edit_controls = self.page.locator(
                    "a[href*='UpdateDoc'], button[onclick*='UpdateDoc'], "
                    "a[onclick*='UpdateDoc'], a:has-text('Chỉnh sửa'), "
                    "button:has-text('Chỉnh sửa')"
                )
                for index in range(await edit_controls.count()):
                    control = edit_controls.nth(index)
                    try:
                        if not await control.is_visible():
                            continue
                        href = await control.get_attribute("href")
                        if href and not href.casefold().startswith(("javascript:", "#")):
                            await self.page.goto(
                                urljoin(current_url, href),
                                wait_until="commit",
                                timeout=30_000,
                            )
                        else:
                            await control.click(timeout=8000)
                        await self._wait_navigation_settled(timeout_ms=6500)
                        landed = str(self.page.url)
                        if (
                            "updatedoc" in landed.casefold()
                            and (
                                not target_id
                                or external_id_from_url(landed) == target_id
                            )
                        ):
                            return
                    except Exception as exc:
                        last_error = exc
                        continue

            await self.page.wait_for_timeout(350 * (attempt + 1))

        raise DocumentNotFoundError(
            f"Không mở được đúng bản ghi {item.external_id} sau 3 lần điều hướng"
            + (f": {last_error}" if last_error else ""),
            step="open_record",
            retryable=True,
        )

    async def _go_first_page(self) -> None:
        current_url = str(self.page.url)
        parsed = urlparse(current_url)
        query = parse_qs(parsed.query)
        page_keys = ("pageIndex", "page", "PageIndex", "pageNumber")
        for key in page_keys:
            if key in query:
                current = query[key][0]
                if current not in {"", "0", "1"}:
                    replaced = re.sub(
                        rf"([?&]{re.escape(key)}=)[^&]+",
                        rf"\g<1>1",
                        current_url,
                        count=1,
                    )
                    await self.page.goto(replaced, wait_until="domcontentloaded")
                return

        await self.page.evaluate(
            r"""() => {
                document.querySelectorAll('[data-cataloging-first-page]')
                    .forEach(el => el.removeAttribute('data-cataloging-first-page'));
                const visible = el => {
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && s.display !== 'none' &&
                           s.visibility !== 'hidden';
                };
                const disabled = el => {
                    const cls = `${el.className || ''} ${el.closest('li')?.className || ''}`.toLowerCase();
                    return cls.includes('disabled') || el.disabled === true ||
                           el.getAttribute('aria-disabled') === 'true';
                };
                const controls = Array.from(document.querySelectorAll(
                    '.pagination a, .pagination button, .pager a, .pager button, ' +
                    '[class*="pagination"] a, [class*="pagination"] button'
                )).filter(el => visible(el) && !disabled(el));
                const label = el => (
                    el.innerText || el.textContent || el.getAttribute('aria-label') ||
                    el.getAttribute('title') || ''
                ).replace(/\s+/g, ' ').trim().toLowerCase();
                const active = document.querySelector(
                    '.pagination .active, .pagination [aria-current="page"], ' +
                    '.pager .active, [class*="pagination"] [aria-current="page"]'
                );
                const current = Number((active?.innerText || active?.textContent || '').trim());
                if (!Number.isFinite(current) || current <= 1) return false;
                const first = controls.find(el =>
                    ['«', '‹', 'trang đầu', 'first', '1'].includes(label(el)) ||
                    label(el).includes('first page')
                );
                if (!first) return false;
                first.setAttribute('data-cataloging-first-page', '1');
                return true;
            }"""
        )
        control = self.page.locator("[data-cataloging-first-page='1']").first
        if await control.count() == 0:
            return
        old_url = str(self.page.url)
        old_first = await self._first_row_text()
        href = await control.get_attribute("href")
        if href and not href.startswith(("#", "javascript:")):
            await self.page.goto(urljoin(old_url, href), wait_until="domcontentloaded")
        else:
            await control.click()
        try:
            await self.page.wait_for_function(
                r"""state => {
                    const row = document.querySelector('table tbody tr, tr[role="row"]');
                    const first = row ? (row.innerText || row.textContent || '')
                        .replace(/\s+/g, ' ').trim() : '';
                    return location.href !== state.url || (first && first !== state.first);
                }""",
                arg={"url": old_url, "first": old_first},
                timeout=20_000,
                polling=250,
            )
        except Exception:
            pass

    async def _go_next_page(self, old_first_row: str) -> bool:
        """Move to the next list page without assuming a single pager skin.

        Playwright's ``wait_for_function`` accepts the JavaScript argument only
        as the keyword-only ``arg=`` parameter. The former positional call made
        every pagination attempt fail and limited inventory to the first 10 rows.
        """
        old_url = str(self.page.url)
        await self.page.evaluate(
            r"""() => {
                document.querySelectorAll('[data-cataloging-next-page]')
                    .forEach(el => el.removeAttribute('data-cataloging-next-page'));

                const visible = el => {
                    if (!el) return false;
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 &&
                           s.display !== 'none' && s.visibility !== 'hidden';
                };
                const disabled = el => {
                    const cls = `${el.className || ''} ${el.closest('li')?.className || ''}`.toLowerCase();
                    return cls.includes('disabled') ||
                           el.disabled === true ||
                           el.getAttribute('aria-disabled') === 'true';
                };
                const label = el => (
                    el.innerText || el.textContent || el.getAttribute('aria-label') ||
                    el.getAttribute('title') || ''
                ).replace(/\s+/g, ' ').trim().toLowerCase();

                const all = Array.from(document.querySelectorAll(
                    '.pagination a, .pagination button, .pager a, .pager button, ' +
                    '[class*="pagination"] a, [class*="pagination"] button, ' +
                    '[class*="pager"] a, [class*="pager"] button, ' +
                    'a[aria-label], button[aria-label], a[title], button[title]'
                )).filter(el => visible(el) && !disabled(el));

                const direct = all.find(el => {
                    const t = label(el);
                    const cls = `${el.className || ''} ${el.closest('li')?.className || ''}`.toLowerCase();
                    return ['»', '›', '>', 'tiếp', 'trang sau', 'next'].includes(t) ||
                           /(^|\s)(next|pager-next|pagination-next)(\s|$)/.test(cls) ||
                           t.includes('trang tiếp') || t.includes('next page');
                });
                if (direct) {
                    direct.setAttribute('data-cataloging-next-page', '1');
                    return true;
                }

                const active = document.querySelector(
                    '.pagination .active, .pagination [aria-current="page"], ' +
                    '.pager .active, [class*="pagination"] [aria-current="page"]'
                );
                if (active) {
                    let sibling = active.nextElementSibling;
                    while (sibling) {
                        const candidate = sibling.matches('a,button')
                            ? sibling
                            : sibling.querySelector('a,button');
                        if (candidate && visible(candidate) && !disabled(candidate)) {
                            candidate.setAttribute('data-cataloging-next-page', '1');
                            return true;
                        }
                        sibling = sibling.nextElementSibling;
                    }
                }

                const current = Number((active?.innerText || active?.textContent || '').trim());
                if (Number.isFinite(current)) {
                    const numeric = all.find(el => Number(label(el)) === current + 1);
                    if (numeric) {
                        numeric.setAttribute('data-cataloging-next-page', '1');
                        return true;
                    }
                }
                return false;
            }"""
        )

        button = self.page.locator("[data-cataloging-next-page='1']").first
        if await button.count() == 0:
            return False

        href = await button.get_attribute("href")
        try:
            if href and not href.startswith(("#", "javascript:")):
                await self.page.goto(urljoin(old_url, href), wait_until="domcontentloaded")
            else:
                await button.click()

            await self.page.wait_for_function(
                r"""state => {
                    const row = document.querySelector('table tbody tr, tr[role="row"]');
                    const first = row ? (row.innerText || row.textContent || '')
                        .replace(/\s+/g, ' ').trim() : '';
                    return location.href !== state.url || (first && first !== state.first);
                }""",
                arg={"url": old_url, "first": old_first_row},
                timeout=30_000,
                polling=250,
            )
        except Exception:
            await self.page.wait_for_timeout(700)
            current_url = str(self.page.url)
            first = await self._first_row_text()
            if current_url == old_url and normalize_lookup(first) == normalize_lookup(old_first_row):
                logger.debug("Nút trang sau được click nhưng URL và dòng đầu không thay đổi")
                return False

        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=10_000)
        except Exception:
            pass
        return True

    async def _first_row_text(self) -> str:
        rows = self.page.locator("table tbody tr, tr[role='row']")
        for index in range(await rows.count()):
            row = rows.nth(index)
            if await row.locator("td").count() == 0:
                continue
            try:
                value = await row.inner_text()
            except Exception:
                value = await row.text_content() or ""
            value = re.sub(r"\s+", " ", value or "").strip()
            if value:
                return value
        return ""

    async def _reported_total_records(self) -> int | None:
        selectors = (
            ".dataTables_info, .pagination-info, .pager-info, .dx-info, "
            ".k-pager-info, [class*='pagination-info'], [class*='pager-info']"
        )
        texts = await self.page.locator(selectors).all_inner_texts()
        # This site renders ``Có tổng cộng 29 bản ghi`` in a plain footer rather
        # than a pager-info class, so include body text as a guarded fallback.
        try:
            texts.append(await self.page.locator("body").inner_text())
        except Exception:
            pass
        return reported_total_from_texts(texts)

    @staticmethod
    def _extract_status(row_text: str) -> str:
        normalized = normalize_lookup(row_text)
        if "chưa hoàn thành" in normalized:
            return "Chưa hoàn thành"
        if "hoàn thành" in normalized:
            return "Hoàn thành"
        return ""


    async def verify_all_completed(
        self, list_url: str, max_pages: int = 200, *, strict: bool = True
    ) -> tuple[int, int]:
        """Đọc lại toàn bộ danh sách sau khi bấm Hoàn thành."""
        await self.page.goto(list_url, wait_until="domcontentloaded")
        inventory = await self.inventory_all(max_pages=max_pages)
        if not inventory:
            raise VerificationError(
                "Không đọc được danh sách bản ghi để kiểm tra trạng thái Hoàn thành.",
                step="verify_all_completed",
            )

        incomplete = [
            item
            for item in inventory
            if normalize_lookup(item.current_status_text)
            != normalize_lookup("Hoàn thành")
        ]
        completed = len(inventory) - len(incomplete)
        if incomplete:
            samples = "; ".join(
                f"#{item.position}: {item.row_text[:180]}"
                for item in incomplete[:10]
            )
            message = (
                f"Còn {len(incomplete)}/{len(inventory)} bản ghi chưa Hoàn thành. "
                f"Mẫu: {samples}"
            )
            if strict:
                raise VerificationError(
                    message,
                    step="verify_all_completed",
                )
            logger.warning(message)
        return completed, len(inventory)


@dataclass(slots=True)
class DocumentEditPage:
    page: Any
    pdf_acquirer: PdfAcquirer
    artifact_root: Path | None = None

    async def acquire_pdf(self, record_key: str):
        return await self.pdf_acquirer.acquire(self.page, record_key)

    async def read_viewer_text(self) -> str:
        """Read a PDF.js/OCR text layer before raster OCR when one exists."""
        selectors = (
            ".textLayer span, .textLayer, [class*='textLayer'] span, "
            "#viewer .page:first-child .textLayer span, "
            ".pdfViewer .page:first-child .textLayer span"
        )
        candidates: list[str] = []
        for frame in self.page.frames:
            try:
                values = await frame.locator(selectors).all_inner_texts()
            except Exception:
                continue
            text = "\n".join(
                re.sub(r"\s+", " ", value).strip()
                for value in values
                if value.strip()
            )
            folded = normalize_lookup(text)
            if len(text) >= 60 and any(
                marker in folded
                for marker in (
                    "số ", "ke hoach", "cong van", "quyet dinh", "bao cao",
                    "thong bao", "to trinh", "nghi quyet", "chi thi",
                )
            ):
                candidates.append(text)
        return max(candidates, key=len) if candidates else ""

    async def capture_last_page_image(
        self, record_key: str, output_dir: Path
    ) -> Path | None:
        """Capture the final PDF page for signer OCR, then restore the page number.

        This is used only for an unidentified record whose signer field is empty.
        It never clicks upload/download controls.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        safe_key = re.sub(r"[^A-Za-z0-9._-]+", "-", record_key).strip("-._")
        target_path = output_dir / f"{safe_key or 'record'}-last-page.png"
        input_selectors = (
            "input#pageNumber, input.pageNumber, "
            "input.toolbarField.pageNumber, input[type='number']"
        )
        contexts = list(getattr(self.page, "frames", []) or []) or [self.page]

        for context in contexts:
            inputs = context.locator(input_selectors)
            try:
                count = await inputs.count()
            except Exception:
                continue
            for index in range(min(count, 8)):
                page_input = inputs.nth(index)
                current = ""
                try:
                    if not await page_input.is_visible(timeout=500):
                        continue
                    current = (await page_input.input_value()).strip() or "1"
                    max_value = await page_input.get_attribute("max")
                    aria_max = await page_input.get_attribute("aria-valuemax")
                    total = int(max_value or aria_max or 0)
                    if total <= 1:
                        nearby = await page_input.evaluate(
                            r"""el => {
                                const root = el.closest('.toolbar, .pdfViewer, #viewerContainer')
                                    || el.parentElement?.parentElement || document.body;
                                return (root?.innerText || document.body?.innerText || '')
                                    .replace(/\s+/g, ' ');
                            }"""
                        )
                        matches = re.findall(
                            r"(?:trên|tren|of|/)\s*(\d{1,4})",
                            str(nearby),
                            flags=re.IGNORECASE,
                        )
                        if matches:
                            total = max(int(value) for value in matches)
                    if total <= 1:
                        continue

                    try:
                        await page_input.fill(str(total))
                    except Exception:
                        await page_input.evaluate(
                            "(el, value) => { el.value = value; "
                            "el.dispatchEvent(new Event('input', {bubbles:true})); }",
                            str(total),
                        )
                    await page_input.press("Enter")
                    await self.page.wait_for_timeout(700)

                    selectors = (
                        f".page[data-page-number='{total}']",
                        f"#viewer .page[data-page-number='{total}']",
                        ".pdfViewer .page:last-child",
                        "#viewer .page:last-child",
                        "canvas",
                    )
                    best = None
                    best_area = 0.0
                    for selector in selectors:
                        locator = context.locator(selector)
                        try:
                            item_count = await locator.count()
                        except Exception:
                            continue
                        for item_index in range(min(item_count, 20)):
                            item = locator.nth(item_index)
                            try:
                                if not await item.is_visible(timeout=350):
                                    continue
                                box = await item.bounding_box()
                                if not box:
                                    continue
                                area = float(box["width"]) * float(box["height"])
                                if area > best_area and box["width"] > 200 and box["height"] > 250:
                                    best = item
                                    best_area = area
                            except Exception:
                                continue
                    if best is None:
                        continue
                    await best.screenshot(path=str(target_path), animations="disabled")
                    if target_path.exists() and target_path.stat().st_size > 1000:
                        return target_path
                except Exception as exc:
                    logger.debug("Không chụp được trang cuối PDF: %s", exc)
                finally:
                    try:
                        if current:
                            await page_input.fill(current)
                            await page_input.press("Enter")
                            await self.page.wait_for_timeout(250)
                    except Exception:
                        pass
        return None

    async def should_skip_missing_pdf(
        self, form: FormSnapshot, viewer_text: str = ""
    ) -> bool:
        """Detect the website's explicit broken placeholder record.

        Skip only when both conditions are true:
        1. The form says ``Không xác định`` and has no real symbol.
        2. After a short loading grace period, the viewer still reports 0/0.
        """
        if not form_marks_unknown_document(form):
            return False
        if viewer_text.strip():
            return False

        try:
            await self.page.wait_for_function(
                r"""() => {
                    const body = (document.body?.innerText || '')
                        .replace(/\s+/g, ' ').toLowerCase();
                    return !/(^|\D)0\s*(?:trên|tren|of|\/)\s*0(\D|$)/i.test(body);
                }""",
                timeout=3000,
                polling=250,
            )
        except Exception:
            pass

        body_text = await self.page.locator("body").inner_text()
        return viewer_reports_zero_pages(body_text)

    async def _read_document_date(self) -> str:
        """Read the three date selects as YYYY-MM-DD without depending on IDs."""
        contexts = list(getattr(self.page, "frames", []) or []) or [self.page]
        for context in contexts:
            try:
                value = await context.evaluate(
                    r"""() => {
                        const norm = value => (value || '')
                            .normalize('NFKC')
                            .toLocaleLowerCase('vi')
                            .replace(/\s+/g, ' ')
                            .trim();
                        const visible = el => {
                            if (!el) return false;
                            const style = getComputedStyle(el);
                            const rect = el.getBoundingClientRect();
                            return style.display !== 'none' &&
                                   style.visibility !== 'hidden' &&
                                   rect.width > 0 && rect.height > 0;
                        };
                        const labels = Array.from(document.querySelectorAll(
                            'label, span, td, th, div, p, strong'
                        )).filter(el => visible(el) &&
                            norm(el.innerText || el.textContent).includes(
                                'ngày, tháng, năm văn bản'
                            ));
                        for (const label of labels) {
                            const roots = [
                                label.closest('tr'),
                                label.closest('.form-group'),
                                label.closest('.row'),
                                label.parentElement
                            ].filter(Boolean);
                            for (const root of roots) {
                                const selects = Array.from(root.querySelectorAll('select'))
                                    .filter(visible)
                                    .sort((a, b) => a.getBoundingClientRect().left -
                                                     b.getBoundingClientRect().left);
                                if (selects.length < 3) continue;
                                const values = selects.slice(0, 3).map(el =>
                                    (el.selectedOptions[0]?.textContent || el.value || '')
                                        .replace(/\D+/g, '')
                                );
                                const year = values.find(v => /^20\d{2}$/.test(v)) || values[0];
                                const rest = values.filter(v => v !== year);
                                const month = rest[0] || values[1];
                                const day = rest[1] || values[2];
                                if (/^20\d{2}$/.test(year) && /^\d{1,2}$/.test(month) &&
                                    /^\d{1,2}$/.test(day)) {
                                    return `${year}-${month.padStart(2, '0')}-${day.padStart(2, '0')}`;
                                }
                            }
                        }
                        return '';
                    }"""
                )
                if value:
                    return str(value)
            except Exception:
                logger.debug("Không đọc được ngày văn bản trong frame", exc_info=True)
        return ""

    async def read_form(self) -> FormSnapshot:
        # Giá trị đang có trên form chỉ là nguồn fallback cho OCR/parser.
        # Không để một label HTML bất thường làm hỏng toàn bộ bản ghi ở bước đọc trước OCR.
        return FormSnapshot(
            document_number=await self._read_field_optional("Số văn bản"),
            symbol=await self._read_field_optional("Ký hiệu văn bản"),
            document_type=await self._read_field_optional("Tên thể loại văn bản"),
            abstract=await self._read_field_optional("Trích yếu nội dung"),
            document_date=await self._read_document_date(),
            author=await self._read_field_optional("Tác giả văn bản"),
            security_level=await self._read_field_optional("Độ mật"),
            signer_name=await self._read_field_optional("Tên người ký văn bản"),
        )

    async def fill_from_parsed(
        self,
        document: ParsedDocument,
        existing_form: FormSnapshot | None = None,
    ) -> FormSnapshot:
        abstract = re.split(
            r"\s+(?=(?:Thực\s+hiện|Thc\s+hin|Thuc\s+hien)\s+"
            r"(?:Kế\s+hoạch|Ke\s+hoach|Công\s+văn|Cong\s+van|"
            r"Quyết\s+định|Quyet\s+dinh|Nghị\s+quyết|Nghi\s+quyet|"
            r"Chương\s+trình|Chuong\s+trinh|Hướng\s+dẫn|Huong\s+dan)\b)",
            document.abstract.value,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip()
        before = existing_form or await self.read_form()
        recovering_empty_form = form_needs_full_metadata_recovery(before)

        # On the website's empty/``Không xác định`` form, number/symbol controls
        # can stay disabled until a document type is selected.  Select the type
        # first, then resolve the dependent controls.  Normal populated records
        # retain their previous fill order.
        if recovering_empty_form:
            await self._select_or_fill("Tên thể loại văn bản", document.document_type.value)
            await self._wait_field_ready("Số văn bản")
            await self._wait_field_ready("Ký hiệu văn bản")
            await self._fill_field("Số văn bản", document.document_number.value)
            await self._fill_field("Ký hiệu văn bản", document.symbol.value)
        else:
            await self._fill_field("Số văn bản", document.document_number.value)
            await self._fill_field("Ký hiệu văn bản", document.symbol.value)
            await self._select_or_fill("Tên thể loại văn bản", document.document_type.value)

        await self._fill_field("Trích yếu nội dung", abstract)
        await self._select_or_fill("Tác giả văn bản", document.author)
        await self._select_or_fill("Độ mật", document.security_level)
        if not before.document_date.strip() and document.document_date.value.strip():
            await self._fill_document_date(document.document_date.value)
        if not before.signer_name.strip() and document.signer_name.value.strip():
            await self._fill_field("Tên người ký văn bản", document.signer_name.value)
        actual = await self.read_form()
        expected = FormSnapshot(
            document_number=document.document_number.value,
            symbol=document.symbol.value,
            document_type=document.document_type.value,
            abstract=abstract,
            author=document.author,
            security_level=document.security_level,
            document_date=(before.document_date or document.document_date.value),
            signer_name=(before.signer_name or document.signer_name.value),
        )
        self._assert_form_matches(expected, actual)
        return actual

    async def _wait_field_ready(self, label: str, attempts: int = 30) -> None:
        """Wait until a dependent form control becomes enabled/locatable."""
        last_error: Exception | None = None
        for _ in range(attempts):
            try:
                field = await self._field_by_label(label)
                disabled = bool(await field.is_disabled()) if hasattr(field, "is_disabled") else False
                if not disabled:
                    return
            except Exception as exc:
                last_error = exc
            await asyncio.sleep(0.10)
        message = f"Trường {label} chưa sẵn sàng sau khi chọn thể loại văn bản"
        if last_error is not None:
            logger.debug(message, exc_info=last_error)
        raise SubmissionError(message, step="fill_form")

    async def _fill_document_date(self, value: str) -> None:
        """Fill dependent year/month/day selects in dependency order.

        The website repopulates month/day options after ``change`` events.  Do
        not set all three selects in one JavaScript turn: that can select stale
        options before the dependent dropdown has finished rebuilding.
        """
        match = re.fullmatch(r"(20\d{2})-(\d{2})-(\d{2})", (value or "").strip())
        if not match:
            raise SubmissionError(
                f"Ngày văn bản không hợp lệ: {value}", step="fill_document_date"
            )
        year, month, day = match.groups()
        contexts = list(getattr(self.page, "frames", []) or []) or [self.page]

        script = r"""({action, component, wanted}) => {
            const norm = value => (value || '').normalize('NFKC')
                .toLocaleLowerCase('vi').replace(/\s+/g, ' ').trim();
            const visible = el => {
                if (!el) return false;
                const st = getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return st.display !== 'none' && st.visibility !== 'hidden'
                    && r.width > 0 && r.height > 0;
            };
            const labels = Array.from(document.querySelectorAll(
                'label, span, td, th, div, p, strong'
            )).filter(el => visible(el) && norm(el.innerText || el.textContent)
                .includes('ngày, tháng, năm văn bản'));

            const digits = option =>
                (option?.textContent || option?.value || '').replace(/\D+/g, '');
            const equalsWanted = optionDigits =>
                optionDigits !== '' && String(Number(optionDigits)) === String(Number(wanted));

            for (const label of labels) {
                const roots = [label.closest('tr'), label.closest('.form-group'),
                    label.closest('.row'), label.parentElement].filter(Boolean);
                for (const root of roots) {
                    const selects = Array.from(root.querySelectorAll('select'))
                        .filter(visible)
                        .sort((a,b) => a.getBoundingClientRect().left
                            - b.getBoundingClientRect().left);
                    if (selects.length < 3) continue;

                    let yearSelect = selects.find(select => Array.from(select.options)
                        .some(option => /^20\d{2}$/.test(digits(option))));
                    yearSelect ||= selects[0];
                    const rest = selects.filter(select => select !== yearSelect);
                    if (rest.length < 2) continue;
                    const target = component === 'year'
                        ? yearSelect
                        : component === 'month'
                            ? rest[0]
                            : rest[1];

                    const option = Array.from(target.options)
                        .find(item => equalsWanted(digits(item)));
                    if (action === 'has-option') {
                        return Boolean(option);
                    }
                    if (action === 'selected') {
                        const current = digits(target.selectedOptions[0])
                            || String(target.value || '').replace(/\D+/g, '');
                        return equalsWanted(current);
                    }
                    if (action === 'set') {
                        if (!option) return false;
                        target.value = option.value;
                        target.dispatchEvent(new Event('input', {bubbles:true}));
                        target.dispatchEvent(new Event('change', {bubbles:true}));
                        target.dispatchEvent(new Event('blur', {bubbles:true}));
                        return true;
                    }
                }
            }
            return false;
        }"""

        async def wait_action(
            context: Any,
            *,
            action: str,
            component: str,
            wanted: str,
            attempts: int = 24,
        ) -> bool:
            for _ in range(attempts):
                if await context.evaluate(
                    script,
                    {
                        "action": action,
                        "component": component,
                        "wanted": wanted,
                    },
                ):
                    return True
                await asyncio.sleep(0.10)
            return False

        for context in contexts:
            try:
                success = True
                for component, wanted in (
                    ("year", year),
                    ("month", month),
                    ("day", day),
                ):
                    if not await wait_action(
                        context,
                        action="has-option",
                        component=component,
                        wanted=wanted,
                    ):
                        success = False
                        break
                    if not await context.evaluate(
                        script,
                        {
                            "action": "set",
                            "component": component,
                            "wanted": wanted,
                        },
                    ):
                        success = False
                        break
                    if not await wait_action(
                        context,
                        action="selected",
                        component=component,
                        wanted=wanted,
                        attempts=12,
                    ):
                        success = False
                        break
                    # Give the site's dependent-dropdown handler one event-loop
                    # turn before polling the next select's rebuilt options.
                    await asyncio.sleep(0.05)

                if success:
                    actual = await self._read_document_date()
                    if actual == value:
                        return
            except Exception:
                logger.debug("Không điền được ngày văn bản trong frame", exc_info=True)
        raise SubmissionError(
            f"Không điền được Ngày, tháng, năm văn bản: {value}",
            step="fill_document_date",
        )

    async def _capture_list_url(self) -> str:
        """Capture the nearest list URL before submit for definitive fallback verification."""
        try:
            hrefs = await self.page.locator(
                "a[href*='ListDocument'], [onclick*='ListDocument']"
            ).evaluate_all(
                """elements => elements.map(el =>
                    el.getAttribute('href') || el.getAttribute('onclick') || ''
                )"""
            )
            for raw in hrefs:
                value = str(raw or "")
                href_match = re.search(r"['\"]([^'\"]*ListDocument[^'\"]*)['\"]", value, re.IGNORECASE)
                candidate = href_match.group(1) if href_match else value
                if "listdocument" in candidate.casefold() and not candidate.casefold().startswith("javascript:"):
                    return urljoin(str(self.page.url), candidate)
        except Exception:
            logger.debug("Không đọc được link danh sách trước khi submit", exc_info=True)

        try:
            referrer = str(await self.page.evaluate("document.referrer || ''"))
            if "listdocument" in referrer.casefold():
                return referrer
        except Exception:
            logger.debug("Không đọc được document.referrer trước khi submit", exc_info=True)
        return ""

    async def _complete_button_visible(self) -> bool:
        locators = (
            self.page.get_by_role(
                "button", name=re.compile(r"^\s*hoàn thành\s*$", re.IGNORECASE)
            ),
            self.page.get_by_role(
                "link", name=re.compile(r"^\s*hoàn thành\s*$", re.IGNORECASE)
            ),
            self.page.locator(
                "input[type='button'][value*='Hoàn thành'], "
                "input[type='submit'][value*='Hoàn thành'], "
                "button:has-text('Hoàn thành'), a:has-text('Hoàn thành')"
            ),
        )
        for locator in locators:
            try:
                count = await locator.count()
                for index in range(min(count, 5)):
                    if await locator.nth(index).is_visible(timeout=750):
                        return True
            except Exception:
                continue
        return False

    async def _body_text_quick(self) -> str:
        try:
            return normalize_lookup(
                await self.page.locator("body").inner_text(timeout=1500)
            )
        except Exception:
            return ""

    async def _confirm_html_dialog_once(self) -> bool:
        """Confirm a website modal once; never re-click the Hoàn thành control."""
        for _ in range(5):
            try:
                dialogs = self.page.locator(
                    ".modal.show, .modal.in, [role='dialog']:visible, .swal2-popup:visible"
                )
                for index in range(await dialogs.count()):
                    dialog = dialogs.nth(index)
                    if not await dialog.is_visible(timeout=500):
                        continue
                    confirm = dialog.get_by_role(
                        "button",
                        name=re.compile(
                            r"^(đồng ý|xác nhận|có|ok|yes)$", re.IGNORECASE
                        ),
                    )
                    if await confirm.count() > 0 and await confirm.first.is_visible(timeout=500):
                        await confirm.first.click(timeout=3000, no_wait_after=True)
                        return True
            except Exception:
                logger.debug("Chưa thể xác nhận hộp thoại HTML", exc_info=True)
            wait_for_timeout = getattr(self.page, "wait_for_timeout", None)
            if callable(wait_for_timeout):
                await cast(Any, wait_for_timeout)(150)
            else:
                await asyncio.sleep(0)
        return False

    async def _verify_completed_from_list(
        self, list_url: str, external_id: str
    ) -> bool | None:
        """Return True/False when the exact row is found, otherwise None."""
        if not list_url or not external_id:
            return None
        try:
            await self.page.goto(list_url, wait_until="domcontentloaded", timeout=20_000)
        except Exception as exc:
            logger.warning("Không mở được danh sách để xác minh submit: %s", exc)
            return None

        try:
            await self.page.locator("body").wait_for(state="visible", timeout=5000)
        except Exception:
            pass

        links = self.page.locator(
            "a[href*='UpdateDoc'], [onclick*='UpdateDoc'], "
            "a[href*='DocView'], [onclick*='DocView']"
        )
        try:
            count = await links.count()
        except Exception:
            return None

        for index in range(count):
            link = links.nth(index)
            try:
                href = (await link.get_attribute("href")) or ""
                onclick = (await link.get_attribute("onclick")) or ""
                candidate = href or onclick
                if external_id not in candidate and external_id_from_url(
                    urljoin(list_url, href)
                ) != external_id:
                    continue
                row = link.locator("xpath=ancestor::tr[1]")
                if await row.count() == 0:
                    row = link.locator("xpath=ancestor::*[@role='row'][1]")
                row_text = normalize_lookup(
                    await row.first.inner_text(timeout=2500)
                )
                if "chưa hoàn thành" in row_text:
                    return False
                if "hoàn thành" in row_text:
                    return True
                return None
            except Exception:
                continue
        return None

    async def complete_and_verify(self) -> None:
        """Submit once, then verify independently without waiting 60 seconds in click()."""
        button = await first_visible(
            self.page.get_by_role(
                "button", name=re.compile(r"^\s*hoàn thành\s*$", re.IGNORECASE)
            ),
            self.page.get_by_role(
                "link", name=re.compile(r"^\s*hoàn thành\s*$", re.IGNORECASE)
            ),
            self.page.locator(
                "input[type='button'][value*='Hoàn thành'], "
                "input[type='submit'][value*='Hoàn thành']"
            ),
            self.page.locator(
                "button:has-text('Hoàn thành'), a:has-text('Hoàn thành')"
            ),
        )
        before_url = str(self.page.url)
        before_url_folded = before_url.casefold()
        external_id = external_id_from_url(before_url)
        list_url = await self._capture_list_url()
        submit_responses: list[tuple[str, int, str]] = []
        response_listener_attached = False

        def capture_response(response: Any) -> None:
            try:
                request = response.request
                method = str(request.method).upper()
                url = str(response.url)
                if method != "GET" and "documentcataloging" in url.casefold():
                    submit_responses.append((url, int(response.status), method))
            except Exception:
                pass

        async def accept_native_dialog(dialog: Any) -> None:
            try:
                await dialog.accept()
            except Exception:
                pass

        page_on = getattr(self.page, "on", None)
        if callable(page_on):
            try:
                page_on("response", capture_response)
                response_listener_attached = True
            except Exception:
                logger.debug("Không đăng ký được listener response", exc_info=True)

        page_once = getattr(self.page, "once", None)
        if callable(page_once):
            try:
                page_once("dialog", accept_native_dialog)
            except Exception:
                logger.debug("Không đăng ký được listener dialog", exc_info=True)

        try:
            try:
                await button.scroll_into_view_if_needed(timeout=5000)
            except TypeError:
                await button.scroll_into_view_if_needed()

            click_error: Exception | None = None
            try:
                try:
                    await button.click(timeout=8000, no_wait_after=True)
                except TypeError:
                    legacy_click = button.click
                    await legacy_click()
            except Exception as exc:
                click_error = exc
                current_url = str(self.page.url).casefold()
                destination_reached = any(
                    token in current_url
                    for token in (
                        "/documentcataloging/docview",
                        "/documentcataloging/listdocument",
                    )
                )
                message = str(exc).casefold()
                sidebar_intercepted = (
                    (
                        "intercepts pointer events" in message
                        or "intercepting pointer events" in message
                    )
                    and any(
                        token in message
                        for token in (
                            "main-sidebar",
                            "nav-menu-cust",
                            "os-content",
                        )
                    )
                )

                if not destination_reached and sidebar_intercepted:
                    try:
                        await button.evaluate("element => element.click()")
                    except Exception as dom_click_error:
                        dom_message = str(dom_click_error).casefold()
                        navigation_started = any(
                            token in dom_message
                            for token in (
                                "execution context was destroyed",
                                "most likely because of a navigation",
                                "frame was detached",
                            )
                        )
                        current_url = str(self.page.url).casefold()
                        destination_reached = any(
                            token in current_url
                            for token in (
                                "/documentcataloging/docview",
                                "/documentcataloging/listdocument",
                            )
                        )
                        if not navigation_started and not destination_reached:
                            raise SubmissionUncertainError(
                                "Sidebar che nút Hoàn thành và DOM click không gửi được thao tác: "
                                f"{dom_click_error}",
                                step="submit",
                                retryable=False,
                            ) from dom_click_error
                elif not destination_reached:
                    raise SubmissionUncertainError(
                        f"Không phát được một lần bấm Hoàn thành trong 8 giây: {exc}",
                        step="submit",
                        retryable=False,
                    ) from exc

            await self._confirm_html_dialog_once()

            wait_error: Exception | None = click_error
            wait_for_function = getattr(self.page, "wait_for_function", None)
            if callable(wait_for_function):
                try:
                    await cast(Any, wait_for_function)(
                        """state => {
                            const text = (document.body?.innerText || '').toLowerCase();
                            const href = location.href.toLowerCase();
                            const completeButtons = Array.from(document.querySelectorAll(
                                'button, a, input[type="button"], input[type="submit"]'
                            )).filter(el => {
                                const value = (el.innerText || el.value || '').trim().toLowerCase();
                                const rect = el.getBoundingClientRect();
                                return rect.width > 0 && rect.height > 0 && value === 'hoàn thành';
                            });
                            return text.includes('cập nhật tài liệu thành công') ||
                                   text.includes('cập nhật thành công') ||
                                   text.includes('hoàn thành thành công') ||
                                   href.includes('/documentcataloging/docview') ||
                                   href.includes('/documentcataloging/listdocument') ||
                                   location.href !== state.beforeUrl ||
                                   completeButtons.length === 0;
                        }""",
                        arg={"beforeUrl": before_url},
                        timeout=8000,
                        polling=200,
                    )
                except Exception as exc:
                    wait_error = exc
                    logger.warning(
                        "Chờ trạng thái submit bị gián đoạn; đang xác minh lại: %s", exc
                    )

            current_url_folded = str(self.page.url).casefold()
            if any(
                token in current_url_folded
                for token in (
                    "/documentcataloging/docview",
                    "/documentcataloging/listdocument",
                )
            ) and current_url_folded != before_url_folded:
                return

            wait_for_load_state = getattr(self.page, "wait_for_load_state", None)
            if callable(wait_for_load_state):
                try:
                    await cast(Any, wait_for_load_state)("domcontentloaded", timeout=4000)
                except Exception:
                    pass

            loop = asyncio.get_running_loop()
            deadline = loop.time() + 6.0
            last_body = ""
            while loop.time() < deadline:
                current_url = str(self.page.url)
                current_url_folded = current_url.casefold()
                body = await self._body_text_quick()
                if body:
                    last_body = body

                if any(
                    token in body
                    for token in (
                        "có lỗi xảy ra",
                        "không thành công",
                        "validation error",
                        "dữ liệu không hợp lệ",
                    )
                ):
                    raise SubmissionError(
                        "Website báo lỗi sau khi bấm Hoàn thành.", step="submit"
                    )

                if any(
                    token in body
                    for token in (
                        "cập nhật tài liệu thành công",
                        "cập nhật thành công",
                        "hoàn thành thành công",
                    )
                ):
                    return

                if current_url_folded != before_url_folded and any(
                    token in current_url_folded
                    for token in (
                        "/documentcataloging/docview",
                        "/documentcataloging/listdocument",
                    )
                ):
                    return

                accepted_response = any(
                    200 <= status < 400
                    for _url, status, _method in submit_responses
                )
                if accepted_response and not await self._complete_button_visible():
                    return

                wait_for_timeout = getattr(self.page, "wait_for_timeout", None)
                if callable(wait_for_timeout):
                    await cast(Any, wait_for_timeout)(250)
                else:
                    await asyncio.sleep(0.05)

            list_result = await self._verify_completed_from_list(list_url, external_id)
            if list_result is True:
                return
            if list_result is False:
                raise SubmissionUncertainError(
                    "Website đã nhận thao tác nhưng dòng danh sách vẫn chưa ở trạng thái Hoàn thành; "
                    "tool không bấm lại để tránh gửi trùng.",
                    step="submit",
                    retryable=False,
                )

            response_detail = ", ".join(
                f"{method} {status} {url}"
                for url, status, method in submit_responses[-3:]
            ) or "không ghi nhận phản hồi POST"
            button_detail = (
                "nút Hoàn thành còn hiển thị"
                if await self._complete_button_visible()
                else "nút Hoàn thành không còn hiển thị"
            )
            wait_detail = f"; lỗi chờ={wait_error}" if wait_error else ""
            raise SubmissionUncertainError(
                "Đã bấm Hoàn thành đúng một lần nhưng chưa có đủ bằng chứng xác minh; "
                f"{button_detail}; {response_detail}; URL={self.page.url}; "
                f"body={last_body[:240]!r}{wait_detail}",
                step="submit",
                retryable=False,
            )
        except SubmissionError:
            raise
        except SubmissionUncertainError:
            raise
        except Exception as exc:
            raise SubmissionUncertainError(
                f"Đã thao tác Hoàn thành đúng một lần nhưng chưa xác định kết quả: {exc}",
                step="submit",
                retryable=False,
            ) from exc
        finally:
            if response_listener_attached:
                remove_listener = getattr(self.page, "remove_listener", None)
                if callable(remove_listener):
                    try:
                        remove_listener("response", capture_response)
                    except Exception:
                        pass

    async def _read_field_optional(self, label: str) -> str:
        try:
            return await self._read_field(label)
        except SubmissionError as exc:
            logger.warning("Không đọc được trường %s; tiếp tục bằng OCR/parser: %s", label, exc)
            return ""

    async def _read_field(self, label: str) -> str:
        field = await self._field_by_label(label)
        tag = (await field.evaluate("el => el.tagName.toLowerCase()"))
        if tag == "select":
            selected = field.locator("option:checked")
            if await selected.count() > 0:
                return (await selected.first.inner_text()).strip()
        value = await field.input_value()
        return value.strip()

    async def _fill_field(self, label: str, value: str) -> None:
        expected = (value or "").strip()
        if not expected:
            raise SubmissionError(
                f"Không được điền rỗng trường bắt buộc: {label}",
                step="fill_form",
            )

        field = await self._field_by_label(label)
        try:
            await field.fill(expected)
        except Exception:
            await self._set_value_native(field, expected)

        actual = (await field.input_value()).strip()
        if normalize_lookup(actual) != normalize_lookup(expected):
            await self._set_value_native(field, expected)
            actual = (await field.input_value()).strip()

        if normalize_lookup(actual) != normalize_lookup(expected):
            raise SubmissionError(
                f"Điền trường {label} không thành công. "
                f"Mong đợi [{expected}], đọc lại [{actual}]",
                step="fill_form",
            )

    async def _set_value_native(self, field: Any, value: str) -> None:
        await field.evaluate(
            r"""(el, value) => {
                const tag = (el.tagName || '').toLowerCase();
                const proto = tag === 'textarea'
                    ? HTMLTextAreaElement.prototype
                    : HTMLInputElement.prototype;
                const descriptor = Object.getOwnPropertyDescriptor(proto, 'value');
                if (descriptor && descriptor.set) descriptor.set.call(el, '');
                else el.value = '';
                el.dispatchEvent(new Event('input', { bubbles: true }));
                if (descriptor && descriptor.set) descriptor.set.call(el, value);
                else el.value = value;
                el.setAttribute('value', value);
                for (const name of ['input', 'change', 'keyup', 'blur']) {
                    const event = name === 'keyup'
                        ? new KeyboardEvent(
                            name, { bubbles: true, key: 'Unidentified' }
                          )
                        : new Event(name, { bubbles: true });
                    el.dispatchEvent(event);
                }
            }""",
            value,
        )

    async def _select_or_fill(self, label: str, value: str) -> None:
        expected = (value or "").strip()
        if not expected:
            raise SubmissionError(
                f"Không được chọn rỗng trường bắt buộc: {label}",
                step="fill_form",
            )

        field = await self._field_by_label(label)
        tag = await field.evaluate("el => el.tagName.toLowerCase()")
        if tag != "select":
            await self._fill_field(label, expected)
            return

        options = await field.locator("option").evaluate_all(
            "els => els.map(el => ({value: el.value || '', "
            r"text: (el.textContent || '').replace(/\s+/g, ' ').trim()}))"
        )
        wanted = normalize_lookup(expected)
        matched = next(
            (
                item
                for item in options
                if normalize_lookup(str(item.get("text", ""))) == wanted
            ),
            None,
        )
        if matched is None:
            matched = next(
                (
                    item
                    for item in options
                    if wanted
                    in normalize_lookup(str(item.get("text", "")))
                    or normalize_lookup(str(item.get("text", "")))
                    in wanted
                ),
                None,
            )
        if matched is None:
            raise SubmissionError(
                f"Không tìm thấy lựa chọn [{expected}] cho trường {label}",
                step="fill_form",
            )

        await field.select_option(value=str(matched.get("value", "")))
        await field.evaluate(
            "el => { "
            "el.dispatchEvent(new Event('input', {bubbles:true})); "
            "el.dispatchEvent(new Event('change', {bubbles:true})); "
            "el.dispatchEvent(new Event('blur', {bubbles:true})); }"
        )
        actual = await self._read_field(label)
        if normalize_lookup(actual) != wanted:
            raise SubmissionError(
                f"Chọn trường {label} không thành công. "
                f"Mong đợi [{expected}], đọc lại [{actual}]",
                step="fill_form",
            )

    async def _field_by_label(self, label: str) -> Any:
        # 1) Ưu tiên quan hệ label-control chuẩn HTML/ARIA trên mọi frame.
        contexts = list(getattr(self.page, "frames", []) or [])
        if not contexts:
            contexts = [self.page]

        hidden_select_fallback: Any | None = None
        for context in contexts:
            try:
                by_label = context.get_by_label(re.compile(re.escape(label), re.IGNORECASE))
                for index in range(await by_label.count()):
                    candidate = by_label.nth(index)
                    tag = await candidate.evaluate("el => (el.tagName || '').toLowerCase()")
                    field_type = (
                        await candidate.get_attribute("type") or ""
                    ).casefold()
                    if tag not in {"input", "textarea", "select"}:
                        continue
                    if field_type in {"hidden", "button", "submit", "reset", "file"}:
                        continue
                    if await candidate.is_visible():
                        return candidate
                    if tag == "select" and hidden_select_fallback is None:
                        hidden_select_fallback = candidate
            except Exception:
                logger.debug("Không dùng được get_by_label cho %s trong frame", label)

        # 2) Website hiện tại dùng nhiều span/div/td thay cho thẻ label. Đánh dấu
        # field gần label nhất bằng JavaScript rồi trả lại dưới dạng Locator.
        marker = "cataloging-" + hashlib.sha1(
            f"{label}-{id(self)}".encode("utf-8"), usedforsecurity=False
        ).hexdigest()[:16]
        for context in contexts:
            try:
                found = await context.evaluate(
                    r"""({ wanted, marker }) => {
                        function norm(value) {
                            return (value || '')
                                .normalize('NFKC')
                                .toLocaleLowerCase('vi')
                                .replace(/\(\s*\*\s*\)/g, '')
                                .replace(/\*/g, '')
                                .replace(/[：:]/g, '')
                                .replace(/\s+/g, ' ')
                                .trim();
                        }

                        function visible(el) {
                            if (!el) return false;
                            const style = window.getComputedStyle(el);
                            if (style.display === 'none' || style.visibility === 'hidden') return false;
                            const rect = el.getBoundingClientRect();
                            return rect.width > 0 && rect.height > 0;
                        }

                        function usableField(el, allowHiddenSelect = false) {
                            if (!el) return false;
                            const tag = (el.tagName || '').toLowerCase();
                            if (!['input', 'textarea', 'select'].includes(tag)) return false;
                            const type = (el.getAttribute('type') || '').toLowerCase();
                            if (['hidden', 'button', 'submit', 'reset', 'file'].includes(type)) return false;
                            if (el.disabled) return false;
                            if (tag !== 'select' && el.readOnly) return false;
                            return visible(el) || (allowHiddenSelect && tag === 'select');
                        }

                        const wantedNorm = norm(wanted);
                        function labelMatches(text) {
                            const current = norm(text);
                            if (!current) return false;
                            if (wantedNorm === 'số văn bản') {
                                return current === 'số văn bản' && !current.includes('số thứ tự');
                            }
                            if (wantedNorm === 'ký hiệu văn bản') {
                                return current === 'ký hiệu văn bản';
                            }
                            if (wantedNorm === 'tác giả văn bản') {
                                return current.includes('tác giả văn bản') &&
                                       !current.includes('tên người ký') && current.length <= 60;
                            }
                            return current === wantedNorm ||
                                   (current.includes(wantedNorm) && current.length <= 90);
                        }

                        const labelNodes = Array.from(
                            document.querySelectorAll('label, span, td, th, div, p, strong')
                        ).filter(el => visible(el) && labelMatches(el.innerText || el.textContent))
                         .sort((a, b) => {
                             const ra = a.getBoundingClientRect();
                             const rb = b.getBoundingClientRect();
                             return (ra.width * ra.height) - (rb.width * rb.height);
                         });

                        const allFields = Array.from(
                            document.querySelectorAll('input, textarea, select')
                        ).filter(el => usableField(el, true));

                        function scoreField(labelEl, field) {
                            const lr = labelEl.getBoundingClientRect();
                            const fr = field.getBoundingClientRect();
                            const ly = lr.top + lr.height / 2;
                            const fy = fr.top + fr.height / 2;
                            const horizontalPenalty = fr.left >= lr.left ? 0 : 1000;
                            const rowPenalty = Math.abs(fy - ly) * 8;
                            const distance = Math.abs(fr.left - lr.right) + Math.abs(fr.top - lr.top);
                            const hiddenPenalty = visible(field) ? 0 : 500;
                            return horizontalPenalty + rowPenalty + distance + hiddenPenalty;
                        }

                        function chooseFrom(labelEl) {
                            const forId = labelEl.getAttribute && labelEl.getAttribute('for');
                            if (forId) {
                                const direct = document.getElementById(forId);
                                if (usableField(direct, true)) return direct;
                            }

                            const roots = [];
                            for (const selector of [
                                'tr', '.form-group', '.form-row', '.row', '.mb-3', '.mb-2',
                                '.field', '.control-group', 'fieldset'
                            ]) {
                                const root = labelEl.closest && labelEl.closest(selector);
                                if (root && !roots.includes(root)) roots.push(root);
                            }
                            if (labelEl.parentElement && !roots.includes(labelEl.parentElement)) {
                                roots.push(labelEl.parentElement);
                            }

                            for (const root of roots) {
                                const candidates = Array.from(
                                    root.querySelectorAll('input, textarea, select')
                                ).filter(el => usableField(el, true));
                                if (candidates.length) {
                                    candidates.sort((a, b) => scoreField(labelEl, a) - scoreField(labelEl, b));
                                    const best = candidates[0];
                                    if (wantedNorm !== 'tác giả văn bản') return best;
                                    const lr = labelEl.getBoundingClientRect();
                                    const br = best.getBoundingClientRect();
                                    if (Math.abs((br.top + br.height / 2) - (lr.top + lr.height / 2)) <= 35) {
                                        return best;
                                    }
                                }
                            }

                            const lr = labelEl.getBoundingClientRect();
                            const ly = lr.top + lr.height / 2;
                            const geometric = allFields.filter(field => {
                                const fr = field.getBoundingClientRect();
                                const fy = fr.top + fr.height / 2;
                                if (wantedNorm === 'tác giả văn bản') {
                                    return fr.left > lr.left && Math.abs(fy - ly) <= 35;
                                }
                                return fr.left > lr.left &&
                                       fr.top >= lr.top - 55 &&
                                       fy <= ly + 130;
                            });
                            geometric.sort((a, b) => scoreField(labelEl, a) - scoreField(labelEl, b));
                            return geometric[0] || null;
                        }

                        for (const labelEl of labelNodes) {
                            const field = chooseFrom(labelEl);
                            if (!field) continue;
                            field.setAttribute('data-cataloging-field-marker', marker);
                            return true;
                        }
                        return false;
                    }""",
                    {"wanted": label, "marker": marker},
                )
                if found:
                    marked = context.locator(
                        f'[data-cataloging-field-marker="{marker}"]'
                    )
                    if await marked.count() > 0:
                        return marked.first
            except Exception as exc:
                logger.debug("Không định vị được trường %s trong frame: %s", label, exc)

        if hidden_select_fallback is not None:
            return hidden_select_fallback

        await self._capture_form_field_diagnostics(label)
        raise SubmissionError(
            f"Không tìm thấy trường: {label}. Đã lưu chẩn đoán tại "
            f"{(self.artifact_root or (Path.cwd() / 'runtime' / 'artifacts')) / 'form-fields'}",
            step="find_form_field",
        )

    async def _capture_form_field_diagnostics(self, label: str) -> None:
        artifact_dir = (self.artifact_root or (Path.cwd() / "runtime" / "artifacts")) / "form-fields"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        safe_label = re.sub(r"[^0-9A-Za-zÀ-ỹ._-]+", "_", label).strip("_") or "field"
        url_hash = hashlib.sha1(
            str(self.page.url).encode("utf-8"), usedforsecurity=False
        ).hexdigest()[:10]
        stem = f"{url_hash}-{safe_label}"
        try:
            await self.page.screenshot(path=str(artifact_dir / f"{stem}.png"), full_page=True)
            (artifact_dir / f"{stem}.html").write_text(
                await self.page.content(), encoding="utf-8"
            )
            candidates = await self.page.evaluate(
                r"""() => {
                    function visible(el) {
                        const r = el.getBoundingClientRect();
                        return r.width > 0 && r.height > 0;
                    }
                    return Array.from(document.querySelectorAll('input, textarea, select'))
                        .filter(visible)
                        .map((el, index) => ({
                            index,
                            tag: (el.tagName || '').toLowerCase(),
                            id: el.id || '',
                            name: el.getAttribute('name') || '',
                            type: el.getAttribute('type') || '',
                            placeholder: el.getAttribute('placeholder') || '',
                            value: el.value || '',
                            ariaLabel: el.getAttribute('aria-label') || ''
                        }));
                }"""
            )
            (artifact_dir / f"{stem}-fields.txt").write_text(
                "\n".join(str(item) for item in candidates), encoding="utf-8"
            )
        except Exception as exc:
            logger.debug("Không lưu được chẩn đoán form %s: %s", label, exc)

    @staticmethod
    def _assert_form_matches(expected: FormSnapshot, actual: FormSnapshot) -> None:
        pairs = [
            ("Số văn bản", expected.document_number, actual.document_number),
            ("Ký hiệu", expected.symbol, actual.symbol),
            ("Thể loại", expected.document_type, actual.document_type),
            ("Trích yếu", expected.abstract, actual.abstract),
            ("Tác giả", expected.author, actual.author),
            ("Độ mật", expected.security_level, actual.security_level),
        ]
        if expected.document_date:
            pairs.append(("Ngày văn bản", expected.document_date, actual.document_date))
        if expected.signer_name:
            pairs.append(("Tên người ký", expected.signer_name, actual.signer_name))
        mismatches = [name for name, left, right in pairs if normalize_lookup(left) != normalize_lookup(right)]
        if mismatches:
            raise SubmissionError(
                "Dữ liệu đọc lại không khớp ở: " + ", ".join(mismatches),
                step="verify_form_before_submit",
            )
