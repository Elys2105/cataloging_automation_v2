from __future__ import annotations

import tempfile
from pathlib import Path

import fitz
from PIL import Image

from cataloging_tool.document.pdf_pipeline import PdfPipeline


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        pdf = root / "sample.pdf"
        document = fitz.open()
        page = document.new_page(width=595, height=842)
        page.insert_text((72, 72), "SO 27-KH/DU\nKE HOACH\nTo chuc cong tac tai phuong", fontsize=14)
        document.save(pdf)
        document.close()

        pipeline = PdfPipeline(root / "rendered", render_dpi=150, minimum_text_length=20)
        text = pipeline.extract_text(pdf)
        assert text.page_count == 1
        assert "27-KH/DU" in text.text
        rendered = pipeline.render_first_page(pdf, "record-27")
        assert rendered.full_page.exists()
        assert rendered.header_crop.exists()
        with Image.open(rendered.header_crop) as image:
            assert image.width == rendered.width
            assert image.height < rendered.height
        processed = pipeline.preprocess_for_ocr(rendered.header_crop, root / "processed.png")
        assert processed.exists()
    print("PDF pipeline smoke test: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
