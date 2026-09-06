from cataloging_tool.automation.pdf_detector import looks_like_pdf, safe_record_key


def test_pdf_validation() -> None:
    assert looks_like_pdf(b"%PDF-1.7\n%%EOF", "application/pdf")
    assert not looks_like_pdf(b"<html>error</html>", "application/pdf")


def test_safe_record_key() -> None:
    assert safe_record_key("27-KH/ĐU") == "27-KH-U"
