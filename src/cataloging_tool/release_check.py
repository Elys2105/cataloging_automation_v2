from __future__ import annotations

import asyncio
import importlib.util
import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

from cataloging_tool.config.settings import AppSettings


def _find_bundled_chromium() -> str | None:
    raw = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if not raw:
        return None
    root = Path(raw)
    if not root.exists():
        return None
    for candidate in sorted(root.glob("chromium-*/**/chrome.exe")):
        if candidate.is_file():
            return str(candidate.resolve())
    return None


def _find_chrome() -> str | None:
    candidates = [
        shutil.which("chrome"),
        shutil.which("chrome.exe"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(Path(candidate))
    return None


def _tesseract_languages(command: str) -> list[str]:
    if not command or not Path(command).exists():
        return []
    env = os.environ.copy()
    tessdata = Path(command).parent / "tessdata"
    if tessdata.exists():
        env["TESSDATA_PREFIX"] = str(tessdata)
    try:
        process = subprocess.run(
            [command, "--list-langs"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    except Exception:
        return []
    if process.returncode != 0:
        return []
    lines = [line.strip() for line in process.stdout.splitlines() if line.strip()]
    return [line for line in lines if not line.casefold().startswith("list of available")]


def run_self_check(settings: AppSettings) -> dict[str, Any]:
    required_modules = ("yaml", "fitz", "PIL", "playwright", "PySide6", "paddle", "paddleocr", "cv2")
    modules = {name: importlib.util.find_spec(name) is not None for name in required_modules}

    rules_ok = all(
        (settings.paths.root / "rules" / name).exists()
        for name in ("document_types.yaml", "vietnamese_normalization.tsv", "known_overrides.yaml")
    )
    bundled_browser = _find_bundled_chromium()
    chrome = _find_chrome()
    browser = bundled_browser or chrome
    tesseract = settings.ocr.tesseract_cmd
    languages = _tesseract_languages(tesseract)
    models = {
        "detection": str(settings.ocr.text_detection_model_dir or ""),
        "recognition": str(settings.ocr.text_recognition_model_dir or ""),
    }
    bundled_models_ok = all(bool(value) and Path(value).exists() for value in models.values())

    write_ok = True
    try:
        settings.paths.ensure()
    except Exception:
        write_ok = False

    blockers: list[str] = []
    if not all(modules.values()):
        blockers.append("Thiếu module runtime: " + ", ".join(name for name, ok in modules.items() if not ok))
    if not rules_ok:
        blockers.append("Thiếu rules/config resource.")
    if not browser:
        blockers.append("Không tìm thấy Chromium đóng gói hoặc Google Chrome hệ thống.")
    if not Path(tesseract).exists():
        blockers.append("Không tìm thấy Tesseract.")
    elif not {"vie", "eng"}.issubset(set(languages)):
        blockers.append("Tesseract thiếu traineddata vie/eng.")
    if settings.paths.installed and not bundled_models_ok:
        blockers.append("Bản cài thiếu PaddleOCR model đóng gói.")
    if not write_ok:
        blockers.append("Không ghi được runtime trong thư mục dữ liệu người dùng.")

    return {
        "ok": not blockers,
        "slot": settings.slot_id,
        "version": settings.version,
        "installed_mode": settings.paths.installed,
        "resource_root": str(settings.paths.root),
        "data_root": str(settings.paths.data_root),
        "runtime": str(settings.paths.runtime),
        "browser_profile": str(settings.browser.profile_dir),
        "browser": browser or "",
        "bundled_browser": bundled_browser or "",
        "chrome": chrome or "",
        "tesseract": tesseract,
        "tesseract_languages": languages,
        "models": models,
        "modules": modules,
        "rules_ok": rules_ok,
        "write_ok": write_ok,
        "blockers": blockers,
    }

def run_browser_smoke(settings: AppSettings) -> dict[str, Any]:
    """Launch the packaged browser against a disposable writable profile.

    Self-check only proves that files exist. This smoke test proves Chromium can
    actually create a persistent context under the customer data root, which
    catches profile/cache/permission regressions before a Setup is released.
    """

    from cataloging_tool.automation.browser import BrowserSession

    smoke_root = settings.paths.runtime / "browser-smoke"
    profile = smoke_root / "profile"
    downloads = smoke_root / "downloads"
    traces = smoke_root / "traces"
    shutil.rmtree(smoke_root, ignore_errors=True)

    async def _run() -> dict[str, Any]:
        smoke_browser = replace(
            settings.browser,
            headless=True,
            profile_dir=profile,
            manual_login_timeout_ms=0,
        )
        session = BrowserSession(
            settings=smoke_browser,
            profile_dir=profile,
            downloads_dir=downloads,
            trace_dir=traces,
            slot_locks=None,
        )
        try:
            page = await session.start()
            await page.goto("about:blank")
            return {
                "ok": True,
                "slot": settings.slot_id,
                "version": settings.version,
                "profile": str(profile),
                "url": str(page.url),
                "error": "",
            }
        except Exception as exc:
            return {
                "ok": False,
                "slot": settings.slot_id,
                "version": settings.version,
                "profile": str(profile),
                "url": "",
                "error": f"{type(exc).__name__}: {exc}",
            }
        finally:
            try:
                await session.stop(save_trace=False)
            finally:
                shutil.rmtree(smoke_root, ignore_errors=True)

    return asyncio.run(_run())

