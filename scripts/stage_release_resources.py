from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


def _find_tesseract(configured: str) -> Path | None:
    candidates = [
        os.environ.get("TESSERACT_CMD", ""),
        configured,
        shutil.which("tesseract") or "",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for raw in candidates:
        if raw and Path(os.path.expandvars(raw)).exists():
            return Path(os.path.expandvars(raw)).resolve()
    return None


def _copy_tesseract(source_exe: Path, destination: Path) -> None:
    source_dir = source_exe.parent
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    # Copy runtime binaries/configs, but only the OCR languages required by
    # this application. This avoids bundling unrelated traineddata.
    for child in source_dir.iterdir():
        target = destination / child.name
        if child.is_dir():
            if child.name.casefold() == "tessdata":
                target.mkdir(parents=True, exist_ok=True)
                for name in ("vie.traineddata", "eng.traineddata", "osd.traineddata"):
                    src = child / name
                    if src.exists():
                        shutil.copy2(src, target / name)
                configs = child / "configs"
                if configs.exists():
                    shutil.copytree(configs, target / "configs", dirs_exist_ok=True)
                tessconfigs = child / "tessconfigs"
                if tessconfigs.exists():
                    shutil.copytree(tessconfigs, target / "tessconfigs", dirs_exist_ok=True)
            else:
                # Tesseract distributions may include auxiliary folders used by
                # runtime DLLs/configuration; preserving them is safer than an
                # executable-only copy.
                shutil.copytree(child, target, dirs_exist_ok=True)
        else:
            shutil.copy2(child, target)

    required = [
        destination / "tesseract.exe",
        destination / "tessdata" / "vie.traineddata",
        destination / "tessdata" / "eng.traineddata",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError("Tesseract staging missing: " + ", ".join(missing))


def _model_source(model_name: str) -> Path | None:
    roots = [
        Path.home() / ".paddlex" / "official_models",
        Path.home() / ".paddleocr",
    ]
    for base in roots:
        direct = base / model_name
        if direct.exists() and direct.is_dir():
            return direct
        if base.exists():
            matches = [
                path for path in base.rglob(model_name)
                if path.is_dir() and path.name == model_name
            ]
            if matches:
                return matches[0]
    return None



def _playwright_cached_chromium() -> Path | None:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            executable = Path(playwright.chromium.executable_path)
    except Exception:
        return None
    if not executable.exists():
        return None
    for parent in executable.parents:
        if parent.name.casefold().startswith("chromium-"):
            return parent
    return None


def _stage_playwright_chromium(destination: Path) -> dict[str, str]:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    cached = _playwright_cached_chromium()
    source_kind = "download"
    if cached is not None:
        shutil.copytree(cached, destination / cached.name, dirs_exist_ok=True)
        source_kind = "cache"
        for extra in sorted(cached.parent.glob("ffmpeg-*")):
            if extra.is_dir():
                shutil.copytree(extra, destination / extra.name, dirs_exist_ok=True)
    else:
        env = os.environ.copy()
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(destination)
        process = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            cwd=str(destination.parent),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            errors="replace",
            timeout=1800,
            check=False,
        )
        if process.returncode != 0:
            raise RuntimeError(
                "Không thể tải Chromium tương thích với Playwright để đóng gói.\n"
                + process.stdout[-6000:]
            )

    executables = sorted(destination.glob("chromium-*/**/chrome.exe"))
    if not executables:
        raise RuntimeError("Không tìm thấy chrome.exe trong Chromium đã stage.")
    return {
        "source": source_kind,
        "executable": str(executables[0].resolve()),
        "root": str(destination.resolve()),
    }

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()

    root = args.root.resolve()
    config = yaml.safe_load((root / "config" / "default.yaml").read_text(encoding="utf-8")) or {}
    ocr = config["ocr"]

    stage = root / "build" / "release_resources"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    browser_report = _stage_playwright_chromium(stage / "playwright-browsers")

    command = _find_tesseract(str(ocr.get("tesseract_cmd", "")))
    if command is None:
        raise RuntimeError("Không tìm thấy Tesseract để đóng gói.")
    _copy_tesseract(command, stage / "tesseract")

    model_names = [
        str(ocr["text_detection_model_name"]),
        str(ocr["text_recognition_model_name"]),
    ]
    model_report: dict[str, str] = {}
    models_dir = stage / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    for model_name in model_names:
        source = _model_source(model_name)
        if source is None:
            raise RuntimeError(
                f"Không tìm thấy Paddle model đã cache: {model_name}. "
                "Hãy chạy OCR smoke một lần trên môi trường build trước khi đóng gói."
            )
        shutil.copytree(source, models_dir / model_name, dirs_exist_ok=True)
        model_report[model_name] = str(source)

    report = {
        "stage": str(stage),
        "browser": browser_report,
        "tesseract_source": str(command.parent),
        "models": model_report,
    }
    (stage / "STAGING_MANIFEST.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
