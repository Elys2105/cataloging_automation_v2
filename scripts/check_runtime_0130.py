from __future__ import annotations

import importlib.util
import os
import platform
import sqlite3
import sys
import tempfile
from pathlib import Path

from cataloging_tool.config.settings import load_settings
from cataloging_tool.document.ocr_guard import ProtectedOcrEngine


def _status(name: str, ok: bool, detail: str) -> bool:
    label = "OK" if ok else "FAIL"
    print(f"[{label}] {name}: {detail}")
    return ok


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    failures = 0
    settings = load_settings(root)

    print("=== Cataloging Automation 0.1.30 runtime check ===")
    print(f"Python: {sys.version.split()[0]} | {platform.platform()}")

    failures += not _status(
        "version", settings.version == "0.1.30", settings.version
    )
    failures += not _status(
        "OCR guard",
        ProtectedOcrEngine.__name__ == "ProtectedOcrEngine",
        "killable Paddle child process enabled",
    )
    failures += not _status(
        "Paddle timeout",
        settings.ocr.paddle_call_timeout_seconds > 0,
        f"{settings.ocr.paddle_call_timeout_seconds}s",
    )
    failures += not _status(
        "Cross-process OCR lock",
        settings.parallel.serialize_ocr,
        f"wait {settings.ocr.paddle_lock_wait_seconds}s then fallback",
    )
    failures += not _status(
        "Worker watchdog",
        settings.parallel.worker_hang_timeout_seconds >= 60,
        f"{settings.parallel.worker_hang_timeout_seconds}s",
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
            failures += not _status("database integrity", ok, str(result[0] if result else "empty"))
        except sqlite3.Error as exc:
            failures += 1
            _status("database integrity", False, str(exc))
    else:
        print(f"[OK] database integrity: database will be created at {database_path}")

    print(f"=== Result: {failures} blocking failure(s) ===")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
