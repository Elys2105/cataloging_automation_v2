from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from cataloging_tool.automation.pages import DocumentListPage
from cataloging_tool.automation.pdf_detector import PdfAcquirer
from cataloging_tool.domain.errors import VerificationError
from cataloging_tool.domain.models import DocumentListItem


class FakePage:
    def __init__(self) -> None:
        self.goto_calls: list[str] = []

    async def goto(self, url: str, wait_until: str = "") -> None:
        self.goto_calls.append(url)


class StubDocumentListPage(DocumentListPage):
    def __init__(self, page: FakePage, items: list[DocumentListItem]) -> None:
        super().__init__(page)
        self.items = items

    async def inventory_all(self, max_pages: int = 200) -> list[DocumentListItem]:
        return self.items


def item(position: int, status: str) -> DocumentListItem:
    return DocumentListItem(
        external_id=str(position),
        edit_url=f"https://example.test/UpdateDoc?id={position}",
        row_text=f"{position} văn bản {status}",
        position=position,
        current_status_text=status,
    )


def test_pdf_acquirer_never_has_browser_button_download_fallback(tmp_path) -> None:
    acquirer = PdfAcquirer(tmp_path)
    assert not hasattr(acquirer, "_try_browser_download")


def test_verify_all_completed_accepts_only_completed_rows() -> None:
    page = FakePage()
    listing = StubDocumentListPage(page, [item(1, "Hoàn thành"), item(2, "Hoàn thành")])
    completed, total = asyncio.run(
        listing.verify_all_completed("https://example.test/ListDocument?id=1")
    )
    assert (completed, total) == (2, 2)
    assert page.goto_calls == ["https://example.test/ListDocument?id=1"]


def test_verify_all_completed_rejects_incomplete_rows() -> None:
    page = FakePage()
    listing = StubDocumentListPage(page, [item(1, "Hoàn thành"), item(2, "Chưa hoàn thành")])
    with pytest.raises(VerificationError, match="chưa Hoàn thành"):
        asyncio.run(
            listing.verify_all_completed("https://example.test/ListDocument?id=1")
        )


class _SimpleLocator:
    def __init__(self, *, count_value: int = 0, text: str = "") -> None:
        self.count_value = count_value
        self.text = text
        self.first = self

    async def count(self) -> int:
        return self.count_value

    async def is_visible(self) -> bool:
        return self.count_value > 0

    async def inner_text(self) -> str:
        return self.text

    def get_by_role(self, *args, **kwargs):
        return _SimpleLocator(count_value=0)

    def nth(self, index: int):
        return self


class _SubmitButton:
    async def scroll_into_view_if_needed(self) -> None:
        return None

    async def click(self) -> None:
        return None


class _SubmitPage:
    def __init__(self) -> None:
        self.url = "https://example.test/DocumentCataloging/UpdateDoc?id=7"
        self.wait_kwargs = None

    def once(self, *args, **kwargs) -> None:
        return None

    def locator(self, selector: str):
        if selector == "body":
            return _SimpleLocator(count_value=1, text="Chi tiết tài liệu")
        return _SimpleLocator(count_value=0)

    def get_by_role(self, *args, **kwargs):
        return _SimpleLocator(count_value=0)

    async def wait_for_function(self, expression: str, *args, **kwargs) -> None:
        assert args == ()
        assert kwargs["arg"]["beforeUrl"].endswith("UpdateDoc?id=7")
        self.wait_kwargs = kwargs
        self.url = "https://example.test/DocumentCataloging/DocView?id=7"

    async def wait_for_load_state(self, *args, **kwargs) -> None:
        return None


def test_complete_wait_uses_keyword_arg_and_accepts_docview(monkeypatch) -> None:
    import cataloging_tool.automation.pages as pages_module

    async def fake_first_visible(*args):
        return _SubmitButton()

    monkeypatch.setattr(pages_module, "first_visible", fake_first_visible)
    page = _SubmitPage()
    edit = pages_module.DocumentEditPage(page=page, pdf_acquirer=None)
    asyncio.run(edit.complete_and_verify())
    assert page.wait_kwargs is not None


class _NextButton:
    first = None

    def __init__(self, page) -> None:
        self.page = page
        self.first = self

    async def count(self) -> int:
        return 1

    async def get_attribute(self, name: str):
        return None

    async def click(self) -> None:
        self.page.url = "https://example.test/ListDocument?pageIndex=2"


class _PagerPage:
    def __init__(self) -> None:
        self.url = "https://example.test/ListDocument?pageIndex=1"
        self.button = _NextButton(self)

    async def evaluate(self, expression: str):
        return True

    def locator(self, selector: str):
        return self.button

    async def wait_for_function(self, expression: str, *args, **kwargs) -> None:
        assert args == ()
        assert kwargs["arg"]["url"].endswith("pageIndex=1")

    async def wait_for_load_state(self, *args, **kwargs) -> None:
        return None

    async def wait_for_timeout(self, ms: int) -> None:
        return None


def test_next_page_wait_uses_keyword_arg() -> None:
    listing = DocumentListPage(_PagerPage())
    assert asyncio.run(listing._go_next_page("first row")) is True


class _FirstPageUrlOnly:
    def __init__(self) -> None:
        self.url = "https://example.test/ListDocument?IDProfile=1&pageIndex=6"
        self.goto_calls: list[str] = []

    async def goto(self, url: str, wait_until: str = "") -> None:
        self.goto_calls.append(url)
        self.url = url


def test_inventory_resets_url_pagination_to_first_page() -> None:
    page = _FirstPageUrlOnly()
    listing = DocumentListPage(page)
    asyncio.run(listing._go_first_page())
    assert page.goto_calls == [
        "https://example.test/ListDocument?IDProfile=1&pageIndex=1"
    ]


class _InterruptedSubmitPage(_SubmitPage):
    async def wait_for_function(self, expression: str, *args, **kwargs) -> None:
        assert args == ()
        assert "arg" in kwargs
        self.url = "https://example.test/DocumentCataloging/DocView?id=7"
        raise RuntimeError("Execution context was destroyed")

    async def wait_for_timeout(self, ms: int) -> None:
        return None


def test_submit_navigation_interruption_is_verified_by_destination(monkeypatch) -> None:
    import cataloging_tool.automation.pages as pages_module

    async def fake_first_visible(*args):
        return _SubmitButton()

    monkeypatch.setattr(pages_module, "first_visible", fake_first_visible)
    page = _InterruptedSubmitPage()
    edit = pages_module.DocumentEditPage(page=page, pdf_acquirer=None)
    asyncio.run(edit.complete_and_verify())
