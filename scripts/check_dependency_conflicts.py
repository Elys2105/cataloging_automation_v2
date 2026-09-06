from __future__ import annotations

import argparse
import importlib.metadata as metadata
import json
import os
import platform
import shutil
import struct
import subprocess
from pathlib import Path
from typing import Any


OPENCV_DISTRIBUTIONS = (
    "opencv-python",
    "opencv-python-headless",
    "opencv-contrib-python",
    "opencv-contrib-python-headless",
)
REQUIRED_EXACT = {
    "paddleocr": "3.3.2",
    "paddlex": "3.3.13",
    "paddlepaddle": "3.2.2",
}
REQUIRED_OPENCV = {"opencv-contrib-python": "4.10.0.84"}
REQUIRED_PRESENT = (
    "PyYAML",
    "PyMuPDF",
    "Pillow",
    "playwright",
    "PySide6",
    "ruff",
    "pyright",
    "pyinstaller",
)


def _version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _find_chrome() -> str | None:
    candidates = [
        shutil.which("chrome"),
        shutil.which("chrome.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for raw in candidates:
        if not raw:
            continue
        path = Path(raw)
        if path.exists():
            return str(path)
    return None


def _find_tesseract() -> str | None:
    candidates = [
        os.environ.get("TESSERACT_CMD", ""),
        shutil.which("tesseract") or "",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for raw in candidates:
        if raw and Path(raw).exists():
            return str(Path(raw))
    return None


def _tesseract_languages(command: str | None) -> list[str]:
    if not command:
        return []
    try:
        proc = subprocess.run(
            [command, "--list-langs"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        return []
    lines = [line.strip() for line in proc.stdout.splitlines()]
    return sorted(line for line in lines if line and not line.lower().startswith("list of available"))


def collect() -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    versions: dict[str, str | None] = {}

    py_ok = (3, 11) <= tuple(__import__("sys").version_info[:2]) < (3, 14)
    if not py_ok:
        blockers.append("Python must be 3.11-3.13")
    if struct.calcsize("P") * 8 != 64:
        blockers.append("Python must be 64-bit")

    for name, expected in REQUIRED_EXACT.items():
        actual = _version(name)
        versions[name] = actual
        if actual != expected:
            blockers.append(f"{name} expected {expected}, found {actual or 'missing'}")

    for name in REQUIRED_PRESENT:
        actual = _version(name)
        versions[name] = actual
        if actual is None:
            blockers.append(f"Required package missing: {name}")

    opencv = {name: _version(name) for name in OPENCV_DISTRIBUTIONS}
    installed_opencv = {name: version for name, version in opencv.items() if version is not None}
    if len(installed_opencv) == 0:
        blockers.append("No OpenCV distribution is installed")
    elif len(installed_opencv) > 1:
        blockers.append(
            "Multiple OpenCV distributions provide cv2: "
            + ", ".join(f"{name}=={version}" for name, version in installed_opencv.items())
        )
    else:
        name, version = next(iter(installed_opencv.items()))
        expected_version = REQUIRED_OPENCV.get(name)
        if expected_version is None:
            blockers.append(
                "OpenCV distribution does not match the release baseline: "
                f"{name}=={version}; expected opencv-contrib-python==4.10.0.84"
            )
        elif version != expected_version:
            blockers.append(
                f"{name} expected {expected_version}, found {version}"
            )

    chrome = _find_chrome()
    if not chrome:
        blockers.append("Google Chrome executable not found")

    tesseract = _find_tesseract()
    languages = _tesseract_languages(tesseract)
    if not tesseract:
        blockers.append("Tesseract executable not found")
    else:
        for language in ("vie", "eng"):
            if language not in languages:
                blockers.append(f"Tesseract language missing: {language}")

    home = Path.home()
    paddle_model_roots = [home / ".paddleocr", home / ".paddlex" / "official_models"]
    model_roots = [str(path) for path in paddle_model_roots if path.exists()]
    if not model_roots:
        warnings.append("No Paddle model cache detected; clean/offline install still needs an explicit model strategy")

    return {
        "ok": not blockers,
        "python": platform.python_version(),
        "python_bits": struct.calcsize("P") * 8,
        "platform": platform.platform(),
        "versions": versions,
        "opencv_distributions": installed_opencv,
        "chrome": chrome,
        "tesseract": tesseract,
        "tesseract_languages": languages,
        "paddle_model_roots": model_roots,
        "blockers": blockers,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Windows release dependency conflicts")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args()
    result = collect()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("DEPENDENCY_HEALTH=" + ("OK" if result["ok"] else "BLOCKED"))
        for item in result["blockers"]:
            print("BLOCKER: " + item)
        for item in result["warnings"]:
            print("WARNING: " + item)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
