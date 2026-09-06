from pathlib import Path
import yaml
from cataloging_tool import release_check


def test_default_customer_release_uses_bundled_playwright_channel():
    root = Path(__file__).resolve().parents[1]
    config = yaml.safe_load((root / "config" / "default.yaml").read_text(encoding="utf-8"))
    assert config["application"]["version"] == "0.1.27.4.19"
    assert config["browser"]["channel"] == ""


def test_release_check_finds_bundled_chromium(tmp_path, monkeypatch):
    browser = tmp_path / "chromium-1234" / "chrome-win64" / "chrome.exe"
    browser.parent.mkdir(parents=True)
    browser.write_bytes(b"MZ")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    assert release_check._find_bundled_chromium() == str(browser.resolve())


def test_inno_creates_two_unconditional_desktop_shortcuts():
    root = Path(__file__).resolve().parents[1]
    text = (root / "installer" / "AutomationBienMuc.iss").read_text(encoding="utf-8-sig")
    assert "[Tasks]" not in text
    assert 'Name: "{autodesktop}\\Automation biên mục tài liệu - Slot 1"' in text
    assert 'Name: "{autodesktop}\\Automation biên mục tài liệu - Slot 2"' in text
    assert "Tasks: desktopicon" not in text


def test_runtime_hook_points_to_bundled_browser():
    root = Path(__file__).resolve().parents[1]
    text = (root / "build" / "runtime_hook.py").read_text(encoding="utf-8")
    assert "PLAYWRIGHT_BROWSERS_PATH" in text
    assert 'resource_root / "resources" / "playwright-browsers"' in text
