from pathlib import Path

from cataloging_tool.config.settings import load_settings
from cataloging_tool.domain.models import OcrLine, OcrResult
from cataloging_tool.document.ocr import (
    PaddleOcrEngine,
    is_pir_onednn_error,
    parse_tesseract_tsv,
)


class _FailingEngine:
    def predict(self, **_kwargs):
        raise RuntimeError(
            "(Unimplemented) ConvertPirAttribute2RuntimeAttribute not support "
            "[pir::ArrayAttribute<pir::DoubleAttribute>] at onednn_instruction.cc"
        )


class _Fallback:
    def recognize(self, _path: Path) -> OcrResult:
        return OcrResult(
            raw_text="Số 81-TB/ĐU\nTHÔNG BÁO",
            confidence=0.91,
            lines=[OcrLine("Số 81-TB/ĐU", 0.91)],
            engine="tesseract:vie+eng",
        )


def test_safe_paddle_kwargs_disable_mkldnn() -> None:
    root = Path(__file__).resolve().parents[1]
    engine = PaddleOcrEngine(load_settings(root).ocr)
    kwargs = engine._engine_kwargs()
    assert kwargs["enable_mkldnn"] is False
    assert kwargs["device"] == "cpu"
    assert kwargs["text_detection_model_name"] == "PP-OCRv5_mobile_det"
    assert kwargs["text_recognition_model_name"] == "latin_PP-OCRv5_mobile_rec"
    assert kwargs["use_doc_orientation_classify"] is False
    assert kwargs["use_textline_orientation"] is False


def test_pir_onednn_failure_uses_tesseract_fallback(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    engine = PaddleOcrEngine(load_settings(root).ocr)
    image = tmp_path / "page.png"
    image.write_bytes(b"not-used-by-fakes")
    engine._get_engine = lambda: _FailingEngine()  # type: ignore[method-assign]
    engine._tesseract = _Fallback()  # type: ignore[assignment]
    result = engine.recognize(image)
    assert result.engine == "tesseract:vie+eng"
    assert "THÔNG BÁO" in result.raw_text


def test_detects_exact_pir_onednn_error() -> None:
    exc = RuntimeError(
        "ConvertPirAttribute2RuntimeAttribute not support "
        "[pir::ArrayAttribute<pir::DoubleAttribute>] at onednn_instruction.cc"
    )
    assert is_pir_onednn_error(exc)


def test_parse_tesseract_tsv_groups_words_by_line() -> None:
    raw = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        "5\t1\t1\t1\t1\t1\t10\t20\t30\t10\t90\tSố\n"
        "5\t1\t1\t1\t1\t2\t45\t20\t60\t10\t92\t81-TB/ĐU\n"
    )
    lines = parse_tesseract_tsv(raw)
    assert len(lines) == 1
    assert lines[0].text == "Số 81-TB/ĐU"
    assert 0.90 <= lines[0].confidence <= 0.92


class _EmptyEngine:
    def __init__(self) -> None:
        self.calls = 0

    def predict(self, **_kwargs):
        self.calls += 1
        return [{"rec_texts": [], "rec_scores": [], "rec_polys": []}]


def test_empty_paddle_result_does_not_reset_initialized_engine(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    engine = PaddleOcrEngine(load_settings(root).ocr)
    paddle = _EmptyEngine()
    engine._engine = paddle
    engine._engine_profile = "test-empty"
    engine._tesseract = _Fallback()  # type: ignore[assignment]

    first_image = tmp_path / "blank-a.png"
    second_image = tmp_path / "blank-b.png"
    first_image.write_bytes(b"blank-a")
    second_image.write_bytes(b"blank-b")

    first = engine.recognize(first_image)
    assert first.engine == "tesseract:vie+eng"
    assert engine._engine is paddle

    second = engine.recognize(second_image)
    assert second.engine == "tesseract:vie+eng"
    assert engine._engine is paddle
    assert paddle.calls == 2
