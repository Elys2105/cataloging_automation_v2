from __future__ import annotations

from pathlib import Path

from cataloging_tool.config.paths import AppPaths
from cataloging_tool.config.settings import load_settings


def _write_config(root: Path) -> None:
    (root / "config").mkdir(parents=True)
    (root / "rules").mkdir(parents=True)
    (root / "resources" / "models" / "PP-OCRv5_mobile_det").mkdir(parents=True)
    (root / "resources" / "models" / "latin_PP-OCRv5_mobile_rec").mkdir(parents=True)
    tess = root / "resources" / "tesseract"
    (tess / "tessdata").mkdir(parents=True)
    (tess / "tesseract.exe").write_bytes(b"stub")
    for name in ("document_types.yaml", "known_overrides.yaml"):
        (root / "rules" / name).write_text("[]\n", encoding="utf-8")
    (root / "rules" / "vietnamese_normalization.tsv").write_text("", encoding="utf-8")
    (root / "config" / "default.yaml").write_text(
        """
application:
  name: Test
  version: 0.1.27.4.18
browser:
  base_url: https://example.test/DocumentCataloging
  channel: ""
  headless: false
  timeout_ms: 30000
  manual_login_timeout_ms: 600000
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


def test_installed_slot_profiles_are_dedicated_even_when_legacy_exists(tmp_path: Path, monkeypatch) -> None:
    local = tmp_path / "local"
    (local / "KhoLuuTruAutomationChromeProfile").mkdir(parents=True)
    (local / "KhoLuuTruAutomationChromeProfile_Slot2").mkdir(parents=True)
    monkeypatch.setenv("LOCALAPPDATA", str(local))

    one = AppPaths.from_root(tmp_path / "root", 1, installed=True)
    two = AppPaths.from_root(tmp_path / "root", 2, installed=True)

    assert one.browser_profile == local / "KhoLuuTruAutomation" / "slot1" / "profile"
    assert two.browser_profile == local / "KhoLuuTruAutomation" / "slot2" / "profile"


def test_installed_local_yaml_legacy_profile_is_migrated_to_slot_profile(tmp_path: Path, monkeypatch) -> None:
    _write_config(tmp_path)
    local = tmp_path / "local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("CATALOGING_INSTALLED_MODE", "1")

    config = local / "KhoLuuTruAutomation" / "config"
    config.mkdir(parents=True)
    legacy = local / "KhoLuuTruAutomationChromeProfile"
    # Use YAML serialization instead of double-quoting a raw Windows path.
    # Backslashes such as ``\U`` are escape initiators inside YAML double-quoted
    # scalars, so a literal ``C:\Users\...`` fixture is invalid YAML.
    import yaml

    (config / "local.yaml").write_text(
        yaml.safe_dump(
            {"browser": {"profile_dir": str(legacy)}},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    settings = load_settings(tmp_path, slot_id=1)
    assert settings.browser.profile_dir == local / "KhoLuuTruAutomation" / "slot1" / "profile"
    assert settings.browser.manual_login_timeout_ms == 600000


def test_final_acceptance_requires_real_browser_launch() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "scripts" / "final_customer_acceptance_0127418.ps1").read_text(encoding="utf-8-sig")
    assert "--browser-smoke" in source
    assert "BROWSER_SMOKE_SLOT1=True" in source
    assert "BROWSER_SMOKE_SLOT2=True" in source
