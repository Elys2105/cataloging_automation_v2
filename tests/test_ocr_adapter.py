from cataloging_tool.document.ocr import extract_paddle_lines


def test_paddle_v3_result() -> None:
    result = [{"res": {"rec_texts": ["KẾ HOẠCH"], "rec_scores": [0.98], "rec_polys": []}}]
    lines = extract_paddle_lines(result)
    assert lines[0].text == "KẾ HOẠCH"
    assert lines[0].confidence == 0.98


def test_legacy_result() -> None:
    result = [[[[0, 0], [1, 0], [1, 1], [0, 1]], ("CÔNG VĂN", 0.97)]]
    lines = extract_paddle_lines(result)
    assert lines[0].text == "CÔNG VĂN"
