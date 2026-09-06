from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cataloging_tool.config.settings import BrowserSettings
from cataloging_tool.domain.errors import AuthenticationExpiredError, BrowserNavigationError
from cataloging_tool.runtime_lock import HeldFileLock, SlotLockService

from .pdf_detector import PdfResponseCollector

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page, Playwright

logger = logging.getLogger(__name__)


class BrowserSession:
    def __init__(
        self,
        settings: BrowserSettings,
        profile_dir: Path,
        downloads_dir: Path,
        trace_dir: Path,
        slot_locks: SlotLockService | None = None,
    ) -> None:
        self.settings = settings
        self.profile_dir = profile_dir
        self.downloads_dir = downloads_dir
        self.trace_dir = trace_dir
        self.slot_locks = slot_locks
        self._profile_lock: HeldFileLock | None = None
        self._playwright: Playwright | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.pdf_collector = PdfResponseCollector()

    async def start(self) -> Any:
        if self.page is not None:
            return self.page
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise BrowserNavigationError(
                "Chưa cài Playwright. Cài extra browser và chạy playwright install chromium.",
                step="browser_initialize",
            ) from exc

        if self.slot_locks is not None:
            self._profile_lock = self.slot_locks.acquire_browser_profile(self.profile_dir)

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        self.trace_dir.mkdir(parents=True, exist_ok=True)

        logger.info("Khởi động Chrome với persistent profile: %s", self.profile_dir)
        try:
            playwright = await async_playwright().start()
            self._playwright = playwright
            channel = self.settings.channel or None
            bundled_browsers = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
            if bundled_browsers and Path(bundled_browsers).exists():
                # Final customer builds ship a compatible Chromium runtime.
                # Prefer it even when an old local.yaml still says channel=chrome.
                channel = None
                logger.info("Dùng Chromium đóng gói: %s", bundled_browsers)

            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                channel=channel,
                headless=self.settings.headless,
                accept_downloads=False,
                viewport=None,
                args=["--start-maximized", "--disable-notifications"],
            )
            self.context = context
            context.set_default_timeout(self.settings.timeout_ms)
            context.set_default_navigation_timeout(self.settings.timeout_ms)
            await context.tracing.start(screenshots=True, snapshots=True, sources=True)
            page = context.pages[0] if context.pages else await context.new_page()
            self.page = page

            # Hàng rào cuối: nếu selector tương lai vô tình click input[type=file],
            # Playwright giữ file chooser trong tiến trình và không mở File Explorer.
            page.on(
                "filechooser",
                lambda _chooser: logger.error(
                    "Đã chặn file chooser ngoài ý muốn; automation không cần chọn file."
                ),
            )
            self.pdf_collector.attach(page)
            return page
        except Exception:
            await self.stop(save_trace=False)
            raise

    async def open_base_page(self) -> Any:
        page = await self.start()
        try:
            await page.goto(self.settings.base_url, wait_until="domcontentloaded")
            try:
                await self._assert_authenticated(page)
            except AuthenticationExpiredError:
                if self.settings.headless or self.settings.manual_login_timeout_ms <= 0:
                    raise

                await self._wait_for_interactive_login(page)
                # Login flows often redirect to a dashboard. Re-open the actual
                # cataloging URL after authentication before returning to workflow.
                await page.goto(self.settings.base_url, wait_until="domcontentloaded")
                await self._assert_authenticated(page)
            return page
        except AuthenticationExpiredError:
            raise
        except Exception as exc:
            raise BrowserNavigationError(
                f"Không mở được trang biên mục: {exc}",
                step="open_base_page",
                retryable=True,
            ) from exc

    async def _wait_for_interactive_login(self, page: Any) -> None:
        """Keep the bundled browser open so a first-time user can log in manually.

        Credentials are never read by the automation. The user signs in directly
        on the website; the persistent per-slot profile then keeps that session for
        later runs.
        """

        import asyncio

        timeout_ms = max(0, int(self.settings.manual_login_timeout_ms))
        deadline = asyncio.get_running_loop().time() + (timeout_ms / 1000.0)
        logger.warning(
            "Chưa có phiên đăng nhập. Hãy đăng nhập trong cửa sổ Chromium của tool; "
            "automation sẽ tự tiếp tục sau khi đăng nhập thành công. Profile: %s",
            self.profile_dir,
        )

        while asyncio.get_running_loop().time() < deadline:
            try:
                await self._assert_authenticated(page)
                logger.info("Đăng nhập thủ công đã hoàn tất: %s", page.url)
                return
            except AuthenticationExpiredError:
                await page.wait_for_timeout(1000)

        raise AuthenticationExpiredError(
            "Hết thời gian chờ đăng nhập. Hãy mở lại tool và đăng nhập trong cửa sổ "
            f"Chromium của Slot này. Profile: {self.profile_dir}",
            step="authentication_wait",
            retryable=False,
        )

    async def _assert_authenticated(self, page: Any) -> None:
        """Reject only when there is strong evidence that the page is a login page.

        Some authenticated pages keep a hidden password input or login modal in the DOM.
        Counting every password input therefore causes false "session expired" errors.
        """

        url = str(page.url).casefold()
        login_url_markers = (
            "/login",
            "signin",
            "account/login",
            "dang-nhap",
            "đăng-nhập",
        )
        visible_password_count = await page.locator("input[type='password']:visible").count()

        if any(marker in url for marker in login_url_markers) or visible_password_count > 0:
            raise AuthenticationExpiredError(
                f"Profile trình duyệt của tool chưa có phiên đăng nhập hợp lệ: "
                f"{self.profile_dir}.",
                step="authentication_check",
                retryable=False,
            )

        logger.info("Đã xác nhận không có dấu hiệu trang đăng nhập: %s", page.url)

    async def save_trace(self, filename: str) -> Path | None:
        if self.context is None:
            return None
        path = self.trace_dir / filename
        await self.context.tracing.stop(path=str(path))
        return path

    async def stop(self, *, save_trace: bool = True) -> None:
        if self.context is not None:
            try:
                if save_trace:
                    await self.context.tracing.stop(path=str(self.trace_dir / "last-session-trace.zip"))
            except Exception as exc:
                logger.debug("Không lưu được trace khi đóng browser: %s", exc)
            await self.context.close()
            self.context = None
            self.page = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
        if self._profile_lock is not None:
            self._profile_lock.release()
            self._profile_lock = None
