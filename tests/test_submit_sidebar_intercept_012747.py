from __future__ import annotations

import asyncio

import pytest

from cataloging_tool.automation.pages import DocumentEditPage
from cataloging_tool.domain.errors import SubmissionUncertainError


INTERCEPT_MESSAGE = """
Locator.click: Timeout 8000ms exceeded.
<div class="os-content">...</div>
from <aside class="main-sidebar nav-menu-cust openIcon">...</aside>
intercepts pointer events
"""


class _Locator:
    def __init__(self, count_value: int = 0, text: str = "") -> None:
        self.count_value = count_value
        self.text = text
        self.first = self

    async def count(self) -> int:
        return self.count_value

    async def is_visible(self, **_kwargs) -> bool:
        return self.count_value > 0

    async def inner_text(self, **_kwargs) -> str:
        return self.text

    async def evaluate_all(self, _script):
        return []

    def nth(self, _index: int):
        return self

    def get_by_role(self, *args, **kwargs):
        return _Locator()


class _Page:
    def __init__(self) -> None:
        self.url = "https://example.test/DocumentCataloging/UpdateDoc?id=7"

    def locator(self, selector: str):
        if selector == "body":
            return _Locator(1, "Chi tiết tài liệu")
        return _Locator()

    def get_by_role(self, *args, **kwargs):
        return _Locator()

    async def evaluate(self, _script: str):
        return ""

    async def wait_for_function(self, *args, **kwargs) -> None:
        return None

    async def wait_for_load_state(self, *args, **kwargs) -> None:
        return None

    async def wait_for_timeout(self, _ms: int) -> None:
        return None


class _SidebarBlockedButton:
    def __init__(self, page: _Page, *, navigate_before_error: bool = False) -> None:
        self.page = page
        self.navigate_before_error = navigate_before_error
        self.click_calls = 0
        self.dom_click_calls = 0

    async def scroll_into_view_if_needed(self, **_kwargs) -> None:
        return None

    async def click(self, **kwargs) -> None:
        self.click_calls += 1
        assert kwargs == {"timeout": 8000, "no_wait_after": True}
        if self.navigate_before_error:
            self.page.url = "https://example.test/DocumentCataloging/DocView?id=7"
        raise RuntimeError(INTERCEPT_MESSAGE)

    async def evaluate(self, script: str):
        assert "element.click()" in script
        self.dom_click_calls += 1
        self.page.url = "https://example.test/DocumentCataloging/DocView?id=7"
        return None


class _UnknownTimeoutButton:
    def __init__(self) -> None:
        self.dom_click_calls = 0

    async def scroll_into_view_if_needed(self, **_kwargs) -> None:
        return None

    async def click(self, **_kwargs) -> None:
        raise RuntimeError("Locator.click: Timeout 8000ms exceeded")

    async def evaluate(self, _script: str):
        self.dom_click_calls += 1
        raise AssertionError("Unknown timeout must not use DOM fallback")


def test_sidebar_pointer_interception_uses_dom_click_once(monkeypatch) -> None:
    import cataloging_tool.automation.pages as pages_module

    page = _Page()
    button = _SidebarBlockedButton(page)

    async def fake_first_visible(*_args):
        return button

    monkeypatch.setattr(pages_module, "first_visible", fake_first_visible)
    asyncio.run(DocumentEditPage(page=page, pdf_acquirer=None).complete_and_verify())

    assert button.click_calls == 1
    assert button.dom_click_calls == 1
    assert "/DocView" in page.url


def test_destination_reached_does_not_dom_click_again(monkeypatch) -> None:
    import cataloging_tool.automation.pages as pages_module

    page = _Page()
    button = _SidebarBlockedButton(page, navigate_before_error=True)

    async def fake_first_visible(*_args):
        return button

    monkeypatch.setattr(pages_module, "first_visible", fake_first_visible)
    asyncio.run(DocumentEditPage(page=page, pdf_acquirer=None).complete_and_verify())

    assert button.click_calls == 1
    assert button.dom_click_calls == 0


def test_unknown_timeout_never_uses_dom_fallback(monkeypatch) -> None:
    import cataloging_tool.automation.pages as pages_module

    page = _Page()
    button = _UnknownTimeoutButton()

    async def fake_first_visible(*_args):
        return button

    monkeypatch.setattr(pages_module, "first_visible", fake_first_visible)

    with pytest.raises(SubmissionUncertainError, match="Không phát được"):
        asyncio.run(DocumentEditPage(page=page, pdf_acquirer=None).complete_and_verify())

    assert button.dom_click_calls == 0
