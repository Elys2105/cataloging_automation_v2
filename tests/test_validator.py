from cataloging_tool.document.validator import DocumentValidator
from cataloging_tool.domain.models import ParsedDocument, ParsedField


def test_rejects_body_leak() -> None:
    document = ParsedDocument(
        document_number=ParsedField("1", 0.99),
        symbol=ParsedField("KH/ĐU", 0.99),
        document_type=ParsedField("Kế hoạch", 0.99),
        abstract=ParsedField("Tổ chức hội nghị Kính gửi Ban Tổ chức", 0.99),
        overall_confidence=0.99,
    )
    DocumentValidator().validate(document)
    assert not DocumentValidator.can_auto_submit(document)


def test_rejects_corrupted_vietnamese_abstract() -> None:
    from cataloging_tool.domain.enums import DataSource
    from cataloging_tool.domain.models import ParsedDocument, ParsedField

    document = ParsedDocument(
        document_number=ParsedField("82", 0.98, ""),
        symbol=ParsedField("TB/ĐU", 0.98, ""),
        document_type=ParsedField("Thông báo", 0.98, ""),
        abstract=ParsedField(
            "KT LUN CA BAN THƯNG VU ĐNG Y Về đánh giá kt quă the hin nhim v năm 2025 đi vói đng chí Trn Th Thu Hà",
            0.95,
            "",
        ),
        author="Tác giả",
        security_level="Thường",
        source=DataSource.PADDLE_OCR,
        overall_confidence=0.95,
    )
    issues = DocumentValidator().validate(document)
    assert any(issue.code == "CORRUPTED_VIETNAMESE" for issue in issues)
    assert not DocumentValidator.can_auto_submit(document)


def test_correct_structured_abstract_is_not_rejected_only_by_generic_quality_score() -> None:
    from cataloging_tool.domain.enums import DataSource

    document = ParsedDocument(
        document_number=ParsedField("82", 0.98),
        symbol=ParsedField("TB/ĐU", 0.98),
        document_type=ParsedField("Thông báo", 0.98),
        abstract=ParsedField(
            "KẾT LUẬN CỦA BAN THƯỜNG VỤ ĐẢNG ỦY Về công tác cán bộ năm 2025",
            0.95,
        ),
        source=DataSource.PADDLE_OCR,
        overall_confidence=0.90,
    )
    issues = DocumentValidator().validate(document)
    assert not any(issue.code == "CORRUPTED_VIETNAMESE" for issue in issues)
    assert DocumentValidator.can_auto_submit(document)


def test_rejects_unrepaired_to_trinh_missing_letter_patterns() -> None:
    from cataloging_tool.domain.enums import DataSource

    document = ParsedDocument(
        document_number=ParsedField("14", 0.98),
        symbol=ParsedField("TTR/ĐU", 0.98),
        document_type=ParsedField("Tờ trình", 0.98),
        abstract=ParsedField(
            "V ch dnh di biu d hi di biu Dng b phung Binh Tien ln th I nhim k 2025 2030",
            0.95,
        ),
        source=DataSource.PADDLE_OCR,
        overall_confidence=0.95,
    )
    issues = DocumentValidator().validate(document)
    assert any(issue.code == "CORRUPTED_VIETNAMESE" for issue in issues)
    assert not DocumentValidator.can_auto_submit(document)


def test_repaired_thong_bao_title_is_not_marked_corrupted() -> None:
    from cataloging_tool.domain.enums import DataSource

    document = ParsedDocument(
        document_number=ParsedField("78", 0.98),
        symbol=ParsedField("TB/ĐU", 0.98),
        document_type=ParsedField("Thông báo", 0.98),
        abstract=ParsedField(
            "KẾT LUẬN CỦA BAN THƯỜNG VỤ ĐẢNG ỦY Về đánh giá kết quả "
            "thực hiện nhiệm vụ năm 2025 đối với đồng chí Võ Thị Cẩm Tú",
            0.98,
        ),
        source=DataSource.PADDLE_OCR,
        overall_confidence=0.88,
    )
    issues = DocumentValidator().validate(document)
    assert not any(issue.code == "CORRUPTED_VIETNAMESE" for issue in issues)
    assert DocumentValidator.can_auto_submit(document)


def test_production_validator_blocks_missing_author_with_specific_error() -> None:
    document = ParsedDocument(
        document_number=ParsedField("12", 0.99),
        symbol=ParsedField("KH/ĐU", 0.99),
        document_type=ParsedField("Kế hoạch", 0.99),
        abstract=ParsedField("Triển khai nhiệm vụ năm 2026", 0.99),
        author="",
        overall_confidence=0.99,
    )
    issues = DocumentValidator(require_author=True).validate(document)
    assert any(issue.code == "AUTHOR_NOT_RECOVERED" for issue in issues)
    assert not DocumentValidator.can_auto_submit(document)
