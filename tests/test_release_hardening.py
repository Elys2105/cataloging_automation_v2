from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace(".", "_"), path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_project_and_default_config_versions_are_synchronized() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    default = yaml.safe_load((ROOT / "config" / "default.yaml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == default["application"]["version"]


def test_build_script_does_not_hardcode_legacy_release_version() -> None:
    source = (ROOT / "scripts" / "build_windows.ps1").read_text(encoding="utf-8")
    assert "CatalogingAutomation-0.1.0-windows-x64" not in source
    assert "read_project_version.py" in source


def test_static_tool_config_excludes_generated_runtime_trees() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    ruff_excludes = set(data["tool"]["ruff"]["extend-exclude"])
    pyright_excludes = set(data["tool"]["pyright"]["exclude"])
    for required in {"runtime", "backup", "backups", "build", "dist", "release"}:
        assert required in ruff_excludes
        assert required in pyright_excludes


def test_dependency_checker_detects_multiple_opencv_distributions(monkeypatch) -> None:
    module = _load_script("check_dependency_conflicts.py")
    versions = {
        "paddleocr": "3.3.2",
        "paddlex": "3.3.13",
        "paddlepaddle": "3.2.2",
        "PyYAML": "6.0",
        "PyMuPDF": "1.26",
        "Pillow": "11.0",
        "playwright": "1.61.0",
        "PySide6": "6.9.0",
        "ruff": "0.12.0",
        "pyright": "1.1.400",
        "pyinstaller": "6.14.0",
        "opencv-python-headless": "4.13.0.92",
        "opencv-contrib-python": "4.10.0.84",
    }
    monkeypatch.setattr(module, "_version", lambda name: versions.get(name))
    monkeypatch.setattr(module, "_find_chrome", lambda: "chrome.exe")
    monkeypatch.setattr(module, "_find_tesseract", lambda: "tesseract.exe")
    monkeypatch.setattr(module, "_tesseract_languages", lambda command: ["eng", "vie"])
    result = module.collect()
    assert not result["ok"]
    assert any("Multiple OpenCV distributions" in item for item in result["blockers"])


def test_benchmark_script_never_emits_document_text_fields() -> None:
    source = (ROOT / "scripts" / "benchmark_pipeline.py").read_text(encoding="utf-8")
    assert '"raw_text"' not in source
    assert '"abstract"' not in source
    assert "No OCR text" in source


def test_project_uses_single_paddlex_compatible_opencv_distribution() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    ocr = set(data["project"]["optional-dependencies"]["ocr"])
    full = set(data["project"]["optional-dependencies"]["full"])
    expected = "opencv-contrib-python==4.10.0.84"
    assert expected in ocr
    assert expected in full
    assert not any(item.startswith("opencv-python-headless") for item in ocr | full)


def test_dependency_checker_accepts_single_expected_opencv(monkeypatch) -> None:
    module = _load_script("check_dependency_conflicts.py")
    versions = {
        "paddleocr": "3.3.2",
        "paddlex": "3.3.13",
        "paddlepaddle": "3.2.2",
        "PyYAML": "6.0.2",
        "PyMuPDF": "1.28.0",
        "Pillow": "12.3.0",
        "playwright": "1.61.0",
        "PySide6": "6.11.1",
        "ruff": "0.15.21",
        "pyright": "1.1.411",
        "pyinstaller": "6.21.0",
        "opencv-contrib-python": "4.10.0.84",
    }
    monkeypatch.setattr(module, "_version", lambda name: versions.get(name))
    monkeypatch.setattr(module, "_find_chrome", lambda: "chrome.exe")
    monkeypatch.setattr(module, "_find_tesseract", lambda: "tesseract.exe")
    monkeypatch.setattr(module, "_tesseract_languages", lambda command: ["eng", "vie"])
    monkeypatch.setattr(Path, "exists", lambda self: True)
    result = module.collect()
    assert result["ok"], result
    assert result["opencv_distributions"] == {"opencv-contrib-python": "4.10.0.84"}


def test_release_hardening_writes_expected_pyright_report_and_keeps_static_advisory() -> None:
    source = (ROOT / "scripts" / "release_hardening.ps1").read_text(encoding="utf-8")
    assert 'Run-Native "09_pyright_full"' in source
    assert 'if ($depCode -ne 0)' in source
    assert 'RELEASE_HARDENING_PASS_WITH_STATIC_ADVISORIES' in source
