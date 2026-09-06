from __future__ import annotations

import os
from pathlib import Path

from cataloging_tool.config.settings import load_settings
from cataloging_tool.document.ocr import PaddleOcrEngine


def find_image(root: Path) -> Path:
    patterns = (
        "runtime/ocr/**/preprocessed.png",
        "runtime/rendered/**/page-1-header.png",
        "runtime/rendered/**/page-1.png",
    )
    files: list[Path] = []
    for pattern in patterns:
        files.extend(root.glob(pattern))
    files = [path for path in files if path.is_file()]
    if not files:
        raise SystemExit(
            "Không tìm thấy ảnh runtime để test. Hãy chạy tool tới bước chụp PDF một lần rồi chạy lại script."
        )
    return max(files, key=lambda path: path.stat().st_mtime)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    os.environ["FLAGS_use_mkldnn"] = "0"
    os.environ["FLAGS_enable_mkldnn"] = "0"
    settings = load_settings(root)
    image = find_image(root)
    print(f"OCR smoke image: {image}")
    result = PaddleOcrEngine(settings.ocr).recognize(image)
    print(f"OCR engine: {result.engine}")
    print(f"Confidence: {result.confidence:.3f}")
    print(result.raw_text[:500])
    if not result.raw_text.strip():
        raise SystemExit("OCR trả về text rỗng")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
