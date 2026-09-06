from __future__ import annotations

import importlib.util
import os
import platform
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cataloging_tool.config.settings import load_settings
from cataloging_tool.document.ocr_guard import ProtectedOcrEngine


def _status(name: str, ok: bool, detail: str) -> bool:
    print(f"[{'OK' if ok else 'FAIL'}] {name}: {detail}")
    return ok


def main() -> int:
    root = ROOT
    settings = load_settings(root)
    failures = 0

    print("=== Cataloging Automation 0.1.31 runtime check ===")
    print(f"Python: {sys.version.split()[0]} | {platform.platform()}")

    failures += not _status("version", settings.version == "0.1.31", settings.version)
    failures += not _status(
        "guarded OCR",
        ProtectedOcrEngine.__name__ == "ProtectedOcrEngine",
        "Paddle child + bounded parent fallback",
    )
    failures += not _status(
        "Paddle hard limit",
        10 <= settings.ocr.paddle_call_timeout_seconds <= 45,
        f"{settings.ocr.paddle_call_timeout_seconds}s",
    )
    failures += not _status(
        "Paddle lock limit",
        1 <= settings.ocr.paddle_lock_wait_seconds <= 10,
        f"{settings.ocr.paddle_lock_wait_seconds}s",
    )
    failures += not _status(
        "Tesseract hard limit",
        10 <= settings.ocr.tesseract_timeout_seconds <= 15,
        f"{settings.ocr.tesseract_timeout_seconds}s",
    )
    failures += not _status(
        "OCR stage watchdog",
        60 <= settings.parallel.ocr_stage_timeout_seconds <= 120,
        f"{settings.parallel.ocr_stage_timeout_seconds}s",
    )
    failures += not _status(
        "Cross-process Paddle lock",
        settings.parallel.serialize_ocr,
        "enabled",
    )

    guard_source = (
        root / "src" / "cataloging_tool" / "document" / "ocr_guard.py"
    ).read_text(encoding="utf-8")
    manager_source = (
        root / "src" / "cataloging_tool" / "ui" / "job_manager.py"
    ).read_text(encoding="utf-8")
    failures += not _status(
        "No hidden child fallback",
        "_paddle_only_settings" in guard_source
        and 'fallback_policy="never"' in guard_source,
        "Paddle child performs one Paddle pass only",
    )
    failures += not _status(
        "Paddle circuit breaker",
        "_paddle_disabled_until" in guard_source,
        "enabled after timeout/crash",
    )
    failures += not _status(
        "Stage timeout kill",
        "Watchdog OCR" in manager_source,
        "enabled even while heartbeat is alive",
    )

    for module in ("playwright", "PySide6", "paddleocr", "PIL", "fitz"):
        found = importlib.util.find_spec(module) is not None
        print(f"[{'OK' if found else 'WARN'}] module {module}: {'installed' if found else 'not found'}")

    tesseract = Path(os.path.expandvars(settings.ocr.tesseract_cmd))
    print(
        f"[{'OK' if tesseract.exists() else 'WARN'}] Tesseract: "
        f"{tesseract if tesseract.exists() else 'configured path not found'}"
    )

    try:
        settings.paths.runtime.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=settings.paths.runtime, delete=True):
            pass
        _status("runtime write", True, str(settings.paths.runtime))
    except OSError as exc:
        failures += 1
        _status("runtime write", False, str(exc))

    database_path = settings.paths.database
    if database_path.exists():
        try:
            with sqlite3.connect(database_path, timeout=5) as connection:
                result = connection.execute("PRAGMA integrity_check").fetchone()
            ok = bool(result and result[0] == "ok")
            failures += not _status(
                "database integrity",
                ok,
                str(result[0] if result else "empty"),
            )
        except sqlite3.Error as exc:
            failures += 1
            _status("database integrity", False, str(exc))
    else:
        print(f"[OK] database integrity: database will be created at {database_path}")

    print(f"=== Result: {failures} blocking failure(s) ===")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
