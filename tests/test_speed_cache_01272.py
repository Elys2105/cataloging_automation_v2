from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PIL import Image

from cataloging_tool.config.settings import load_settings
from cataloging_tool.document.ocr import PaddleOcrEngine, TesseractOcrEngine
from cataloging_tool.document.pdf_pipeline import PdfPipeline


class _CountingGoodPaddle:
    def __init__(self) -> None:
        self.calls = 0

    def predict(self, **_kwargs):
        self.calls += 1
        return [
            {
                "rec_texts": [
                    "ĐẢNG CỘNG SẢN VIỆT NAM",
                    "Số 82-TB/ĐU",
                    "THÔNG BÁO",
                    "Về đánh giá kết quả thực hiện nhiệm vụ năm 2025",
                ],
                "rec_scores": [0.99, 0.98, 0.99, 0.97],
                "rec_polys": [None, None, None, None],
            }
        ]


class _MustNotRun:
    def recognize(self, _path: Path):
        raise AssertionError("Tesseract must not run for this strong Paddle result")


def test_same_image_is_not_sent_to_paddle_twice(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    engine = PaddleOcrEngine(load_settings(root).ocr)
    image = tmp_path / "header.png"
    image.write_bytes(b"same-image")
    paddle = _CountingGoodPaddle()
    engine._get_engine = lambda: paddle  # type: ignore[method-assign]
    engine._tesseract = _MustNotRun()  # type: ignore[assignment]

    first = engine.recognize(image)
    first.engine = "caller-mutated-value"
    second = engine.recognize(image)

    assert paddle.calls == 1
    assert second.engine.startswith("paddleocr:")
    assert second.raw_text == first.raw_text


def test_same_image_is_not_sent_to_tesseract_twice(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = Path(__file__).resolve().parents[1]
    engine = TesseractOcrEngine(load_settings(root).ocr)
    engine._command = "tesseract-test-double"
    image = tmp_path / "header.png"
    image.write_bytes(b"same-image")
    calls = 0
    tsv = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        "5\t1\t1\t1\t1\t1\t0\t0\t200\t40\t98\tĐẢNG\n"
        "5\t1\t1\t1\t1\t2\t210\t0\t200\t40\t98\tCỘNG\n"
        "5\t1\t1\t1\t1\t3\t420\t0\t200\t40\t98\tSẢN\n"
        "5\t1\t1\t1\t1\t4\t630\t0\t200\t40\t98\tVIỆT\n"
        "5\t1\t1\t1\t1\t5\t840\t0\t200\t40\t98\tNAM\n"
        "5\t1\t1\t1\t2\t1\t0\t50\t200\t40\t98\tSố\n"
        "5\t1\t1\t1\t2\t2\t210\t50\t300\t40\t98\t82-TB/ĐU\n"
    )

    def fake_run(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess([], 0, stdout=tsv, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    first = engine.recognize(image)
    second = engine.recognize(image)

    assert calls == 1
    assert second.raw_text == first.raw_text


def test_preprocessed_image_is_reused_and_capped_to_model_limit(tmp_path: Path) -> None:
    source = tmp_path / "large-header.png"
    Image.new("L", (4200, 791), 255).save(source)
    output = tmp_path / "header-preprocessed.png"
    pipeline = PdfPipeline(tmp_path / "rendered")

    pipeline.preprocess_for_ocr(source, output, target_width=4200)
    with Image.open(output) as image:
        assert max(image.size) <= 4000

    future = output.stat().st_mtime_ns + 10_000_000_000
    os.utime(output, ns=(future, future))
    pipeline.preprocess_for_ocr(source, output, target_width=4200)

    assert output.stat().st_mtime_ns == future
