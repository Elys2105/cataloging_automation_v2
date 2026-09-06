from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from cataloging_tool.config.settings import load_settings
from cataloging_tool.document.ocr import PaddleOcrEngine
from cataloging_tool.document.parser import DocumentParser
from cataloging_tool.document.pdf_pipeline import PdfPipeline
from cataloging_tool.domain.enums import DataSource


@dataclass(slots=True)
class SampleResult:
    label: str
    sha256: str
    bytes: int
    pages: int
    text_usable: bool
    text_ms: float
    render_ms: float
    preprocess_ms: float
    ocr_ms: float | None
    ocr_engine: str | None
    ocr_lines: int | None
    ocr_confidence: float | None
    parse_ms: float
    total_ms: float


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_sample(raw: str) -> tuple[str, Path]:
    if "=" not in raw:
        raise argparse.ArgumentTypeError("Use LABEL=PDF_PATH")
    label, value = raw.split("=", 1)
    path = Path(value).expanduser().resolve()
    if not label.strip() or not path.is_file():
        raise argparse.ArgumentTypeError(f"Invalid benchmark sample: {raw}")
    return label.strip(), path


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def benchmark_one(
    label: str,
    pdf_path: Path,
    *,
    root: Path,
    enable_ocr: bool,
    engine: PaddleOcrEngine | None,
) -> SampleResult:
    started_total = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="cataloging-benchmark-") as temp:
        out = Path(temp)
        settings = load_settings(root)
        pipeline = PdfPipeline(out / "rendered", render_dpi=settings.pdf.render_dpi, minimum_text_length=settings.pdf.minimum_text_length)

        started = time.perf_counter()
        text = pipeline.extract_text(pdf_path, max_pages=max(1, settings.pdf.max_pages_for_header))
        text_ms = _ms(started)

        started = time.perf_counter()
        rendered = pipeline.render_first_page(pdf_path, "sample")
        render_ms = _ms(started)

        started = time.perf_counter()
        processed = pipeline.preprocess_for_ocr(rendered.header_crop, out / "processed.png")
        preprocess_ms = _ms(started)

        ocr_ms: float | None = None
        ocr_engine: str | None = None
        ocr_lines: int | None = None
        ocr_confidence: float | None = None
        parse_input = text.text
        parse_source = DataSource.PDF_TEXT
        parse_confidence = 1.0 if text.usable else 0.0
        if enable_ocr:
            if engine is None:
                raise RuntimeError("OCR engine not initialized")
            started = time.perf_counter()
            ocr = engine.recognize(processed)
            ocr_ms = _ms(started)
            ocr_engine = ocr.engine
            ocr_lines = len(ocr.lines)
            ocr_confidence = round(float(ocr.confidence), 4)
            if not text.usable:
                parse_input = ocr.raw_text
                parse_source = DataSource.PADDLE_OCR
                parse_confidence = float(ocr.confidence)

        parser = DocumentParser(root / "rules", author="", security_level="Thường")
        started = time.perf_counter()
        parser.parse(parse_input, source=parse_source, source_confidence=parse_confidence)
        parse_ms = _ms(started)

        return SampleResult(
            label=label,
            sha256=_sha256(pdf_path),
            bytes=pdf_path.stat().st_size,
            pages=text.page_count,
            text_usable=text.usable,
            text_ms=text_ms,
            render_ms=render_ms,
            preprocess_ms=preprocess_ms,
            ocr_ms=ocr_ms,
            ocr_engine=ocr_engine,
            ocr_lines=ocr_lines,
            ocr_confidence=ocr_confidence,
            parse_ms=parse_ms,
            total_ms=_ms(started_total),
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Local benchmark. Output contains hashes/timings only, never OCR/document text."
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--pdf", action="append", type=_parse_sample, required=True, metavar="LABEL=PATH")
    parser.add_argument("--ocr", action="store_true", help="Include real Paddle/Tesseract OCR timing")
    parser.add_argument("--output", type=Path, help="Write JSON result")
    parser.add_argument("--csv", type=Path, help="Write CSV result")
    args = parser.parse_args()

    root = args.root.resolve()
    settings = load_settings(root)
    engine = PaddleOcrEngine(settings.ocr) if args.ocr else None
    results = [
        benchmark_one(label, path, root=root, enable_ocr=args.ocr, engine=engine)
        for label, path in args.pdf
    ]
    payload = {
        "privacy": "No OCR text, parsed field values, file names, or document contents are emitted.",
        "ocr_enabled": args.ocr,
        "samples": [asdict(item) for item in results],
        "summary": {
            "count": len(results),
            "median_total_ms": round(statistics.median(item.total_ms for item in results), 3),
            "median_ocr_ms": (
                round(statistics.median(item.ocr_ms for item in results if item.ocr_ms is not None), 3)
                if any(item.ocr_ms is not None for item in results)
                else None
            ),
        },
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        rows = [asdict(item) for item in results]
        with args.csv.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
