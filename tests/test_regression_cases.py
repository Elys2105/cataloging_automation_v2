from pathlib import Path

import yaml

from cataloging_tool.document.parser import DocumentParser
from cataloging_tool.domain.enums import DataSource


def test_regression_cases() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = DocumentParser(root / "rules", "Tác giả", "Thường")
    cases = yaml.safe_load((root / "tests" / "regression" / "cases.yaml").read_text(encoding="utf-8"))
    for case in cases:
        result = parser.parse(case["text"], source=DataSource.PADDLE_OCR, source_confidence=0.95)
        expected = case["expected"]
        assert result.document_number.value == expected["document_number"], case["id"]
        assert result.symbol.value == expected["symbol"], case["id"]
        assert result.document_type.value == expected["document_type"], case["id"]
        assert expected["abstract_contains"] in result.abstract.value, case["id"]
