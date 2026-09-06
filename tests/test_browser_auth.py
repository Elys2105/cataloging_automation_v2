from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from cataloging_tool.automation.browser import BrowserSession
from cataloging_tool.config.settings import BrowserSettings
from cataloging_tool.domain.errors import AuthenticationExpiredError


class FakeLocator:
    def __init__(self, count: int) -> None:
        self._count = count

    async def count(self) -> int:
        return self._count


class FakePage:
    def __init__(self, url: str, visible_password_count: int) -> None:
        self.url = url
        self.visible_password_count = visible_password_count

    def locator(self, selector: str) -> FakeLocator:
        assert selector == "input[type='password']:visible"
        return FakeLocator(self.visible_password_count)


class LoginThenAuthenticatedPage(FakePage):
    async def wait_for_timeout(self, _milliseconds: int) -> None:
        self.url = "https://example.test/DocumentCataloging/ListDocument?IDProfile=1"
        self.visible_password_count = 0


def make_session() -> BrowserSession:
    return BrowserSession(
        settings=BrowserSettings(
            base_url="https://example.test/DocumentCataloging",
            channel="chrome",
            headless=False,
            timeout_ms=30_000,
            profile_dir=Path("profile"),
            manual_login_timeout_ms=2_000,
        ),
        profile_dir=Path("profile"),
        downloads_dir=Path("downloads"),
        trace_dir=Path("traces"),
    )


def test_authenticated_page_allows_hidden_login_modal() -> None:
    page = FakePage(
        "https://example.test/DocumentCataloging/ListDocument?IDProfile=1",
        visible_password_count=0,
    )
    asyncio.run(make_session()._assert_authenticated(page))


def test_visible_password_field_is_login_evidence() -> None:
    page = FakePage("https://example.test/", visible_password_count=1)
    with pytest.raises(AuthenticationExpiredError):
        asyncio.run(make_session()._assert_authenticated(page))


def test_login_url_is_login_evidence() -> None:
    page = FakePage("https://example.test/Account/Login", visible_password_count=0)
    with pytest.raises(AuthenticationExpiredError):
        asyncio.run(make_session()._assert_authenticated(page))


def test_interactive_login_wait_continues_after_user_authenticates() -> None:
    page = LoginThenAuthenticatedPage(
        "https://example.test/Account/Login",
        visible_password_count=1,
    )
    asyncio.run(make_session()._wait_for_interactive_login(page))
    assert "DocumentCataloging" in page.url
