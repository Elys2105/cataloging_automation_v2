from __future__ import annotations

import sys
from pathlib import Path

import yaml


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    path = root / "config" / "local.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(raw, dict):
        raw = {}
    ocr = raw.setdefault("ocr", {})
    ocr.update(
        {
            "device": "cpu",
            "enable_mkldnn": False,
            "cpu_threads": 4,
            "text_detection_model_name": "PP-OCRv5_mobile_det",
            "text_recognition_model_name": "latin_PP-OCRv5_mobile_rec",
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
            "use_tesseract_fallback": True,
            "tesseract_cmd": "C:/Program Files/Tesseract-OCR/tesseract.exe",
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print(f"Đã ghi cấu hình OCR an toàn: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
