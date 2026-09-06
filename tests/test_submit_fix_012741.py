from __future__ import annotations

import asyncio
import inspect

from cataloging_tool.automation.pages import DocumentEditPage


class _Locator:
    def __init__(self, count_value: int = 0, text: str = "") -> None:
        self.count_value = count_value
        self.text = text
        self.first = self

    async def count(self) -> int:
        return self.count_value

    async def is_visible(self) -> bool:
        return self.count_value > 0

    async def inner_text(self) -> str:
        return self.text

    def nth(self, _index: int):
        return self

    def get_by_role(self, *args, **kwargs):
        return _Locator()


class _LegacyButton:
    def __init__(self) -> None:
        self.clicks = 0

    async def scroll_into_view_if_needed(self) -> None:
        return None

    async def click(self) -> None:
        self.clicks += 1


class _PageWithoutEventApi:
    """Matches the lightweight page doubles in the existing safety tests."""

    def __init__(self) -> None:
        self.url = "https://example.test/DocumentCataloging/UpdateDoc?id=7"
        self.wait_called = False

    def once(self, *args, **kwargs) -> None:
        return None

    def locator(self, selector: str):
        if selector == "body":
            return _Locator(1, "Chi tiết tài liệu")
        return _Locator()

    def get_by_role(self, *args, **kwargs):
        return _Locator()

    async def wait_for_function(self, expression: str, *args, **kwargs) -> None:
        assert args == ()
        assert kwargs["arg"]["beforeUrl"].endswith("UpdateDoc?id=7")
        self.wait_called = True
        self.url = "https://example.test/DocumentCataloging/DocView?id=7"

    async def wait_for_load_state(self, *args, **kwargs) -> None:
        return None


def test_submit_supports_page_without_on_or_remove_listener(monkeypatch) -> None:
    import cataloging_tool.automation.pages as pages_module

    button = _LegacyButton()

    async def fake_first_visible(*args):
        return button

    monkeypatch.setattr(pages_module, "first_visible", fake_first_visible)
    page = _PageWithoutEventApi()
    asyncio.run(DocumentEditPage(page=page, pdf_acquirer=None).complete_and_verify())

    assert page.wait_called is True
    assert button.clicks == 1


def test_submit_source_keeps_single_click_and_short_timeout() -> None:
    source = inspect.getsource(DocumentEditPage.complete_and_verify)
    assert source.count("await button.click(") == 1
    assert "timeout=8000" in source
    assert "no_wait_after=True" in source
    assert "page_on = getattr(self.page, \"on\", None)" in source
