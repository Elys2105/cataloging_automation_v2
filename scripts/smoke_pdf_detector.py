from __future__ import annotations

import tempfile
from pathlib import Path

from cataloging_tool.automation.pdf_detector import PdfAcquirer, PdfCandidate, looks_like_pdf, safe_record_key


def main() -> int:
    data = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF"
    assert looks_like_pdf(data, "application/pdf", "https://x.test/file")
    assert not looks_like_pdf(b"not pdf", "application/pdf", "https://x.test/file")
    assert safe_record_key("27-KH/ĐU") == "27-KH-U"
    with tempfile.TemporaryDirectory() as directory:
        acquirer = PdfAcquirer(Path(directory))
        result = acquirer._save(
            PdfCandidate(source="test", url="https://x.test/file.pdf", content=data),
            "27-KH/ĐU",
        )
        assert result.path.exists()
        assert result.size_bytes == len(data)
        assert result.sha256
    print("PDF detector smoke test: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
