from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger(__name__)


class ArtifactManager:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def attempt_dir(self, job_id: int, record_id: int, attempt: int) -> Path:
        path = self.root / f"job-{job_id}" / f"record-{record_id}" / f"attempt-{attempt}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def _json_ready(cls, value: Any) -> Any:
        if is_dataclass(value) and not isinstance(value, type):
            return cls._json_ready(asdict(cast(Any, value)))
        if isinstance(value, dict):
            return {str(key): cls._json_ready(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [cls._json_ready(item) for item in value]
        if isinstance(value, Path):
            return str(value)
        return value

    @classmethod
    def write_json(cls, path: Path, value: Any) -> Path:
        payload = cls._json_ready(value)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return path


    @staticmethod
    def sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def write_diagnostic_manifest(
        self,
        directory: Path,
        *,
        source_pdf: Path | None,
        ocr_path: Path | None,
        existing_form: Any,
        parsed: Any,
        extracted: Any,
        final_status: str,
    ) -> Path:
        source_payload: dict[str, Any] = {"path": str(source_pdf or "")}
        if source_pdf is not None and source_pdf.exists():
            source_payload.update(
                {
                    "sha256": self.sha256_file(source_pdf),
                    "size": source_pdf.stat().st_size,
                }
            )
        rendered = getattr(extracted, "rendered", None)
        ocr_artifacts: list[str] = []
        if ocr_path is not None and ocr_path.parent.exists():
            for candidate in sorted(ocr_path.parent.iterdir()):
                if candidate.is_file() and candidate.suffix.lower() in {".png", ".txt", ".json"}:
                    ocr_artifacts.append(str(candidate))
        payload = {
            "source_pdf": source_payload,
            "ocr_path": str(ocr_path or ""),
            "ocr_artifacts": ocr_artifacts,
            "rendered": {
                "full_page": str(getattr(rendered, "full_page", "") or ""),
                "header_crop": str(getattr(rendered, "header_crop", "") or ""),
            },
            "ocr_result": getattr(extracted, "ocr_result", None),
            "existing_form": existing_form,
            "final_reconciliation": parsed.to_dict() if hasattr(parsed, "to_dict") else parsed,
            "evidence": {
                "source": str(getattr(extracted, "source", "")),
                "confidence": float(getattr(extracted, "confidence", 0.0) or 0.0),
                "header": str(getattr(extracted, "header_evidence_text", "") or ""),
                "author": str(getattr(extracted, "author_evidence_text", "") or ""),
                "signature": str(getattr(extracted, "signature_evidence_text", "") or ""),
                "special_report_title": str(getattr(extracted, "special_report_title", "") or ""),
            },
            "final_status": final_status,
        }
        return self.write_json(directory / "diagnostic.json", payload)

    @staticmethod
    def prune_completed_attempt(directory: Path) -> None:
        # Completed records do not need browser dumps. Keep the compact JSON/text
        # evidence needed for audit/resume, but remove accidental heavy captures.
        for name in ("screenshot.png", "page.html"):
            path = directory / name
            try:
                if path.exists():
                    path.unlink()
            except OSError as exc:
                logger.debug("Không xóa được artifact hoàn thành %s: %s", path, exc)

    @staticmethod
    async def capture_page(page: Any, directory: Path) -> None:
        try:
            await page.screenshot(path=str(directory / "screenshot.png"), full_page=True)
        except Exception as exc:
            logger.debug("Không chụp được screenshot artifact: %s", exc)
        try:
            (directory / "page.html").write_text(await page.content(), encoding="utf-8")
        except Exception as exc:
            logger.debug("Không lưu được HTML artifact: %s", exc)
