from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .deployment import app_data_root, is_installed_mode, local_appdata_root


@dataclass(frozen=True, slots=True)
class AppPaths:
    root: Path
    slot_id: int
    installed: bool
    data_root: Path
    config_dir: Path
    user_config: Path
    resources: Path
    models: Path
    tesseract_dir: Path
    tesseract_exe: Path
    runtime: Path
    database: Path
    browser_profile: Path
    downloads: Path
    pdf_cache: Path
    rendered: Path
    ocr: Path
    artifacts: Path
    logs: Path
    lock_root: Path

    @classmethod
    def from_root(
        cls,
        root: Path,
        slot_id: int = 1,
        *,
        installed: bool | None = None,
    ) -> "AppPaths":
        if slot_id not in {1, 2}:
            raise ValueError(f"Slot không hợp lệ: {slot_id}")

        root = root.resolve()
        installed_mode = is_installed_mode() if installed is None else installed
        resources = root / "resources"

        if installed_mode:
            data_root = app_data_root()
            slot_root = data_root / f"slot{slot_id}"
            runtime = slot_root / "runtime"
            config_dir = data_root / "config"
            lock_root = data_root / "locks"

            # Customer/installed releases use a dedicated profile per slot.
            # Do not launch bundled Chromium against the legacy system-Chrome
            # profile: cross-browser/profile-version reuse can trigger Chromium
            # downgrade/cache migration failures (Access denied / exitCode=33).
            browser_profile = slot_root / "profile"
        else:
            data_root = root
            config_dir = root / "config"
            # Preserve current development behavior and current jobs/cache.
            runtime = root / "runtime" if slot_id == 1 else root / "runtime" / "slot2"
            local = local_appdata_root()
            lock_root = (
                local / "KhoLuuTruAutomation" / "locks"
                if str(local)
                else root / "runtime" / "machine-locks"
            )
            browser_profile = runtime / "browser-profile"

        return cls(
            root=root,
            slot_id=slot_id,
            installed=installed_mode,
            data_root=data_root,
            config_dir=config_dir,
            user_config=config_dir / "local.yaml",
            resources=resources,
            models=resources / "models",
            tesseract_dir=resources / "tesseract",
            tesseract_exe=resources / "tesseract" / "tesseract.exe",
            runtime=runtime,
            database=runtime / "database" / "cataloging.sqlite3",
            browser_profile=browser_profile,
            downloads=runtime / "downloads",
            pdf_cache=runtime / "pdf",
            rendered=runtime / "rendered",
            ocr=runtime / "ocr",
            artifacts=runtime / "artifacts",
            logs=runtime / "logs",
            lock_root=lock_root,
        )

    def ensure(self) -> None:
        directories = (
            self.data_root if self.installed else self.runtime,
            self.config_dir,
            self.runtime,
            self.database.parent,
            self.browser_profile,
            self.downloads,
            self.pdf_cache,
            self.rendered,
            self.ocr,
            self.artifacts,
            self.logs,
            self.lock_root,
        )
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
            probe = directory / ".write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
