from __future__ import annotations

import importlib.util
import json
import platform
import shutil
import sqlite3
from contextlib import closing
import sys
from pathlib import Path


def available(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    runtime = root / "runtime"
    runtime.mkdir(exist_ok=True)
    db = runtime / "environment-check.sqlite3"
    with closing(sqlite3.connect(db)) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS probe (value TEXT NOT NULL)")
        connection.execute("DELETE FROM probe")
        connection.execute("INSERT INTO probe(value) VALUES ('ok')")
        connection.commit()
        value = connection.execute("SELECT value FROM probe").fetchone()[0]
    db.unlink(missing_ok=True)

    report = {
        "python": sys.version,
        "python_supported": (3, 11) <= sys.version_info[:2] < (3, 14),
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "disk_free_gb": round(shutil.disk_usage(root).free / 1024**3, 2),
        "sqlite": sqlite3.sqlite_version,
        "sqlite_write_ok": value == "ok",
        "modules": {
            "yaml": available("yaml"),
            "fitz": available("fitz"),
            "PIL": available("PIL"),
            "playwright": available("playwright"),
            "PySide6": available("PySide6"),
            "paddle": available("paddle"),
            "paddleocr": available("paddleocr"),
            "cv2": available("cv2"),
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    required_core = report["python_supported"] and report["sqlite_write_ok"]
    return 0 if required_core else 1


if __name__ == "__main__":
    raise SystemExit(main())
