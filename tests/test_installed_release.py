from __future__ import annotations

import os
from pathlib import Path

import yaml

from cataloging_tool.config.paths import AppPaths
from cataloging_tool.config.settings import load_settings
from cataloging_tool.main import main


def _write_minimal_config(root: Path) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "rules").mkdir(parents=True, exist_ok=True)
    (root / "resources" / "models" / "PP-OCRv5_mobile_det").mkdir(parents=True, exist_ok=True)
    (root / "resources" / "models" / "latin_PP-OCRv5_mobile_rec").mkdir(parents=True, exist_ok=True)
    tess = root / "resources" / "tesseract"
    (tess / "tessdata").mkdir(parents=True, exist_ok=True)
    (tess / "tesseract.exe").write_bytes(b"stub")
    for name in ("document_types.yaml", "known_overrides.yaml"):
        (root / "rules" / name).write_text("[]\n", encoding="utf-8")
    (root / "rules" / "vietnamese_normalization.tsv").write_text("", encoding="utf-8")
    (root / "config" / "default.yaml").write_text(
        """
application:
  name: Test App
  version: 1.2.3
browser:
  base_url: https://example.test/DocumentCataloging
  channel: chrome
  headless: false
  timeout_ms: 30000
  profile_dir: "%LOCALAPPDATA%/KhoLuuTruAutomationChromeProfile"
  profile_dir_slot2: "%LOCALAPPDATA%/KhoLuuTruAutomationChromeProfile_Slot2"
pdf:
  render_dpi: 300
  max_pages_for_header: 1
  minimum_text_length: 80
ocr:
  enabled: true
  language: vi
  minimum_confidence: 0.82
  device: cpu
  text_detection_model_name: PP-OCRv5_mobile_det
  text_recognition_model_name: latin_PP-OCRv5_mobile_rec
  use_tesseract_fallback: true
workflow:
  max_attempts: 1
  continue_after_record_error: true
  auto_complete: false
  dry_run: true
cataloging_defaults:
  author: ""
  security_level: Thường
""".strip(),
        encoding="utf-8",
    )


def test_installed_paths_are_under_localappdata_and_slot_isolated(tmp_path: Path, monkeypatch) -> None:
    local = tmp_path / "local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    one = AppPaths.from_root(tmp_path / "resources-root", 1, installed=True)
    two = AppPaths.from_root(tmp_path / "resources-root", 2, installed=True)

    base = local / "KhoLuuTruAutomation"
    assert one.runtime == base / "slot1" / "runtime"
    assert two.runtime == base / "slot2" / "runtime"
    assert one.database != two.database
    assert one.lock_root == two.lock_root == base / "locks"
    assert one.user_config == base / "config" / "local.yaml"


def test_installed_mode_does_not_reuse_legacy_chrome_profile(tmp_path: Path, monkeypatch) -> None:
    local = tmp_path / "local"
    legacy = local / "KhoLuuTruAutomationChromeProfile"
    legacy.mkdir(parents=True)
    monkeypatch.setenv("LOCALAPPDATA", str(local))

    paths = AppPaths.from_root(tmp_path / "root", 1, installed=True)
    assert paths.browser_profile == local / "KhoLuuTruAutomation" / "slot1" / "profile"
    assert paths.browser_profile != legacy


def test_fresh_installed_mode_uses_nested_profile(tmp_path: Path, monkeypatch) -> None:
    local = tmp_path / "local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    paths = AppPaths.from_root(tmp_path / "root", 2, installed=True)
    assert paths.browser_profile == local / "KhoLuuTruAutomation" / "slot2" / "profile"


def test_installed_settings_use_user_config_and_bundled_resources(tmp_path: Path, monkeypatch) -> None:
    _write_minimal_config(tmp_path)
    local = tmp_path / "local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("CATALOGING_INSTALLED_MODE", "1")

    config_dir = local / "KhoLuuTruAutomation" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "local.yaml").write_text("workflow:\n  dry_run: false\n", encoding="utf-8")

    settings = load_settings(tmp_path, slot_id=1)

    assert settings.paths.installed
    assert settings.paths.user_config == config_dir / "local.yaml"
    assert settings.ocr.tesseract_cmd == str(tmp_path / "resources" / "tesseract" / "tesseract.exe")
    assert settings.ocr.text_detection_model_dir == tmp_path / "resources" / "models" / "PP-OCRv5_mobile_det"
    assert settings.ocr.text_recognition_model_dir == tmp_path / "resources" / "models" / "latin_PP-OCRv5_mobile_rec"
    assert settings.ocr.tessdata_dir == tmp_path / "resources" / "tesseract" / "tessdata"



def test_fresh_installed_settings_do_not_require_local_yaml(tmp_path: Path, monkeypatch) -> None:
    _write_minimal_config(tmp_path)
    local = tmp_path / "local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("CATALOGING_INSTALLED_MODE", "1")

    settings = load_settings(tmp_path, slot_id=2)

    assert settings.paths.installed
    assert not settings.paths.user_config.exists()
    assert settings.paths.runtime == local / "KhoLuuTruAutomation" / "slot2" / "runtime"
    assert settings.browser.profile_dir == local / "KhoLuuTruAutomation" / "slot2" / "profile"

def test_installer_defines_two_slot_shortcuts_and_does_not_delete_user_data() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "installer" / "AutomationBienMuc.iss").read_text(encoding="utf-8")
    assert 'Parameters: "--slot 1"' in source
    assert 'Parameters: "--slot 2"' in source
    assert "KhoLuuTruAutomation" not in source
    assert "[UninstallDelete]" not in source


def test_spec_bundles_config_rules_pyproject_and_release_resources() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "build" / "CatalogingAutomation.spec").read_text(encoding="utf-8")
    assert 'pyproject.toml' in source
    assert 'config" / "default.yaml' in source
    assert 'rules" / "document_types.yaml' in source
    assert "release_resources" in source
    assert "runtime_hook.py" in source


def test_build_script_runs_packaged_self_check_and_creates_installer() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "scripts" / "build_windows.ps1").read_text(encoding="utf-8")
    assert "--self-check" in source
    assert '"--slot", "$slot"' in source
    assert "AutomationBienMuc-Portable-" in source
    assert "AutomationBienMuc-Setup-" in source
    assert "stage_release_resources.py" in source
