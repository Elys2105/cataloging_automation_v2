from __future__ import annotations

from cataloging_tool.automation.pages import DocumentListPage, external_id_from_url, normalize_lookup


def main() -> int:
    assert normalize_lookup("  Hồ   Sơ 27 ") == "hồ sơ 27"
    assert external_id_from_url("https://x.test/UpdateDoc?id=123") == "123"
    hashed = external_id_from_url("https://x.test/UpdateDoc/no-query")
    assert len(hashed) == 20
    assert DocumentListPage._extract_status("27 KH/ĐU Hoàn thành") == "Hoàn thành"
    print("Playwright page helper smoke test: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
