from __future__ import annotations

import os
import sys
from pathlib import Path


APP_DATA_DIRNAME = "KhoLuuTruAutomation"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"))


def is_installed_mode() -> bool:
    override = os.environ.get("CATALOGING_INSTALLED_MODE", "").strip().casefold()
    if override in {"1", "true", "yes", "on"}:
        return True
    if override in {"0", "false", "no", "off"}:
        return False
    return is_frozen()


def resource_root() -> Path:
    override = os.environ.get("CATALOGING_RESOURCE_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS")).resolve()

    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "config" / "default.yaml").exists():
            return parent
    return Path.cwd().resolve()


def local_appdata_root() -> Path:
    raw = os.environ.get("LOCALAPPDATA", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / "AppData" / "Local").resolve()


def app_data_root() -> Path:
    override = os.environ.get("CATALOGING_DATA_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return local_appdata_root() / APP_DATA_DIRNAME
