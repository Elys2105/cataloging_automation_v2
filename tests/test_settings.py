from __future__ import annotations

from pathlib import Path

from cataloging_tool.config.settings import load_settings


def test_browser_profile_dir_can_be_overridden(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "default.yaml").write_text(
        """
application:
  name: Test
  version: 1
browser:
  base_url: https://example.test/DocumentCataloging
  channel: chrome
  headless: false
  timeout_ms: 30000
  profile_dir: runtime/browser-profile
pdf:
  render_dpi: 300
  max_pages_for_header: 1
  minimum_text_length: 80
ocr:
  enabled: true
  language: vi
  minimum_confidence: 0.82
  use_doc_orientation_classify: true
  use_doc_unwarping: false
  use_textline_orientation: true
workflow:
  max_attempts: 1
  continue_after_record_error: true
  auto_complete: false
  dry_run: true
cataloging_defaults:
  author: Test
  security_level: Thường
""".strip(),
        encoding="utf-8",
    )
    custom = tmp_path / "legacy-profile"
    monkeypatch.setenv("CATALOGING_TEST_PROFILE", str(custom))
    (tmp_path / "config" / "local.yaml").write_text(
        'browser:\n  profile_dir: "$CATALOGING_TEST_PROFILE"\n',
        encoding="utf-8",
    )

    settings = load_settings(tmp_path)

    assert settings.browser.profile_dir == custom
