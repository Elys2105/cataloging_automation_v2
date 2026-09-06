from __future__ import annotations

from pathlib import Path

import pytest

from cataloging_tool.config.paths import AppPaths
from cataloging_tool.config.settings import load_settings
from cataloging_tool.domain.errors import ProfileInUseError, WorkItemInUseError
from cataloging_tool.runtime_lock import SlotLockService


def _write_config(root: Path) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "default.yaml").write_text(
        """
application:
  name: Test
  version: 1
browser:
  base_url: https://example.test/DocumentCataloging
  channel: chrome
  headless: false
  timeout_ms: 30000
  profile_dir: slot1-profile
  profile_dir_slot2: slot2-profile
pdf:
  render_dpi: 300
  max_pages_for_header: 1
  minimum_text_length: 80
ocr:
  enabled: true
  language: vi
  minimum_confidence: 0.82
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


def test_slot1_preserves_legacy_runtime_and_slot2_is_isolated(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    slot1 = AppPaths.from_root(tmp_path, 1)
    slot2 = AppPaths.from_root(tmp_path, 2)

    assert slot1.runtime == tmp_path / "runtime"
    assert slot2.runtime == tmp_path / "runtime" / "slot2"
    assert slot1.database != slot2.database
    assert slot1.downloads != slot2.downloads
    assert slot1.pdf_cache != slot2.pdf_cache
    assert slot1.rendered != slot2.rendered
    assert slot1.ocr != slot2.ocr
    assert slot1.artifacts != slot2.artifacts
    assert slot1.logs != slot2.logs
    assert slot1.lock_root == slot2.lock_root == tmp_path / "local" / "KhoLuuTruAutomation" / "locks"


def test_slot_settings_select_distinct_browser_profiles(tmp_path: Path, monkeypatch) -> None:
    _write_config(tmp_path)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))

    slot1 = load_settings(tmp_path, slot_id=1)
    slot2 = load_settings(tmp_path, slot_id=2)

    assert slot1.slot_id == 1
    assert slot2.slot_id == 2
    assert slot1.browser.profile_dir == tmp_path / "slot1-profile"
    assert slot2.browser.profile_dir == tmp_path / "slot2-profile"
    assert slot1.browser.profile_dir != slot2.browser.profile_dir
    assert slot1.paths.database != slot2.paths.database


def test_environment_selects_slot2(tmp_path: Path, monkeypatch) -> None:
    _write_config(tmp_path)
    monkeypatch.setenv("CATALOGING_SLOT", "2")
    settings = load_settings(tmp_path)
    assert settings.slot_id == 2
    assert settings.paths.runtime == tmp_path / "runtime" / "slot2"


def test_invalid_slot_is_rejected(tmp_path: Path) -> None:
    _write_config(tmp_path)
    with pytest.raises(ValueError, match="1 hoặc 2"):
        load_settings(tmp_path, slot_id=3)


def test_browser_profile_lock_reports_owner_slot(tmp_path: Path) -> None:
    lock_dir = tmp_path / "locks"
    profile = tmp_path / "ChromeProfile"
    first = SlotLockService(lock_dir, 1)
    second = SlotLockService(lock_dir, 2)

    held = first.acquire_browser_profile(profile)
    try:
        with pytest.raises(ProfileInUseError, match=r"Slot 1"):
            second.acquire_browser_profile(profile)
    finally:
        held.release()

    # Lock must be released after the first process exits/stops.
    second_held = second.acquire_browser_profile(profile)
    second_held.release()


def test_same_profile_query_cannot_run_in_two_slots(tmp_path: Path) -> None:
    lock_dir = tmp_path / "locks"
    first = SlotLockService(lock_dir, 1)
    second = SlotLockService(lock_dir, 2)

    held = first.acquire_job("HS 2025 / 001")
    try:
        with pytest.raises(WorkItemInUseError, match=r"Hồ sơ đang được xử lý ở Slot 1"):
            second.acquire_job("  hs 2025/001  ")
    finally:
        held.release()


def test_different_profile_queries_can_run_in_parallel(tmp_path: Path) -> None:
    lock_dir = tmp_path / "locks"
    first = SlotLockService(lock_dir, 1)
    second = SlotLockService(lock_dir, 2)

    one = first.acquire_job("HS-A")
    two = second.acquire_job("HS-B")
    two.release()
    one.release()


def test_owner_metadata_reader_skips_locked_byte_zero(tmp_path: Path, monkeypatch) -> None:
    lock_dir = tmp_path / "locks"
    first = SlotLockService(lock_dir, 1)
    second = SlotLockService(lock_dir, 2)

    # Regression for Windows msvcrt byte-range locking: reading the whole file
    # starts at byte 0 and can fail while that byte is locked. The owner reader
    # must instead open the file and seek past byte 0 before reading metadata.
    def forbidden_read_bytes(self: Path) -> bytes:
        raise AssertionError("owner metadata must not read locked byte zero")

    monkeypatch.setattr(Path, "read_bytes", forbidden_read_bytes)

    held = first.acquire_job("HS-WINDOWS-LOCK")
    try:
        with pytest.raises(WorkItemInUseError, match=r"Slot 1"):
            second.acquire_job("HS-WINDOWS-LOCK")
    finally:
        held.release()
