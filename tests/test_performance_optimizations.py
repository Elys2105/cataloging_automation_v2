from pathlib import Path

from PIL import Image

from cataloging_tool.config.settings import load_settings
from cataloging_tool.domain.models import OcrLine, OcrResult
from cataloging_tool.document.ocr import PaddleOcrEngine
from cataloging_tool.document.pdf_pipeline import PdfPipeline


class _GoodPaddle:
    def predict(self, **_kwargs):
        return [
            {
                "rec_texts": [
                    "ĐẢNG CỘNG SẢN VIỆT NAM",
                    "Số 82-TB/ĐU",
                    "THÔNG BÁO",
                    "KẾT LUẬN CỦA BAN THƯỜNG VỤ ĐẢNG ỦY",
                    "Về đánh giá kết quả thực hiện nhiệm vụ năm 2025",
                ],
                "rec_scores": [0.98, 0.98, 0.99, 0.97, 0.96],
                "rec_polys": [None, None, None, None, None],
            }
        ]


class _FallbackMustNotRun:
    def recognize(self, _path: Path):
        raise AssertionError("Tesseract must be skipped for good Paddle OCR")


class _BadPaddle:
    def predict(self, **_kwargs):
        return [
            {
                "rec_texts": ["KT LUN CA BAN THƯNG VU ĐNG Y"],
                "rec_scores": [0.97],
                "rec_polys": [None],
            }
        ]


class _FallbackCalled:
    def __init__(self) -> None:
        self.called = False

    def recognize(self, _path: Path) -> OcrResult:
        self.called = True
        return OcrResult(
            raw_text="KẾT LUẬN CỦA BAN THƯỜNG VỤ ĐẢNG ỦY",
            confidence=0.91,
            lines=[OcrLine("KẾT LUẬN CỦA BAN THƯỜNG VỤ ĐẢNG ỦY", 0.91)],
            engine="tesseract:vie+eng:psm6",
        )


def test_good_paddle_skips_tesseract(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    engine = PaddleOcrEngine(load_settings(root).ocr)
    image = tmp_path / "page.png"
    image.write_bytes(b"fake")
    engine._get_engine = lambda: _GoodPaddle()  # type: ignore[method-assign]
    engine._tesseract = _FallbackMustNotRun()  # type: ignore[assignment]

    result = engine.recognize(image)

    assert result.engine.startswith("paddleocr:")
    assert "THÔNG BÁO" in result.raw_text


def test_weak_paddle_runs_tesseract_on_demand(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    engine = PaddleOcrEngine(load_settings(root).ocr)
    image = tmp_path / "page.png"
    image.write_bytes(b"fake")
    fallback = _FallbackCalled()
    engine._get_engine = lambda: _BadPaddle()  # type: ignore[method-assign]
    engine._tesseract = fallback  # type: ignore[assignment]

    result = engine.recognize(image)

    assert fallback.called is True
    assert "KẾT LUẬN" in result.raw_text


def test_viewer_image_is_cropped_directly_without_pdf_render(tmp_path: Path) -> None:
    source = tmp_path / "viewer.png"
    Image.new("RGB", (1200, 1600), "white").save(source)
    pipeline = PdfPipeline(tmp_path / "rendered", render_dpi=300, minimum_text_length=80)

    rendered = pipeline.prepare_image_first_page(source, "record-1", header_ratio=0.55)

    assert rendered.full_page == source
    assert rendered.header_crop.exists()
    with Image.open(rendered.header_crop) as header:
        assert header.size == (1200, 880)


def test_speed_settings_are_enabled_by_default() -> None:
    root = Path(__file__).resolve().parents[1]
    settings = load_settings(root)
    assert settings.pdf.fast_viewer_fallback is True
    assert settings.pdf.direct_viewer_image is True
    assert settings.ocr.fallback_policy == "on_demand"
    assert settings.ocr.tesseract_max_variants == 2
    assert settings.ocr.reuse_ocr_cache is True


class _ReportRecoveryEngine:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def recognize(self, path: Path) -> OcrResult:
        self.calls.append(path.name)
        if "report-title" in path.name:
            text = (
                "Số 91-BC/ĐU\n"
                "BÁO CÁO NGÀY 11 THÁNG 9 NĂM 2025\n"
                "VỀ CÔNG TÁC NỘI CHÍNH, PHÒNG CHỐNG THAM NHŨNG, "
                "LÃNG PHÍ TIÊU CỰC VÀ CẢI CÁCH TƯ PHÁP\n"
                "Danh sách chuyên viên"
            )
            return OcrResult(
                raw_text=text,
                confidence=0.94,
                lines=[OcrLine(line, 0.94) for line in text.splitlines()],
                engine="fake-report-title",
            )
        text = "ĐẢNG ỦY PHƯỜNG BÌNH TIÊN\nSố 91-BC/ĐU\nA. TÌNH HÌNH, KẾT QUẢ"
        return OcrResult(
            raw_text=text,
            confidence=0.92,
            lines=[OcrLine(line, 0.92) for line in text.splitlines()],
            engine="fake-generic",
        )


def test_special_report_title_recovery_runs_only_for_bc_hint(tmp_path: Path) -> None:
    from cataloging_tool.document.text_extractor import DocumentTextExtractor

    source = tmp_path / "landscape-viewer.png"
    Image.new("RGB", (1800, 1000), "white").save(source)
    fake_pdf = tmp_path / "viewer.pdf"
    fake_pdf.write_bytes(b"not-used-because-source-image-is-direct")
    pipeline = PdfPipeline(tmp_path / "rendered", render_dpi=300, minimum_text_length=80)
    engine = _ReportRecoveryEngine()
    extractor = DocumentTextExtractor(
        pipeline,
        engine,
        tmp_path / "ocr",
        reuse_ocr_cache=False,
        direct_viewer_image=True,
    )

    result = extractor.extract(
        fake_pdf,
        "record-91",
        source_image=source,
        document_symbol_hint="BC/ĐU",
        document_type_hint="Khác",
    )

    assert result.special_report_title.startswith(
        "BÁO CÁO NGÀY 11 THÁNG 9 NĂM 2025"
    )
    assert any("report-title" in name for name in engine.calls)


def test_old_ocr_cache_is_invalidated_by_cache_version(tmp_path: Path) -> None:
    import json
    from cataloging_tool.document.text_extractor import DocumentTextExtractor

    artifact = tmp_path / "ocr" / "record-1"
    artifact.mkdir(parents=True)
    (artifact / "ocr-cache.json").write_text(
        json.dumps({
            "input_sha256": "same-hash",
            "raw_text": "old broken OCR",
            "confidence": 0.99,
            "engine": "old",
            "lines": [],
        }),
        encoding="utf-8",
    )
    pipeline = PdfPipeline(tmp_path / "rendered")
    extractor = DocumentTextExtractor(pipeline, _ReportRecoveryEngine(), tmp_path / "ocr")

    assert extractor._load_cache(artifact, "same-hash") is None


def test_special_report_generic_title_is_bounded_without_recovery(tmp_path: Path) -> None:
    from cataloging_tool.document.text_extractor import DocumentTextExtractor

    class _InlineReportEngine:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def recognize(self, path: Path) -> OcrResult:
            self.calls.append(path.name)
            text = (
                "Số 116-BC/ĐU\n"
                "BÁO CÁO NGÀY 25 THÁNG 9 NĂM 2025\n"
                "V CÔNG TC NỘI CHÍNH, PHÒNG CHỐNG THAM NHNG, "
                "LNG PHÍ TIU CC VÀ CẢI CÁCH TU PHÁP\n"
                "Thc hin Công văn s 279-CV/BNCTU"
            )
            return OcrResult(
                raw_text=text,
                confidence=0.82,
                lines=[OcrLine(line, 0.82) for line in text.splitlines()],
                engine="fake-inline-report",
            )

    source = tmp_path / "landscape-viewer.png"
    Image.new("RGB", (1800, 1000), "white").save(source)
    fake_pdf = tmp_path / "viewer.pdf"
    fake_pdf.write_bytes(b"not-used")
    pipeline = PdfPipeline(tmp_path / "rendered", render_dpi=300, minimum_text_length=80)
    engine = _InlineReportEngine()
    extractor = DocumentTextExtractor(
        pipeline,
        engine,
        tmp_path / "ocr",
        reuse_ocr_cache=False,
        direct_viewer_image=True,
    )

    result = extractor.extract(
        fake_pdf,
        "record-116",
        source_image=source,
        document_symbol_hint="BC/ĐU",
        document_type_hint="Báo cáo",
    )

    assert result.special_report_title == (
        "BÁO CÁO NGÀY 25 THÁNG 9 NĂM 2025 "
        "VỀ CÔNG TÁC NỘI CHÍNH, PHÒNG CHỐNG THAM NHŨNG, "
        "LÃNG PHÍ TIÊU CỰC VÀ CẢI CÁCH TƯ PHÁP"
    )
    assert "279-CV" not in result.special_report_title

class _WeakThenGoodHeaderEngine:
    def __init__(self) -> None:
        self.header_crop_calls = 0

    def recognize(self, path: Path) -> OcrResult:
        if "document-header" in path.name:
            self.header_crop_calls += 1
            text = "Số 234-CV/ĐU\nVề việc xác minh thái độ chính trị hiện nay phục vụ công tác cán bộ"
            return OcrResult(
                raw_text=text,
                confidence=0.94,
                lines=[OcrLine(line, 0.94) for line in text.splitlines()],
                engine="fake-focused-header",
            )
        text = "mờ nhòe không xác định"
        return OcrResult(
            raw_text=text,
            confidence=0.25,
            lines=[OcrLine(text, 0.25)],
            engine="fake-weak-page",
        )


def test_unhinted_weak_page_ocr_triggers_header_crop_rescue_0124(tmp_path: Path) -> None:
    from cataloging_tool.document.text_extractor import DocumentTextExtractor

    source = tmp_path / "viewer.png"
    Image.new("RGB", (1200, 1600), "white").save(source)
    fake_pdf = tmp_path / "viewer.pdf"
    fake_pdf.write_bytes(b"not-used-because-source-image-is-direct")
    pipeline = PdfPipeline(tmp_path / "rendered", render_dpi=300, minimum_text_length=80)
    engine = _WeakThenGoodHeaderEngine()
    extractor = DocumentTextExtractor(
        pipeline,
        engine,
        tmp_path / "ocr",
        reuse_ocr_cache=False,
        direct_viewer_image=True,
    )

    result = extractor.extract(
        fake_pdf,
        "record-234",
        source_image=source,
        document_symbol_hint="",
        document_type_hint="",
    )

    assert engine.header_crop_calls >= 1
    assert "234-CV/ĐU" in result.header_evidence_text
