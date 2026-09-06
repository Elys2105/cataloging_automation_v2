from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .paths import AppPaths


@dataclass(frozen=True, slots=True)
class BrowserSettings:
    base_url: str
    channel: str
    headless: bool
    timeout_ms: int
    profile_dir: Path
    manual_login_timeout_ms: int = 600_000


@dataclass(frozen=True, slots=True)
class PdfSettings:
    render_dpi: int
    max_pages_for_header: int
    minimum_text_length: int
    fast_viewer_fallback: bool
    viewer_ready_timeout_ms: int
    direct_viewer_image: bool


@dataclass(frozen=True, slots=True)
class OcrSettings:
    enabled: bool
    language: str
    minimum_confidence: float
    device: str
    enable_mkldnn: bool
    cpu_threads: int
    text_detection_model_name: str
    text_recognition_model_name: str
    use_doc_orientation_classify: bool
    use_doc_unwarping: bool
    use_textline_orientation: bool
    use_tesseract_fallback: bool
    tesseract_cmd: str
    fallback_policy: str
    paddle_accept_score: float
    paddle_accept_vietnamese_quality: float
    tesseract_accept_score: float
    tesseract_max_variants: int
    reuse_ocr_cache: bool
    text_detection_model_dir: Path | None
    text_recognition_model_dir: Path | None
    tessdata_dir: Path | None


@dataclass(frozen=True, slots=True)
class WorkflowSettings:
    max_attempts: int
    continue_after_record_error: bool
    auto_complete: bool
    dry_run: bool


@dataclass(frozen=True, slots=True)
class DefaultsSettings:
    author: str
    security_level: str


@dataclass(frozen=True, slots=True)
class AppSettings:
    name: str
    version: str
    slot_id: int
    browser: BrowserSettings
    pdf: PdfSettings
    ocr: OcrSettings
    workflow: WorkflowSettings
    defaults: DefaultsSettings
    paths: AppPaths


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _resolve_path(project_root: Path, raw_value: str | None, default: Path) -> Path:
    if not raw_value:
        return default
    expanded = os.path.expandvars(os.path.expanduser(str(raw_value)))
    candidate = Path(expanded)
    return candidate if candidate.is_absolute() else project_root / candidate



def _installed_profile_path(
    paths: AppPaths,
    local: dict[str, Any],
    slot_id: int,
) -> Path:
    """Resolve an installed browser profile without reusing unsafe legacy profiles.

    Older releases stored automation profiles directly under LOCALAPPDATA and
    could persist those paths in local.yaml. Final customer releases bundle
    Playwright Chromium, so those old system-Chrome profiles must not be opened
    by the bundled browser. Preserve custom non-legacy overrides, but migrate the
    two historical automation paths to the slot-isolated profile automatically.
    """

    browser_local = local.get("browser") or {}
    key = "profile_dir_slot2" if slot_id == 2 else "profile_dir"
    candidate = _resolve_path(paths.data_root, browser_local.get(key), paths.browser_profile)

    legacy_name = (
        "KhoLuuTruAutomationChromeProfile_Slot2"
        if slot_id == 2
        else "KhoLuuTruAutomationChromeProfile"
    )
    legacy = paths.data_root.parent / legacy_name
    try:
        if candidate.resolve(strict=False) == legacy.resolve(strict=False):
            return paths.browser_profile
    except OSError:
        if os.path.normcase(os.path.normpath(str(candidate))) == os.path.normcase(
            os.path.normpath(str(legacy))
        ):
            return paths.browser_profile
    return candidate

def _resolve_slot_id(slot_id: int | None = None) -> int:
    raw = str(slot_id if slot_id is not None else os.environ.get("CATALOGING_SLOT", "1")).strip()
    try:
        resolved = int(raw)
    except ValueError as exc:
        raise ValueError(f"CATALOGING_SLOT không hợp lệ: {raw!r}") from exc
    if resolved not in {1, 2}:
        raise ValueError(f"CATALOGING_SLOT chỉ hỗ trợ 1 hoặc 2, nhận được: {resolved}")
    return resolved


def load_settings(project_root: Path, slot_id: int | None = None) -> AppSettings:
    resolved_slot_id = _resolve_slot_id(slot_id)
    paths = AppPaths.from_root(project_root, resolved_slot_id)

    default_path = project_root / "config" / "default.yaml"
    local_path = paths.user_config
    if not default_path.exists():
        raise FileNotFoundError(f"Không tìm thấy cấu hình mặc định: {default_path}")

    raw = yaml.safe_load(default_path.read_text(encoding="utf-8")) or {}
    local: dict[str, Any] = {}
    if local_path.exists():
        local = yaml.safe_load(local_path.read_text(encoding="utf-8")) or {}
        raw = _deep_merge(raw, local)
    app = raw["application"]
    browser = raw["browser"]
    pdf = raw["pdf"]
    ocr = raw["ocr"]
    workflow = raw["workflow"]
    defaults = raw["cataloging_defaults"]

    settings = AppSettings(
        name=str(app["name"]),
        version=str(app["version"]),
        slot_id=resolved_slot_id,
        browser=BrowserSettings(
            base_url=str(browser["base_url"]),
            channel=str(browser.get("channel", "chrome")),
            headless=bool(browser.get("headless", False)),
            timeout_ms=int(browser.get("timeout_ms", 30000)),
            profile_dir=(
                _installed_profile_path(paths, local, resolved_slot_id)
                if paths.installed
                else _resolve_path(
                    project_root,
                    browser.get("profile_dir_slot2")
                    if resolved_slot_id == 2
                    else browser.get("profile_dir"),
                    paths.browser_profile,
                )
            ),
            manual_login_timeout_ms=int(browser.get("manual_login_timeout_ms", 600_000)),
        ),
        pdf=PdfSettings(
            render_dpi=int(pdf.get("render_dpi", 300)),
            max_pages_for_header=int(pdf.get("max_pages_for_header", 1)),
            minimum_text_length=int(pdf.get("minimum_text_length", 80)),
            fast_viewer_fallback=bool(pdf.get("fast_viewer_fallback", True)),
            viewer_ready_timeout_ms=int(pdf.get("viewer_ready_timeout_ms", 3500)),
            direct_viewer_image=bool(pdf.get("direct_viewer_image", True)),
        ),
        ocr=OcrSettings(
            enabled=bool(ocr.get("enabled", True)),
            language=str(ocr.get("language", "vi")),
            minimum_confidence=float(ocr.get("minimum_confidence", 0.82)),
            device=str(ocr.get("device", "cpu")),
            enable_mkldnn=bool(ocr.get("enable_mkldnn", False)),
            cpu_threads=int(ocr.get("cpu_threads", 4)),
            text_detection_model_name=str(
                ocr.get("text_detection_model_name", "PP-OCRv5_mobile_det")
            ),
            text_recognition_model_name=str(
                ocr.get("text_recognition_model_name", "latin_PP-OCRv5_mobile_rec")
            ),
            use_doc_orientation_classify=bool(ocr.get("use_doc_orientation_classify", False)),
            use_doc_unwarping=bool(ocr.get("use_doc_unwarping", False)),
            use_textline_orientation=bool(ocr.get("use_textline_orientation", False)),
            use_tesseract_fallback=bool(ocr.get("use_tesseract_fallback", True)),
            tesseract_cmd=str(
                paths.tesseract_exe
                if paths.tesseract_exe.exists()
                else ocr.get("tesseract_cmd", r"C:/Program Files/Tesseract-OCR/tesseract.exe")
            ),
            fallback_policy=str(ocr.get("fallback_policy", "on_demand")),
            paddle_accept_score=float(ocr.get("paddle_accept_score", 0.78)),
            paddle_accept_vietnamese_quality=float(
                ocr.get("paddle_accept_vietnamese_quality", 0.62)
            ),
            tesseract_accept_score=float(ocr.get("tesseract_accept_score", 0.64)),
            tesseract_max_variants=int(ocr.get("tesseract_max_variants", 2)),
            reuse_ocr_cache=bool(ocr.get("reuse_ocr_cache", True)),
            text_detection_model_dir=(
                paths.models / str(ocr.get("text_detection_model_name", "PP-OCRv5_mobile_det"))
                if (paths.models / str(ocr.get("text_detection_model_name", "PP-OCRv5_mobile_det"))).exists()
                else None
            ),
            text_recognition_model_dir=(
                paths.models / str(ocr.get("text_recognition_model_name", "latin_PP-OCRv5_mobile_rec"))
                if (paths.models / str(ocr.get("text_recognition_model_name", "latin_PP-OCRv5_mobile_rec"))).exists()
                else None
            ),
            tessdata_dir=(
                paths.tesseract_dir / "tessdata"
                if (paths.tesseract_dir / "tessdata").exists()
                else None
            ),
        ),
        workflow=WorkflowSettings(
            max_attempts=int(workflow.get("max_attempts", 3)),
            continue_after_record_error=bool(workflow.get("continue_after_record_error", True)),
            auto_complete=bool(workflow.get("auto_complete", True)),
            dry_run=bool(workflow.get("dry_run", False)),
        ),
        defaults=DefaultsSettings(
            author=str(defaults["author"]),
            security_level=str(defaults["security_level"]),
        ),
        paths=paths,
    )
    settings.paths.ensure()
    return settings
