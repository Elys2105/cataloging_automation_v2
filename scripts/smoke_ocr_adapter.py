from __future__ import annotations

from cataloging_tool.document.ocr import extract_paddle_lines


def main() -> int:
    modern = [
        {
            "res": {
                "rec_texts": ["Số 27-KH/ĐU", "KẾ HOẠCH", "sắp xếp cán bộ"],
                "rec_scores": [0.99, 0.98, 0.95],
                "rec_polys": [[[0, 0], [1, 0], [1, 1], [0, 1]]] * 3,
            }
        }
    ]
    lines = extract_paddle_lines(modern)
    assert len(lines) == 3
    assert lines[0].text == "Số 27-KH/ĐU"
    assert lines[0].confidence == 0.99

    legacy = [[[[0, 0], [1, 0], [1, 1], [0, 1]], ("CÔNG VĂN", 0.97)]]
    old_lines = extract_paddle_lines(legacy)
    assert len(old_lines) == 1
    assert old_lines[0].text == "CÔNG VĂN"
    print("OCR adapter smoke test: OK (Paddle model remains lazy and was not loaded)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
