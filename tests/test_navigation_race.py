from __future__ import annotations

import asyncio

from cataloging_tool.automation.pages import DocumentListPage
from cataloging_tool.domain.models import DocumentListItem


class _BodyLocator:
    async def wait_for(self, **_kwargs):
        return None


class _FakePage:
    def __init__(self) -> None:
        self.url = "https://example.test/DocumentCataloging/DocView?id=old"
        self.goto_calls = 0

    async def evaluate(self, _script):
        return "complete"

    async def wait_for_timeout(self, _ms):
        return None

    def locator(self, selector):
        assert selector == "body"
        return _BodyLocator()

    async def goto(self, target, **_kwargs):
        self.goto_calls += 1
        if self.goto_calls == 1:
            self.url = "https://example.test/DocumentCataloging/DocView?id=old"
            raise RuntimeError(
                f'Page.goto: Navigation to "{target}" is interrupted by another navigation'
            )
        self.url = target
        return None


def test_open_record_recovers_from_interrupted_navigation() -> None:
    page = _FakePage()
    item = DocumentListItem(
        external_id="536069",
        edit_url="https://example.test/DocumentCataloging/UpdateDoc?id=536069",
        row_text="",
        position=1,
    )
    asyncio.run(DocumentListPage(page).open_record(item))
    assert page.goto_calls == 2
    assert "536069" in page.url
