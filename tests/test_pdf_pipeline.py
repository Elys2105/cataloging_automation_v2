import fitz

from cataloging_tool.document.pdf_pipeline import PdfPipeline


def test_extract_and_render(tmp_path) -> None:
    pdf = tmp_path / "sample.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((50, 50), "SO 27-KH/DU KE HOACH VAN BAN MAU " * 5)
    document.save(pdf)
    document.close()
    pipeline = PdfPipeline(tmp_path / "render", render_dpi=100, minimum_text_length=20)
    result = pipeline.extract_text(pdf)
    assert result.page_count == 1
    rendered = pipeline.render_first_page(pdf, "sample")
    assert rendered.full_page.exists()
    assert rendered.header_crop.exists()
