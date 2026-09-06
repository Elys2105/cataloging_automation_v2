from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cataloging_tool.config.deployment import resource_root
from cataloging_tool.config.settings import load_settings


def find_project_root() -> Path:
    return resource_root()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="AutomationBienMuc")
    parser.add_argument("--slot", type=int, choices=(1, 2), default=None)
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="Kiểm tra resource/dependency/runtime mà không mở UI hoặc website.",
    )
    parser.add_argument(
        "--browser-smoke",
        action="store_true",
        help="Khởi động Chromium đóng gói với profile tạm rồi đóng lại.",
    )
    parser.add_argument("--json", action="store_true", help="Xuất self-check ở dạng JSON.")
    parser.add_argument("--report", type=Path, default=None, help="Ghi self-check JSON ra file.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = find_project_root()
    settings = load_settings(root, slot_id=args.slot)

    if args.self_check or args.browser_smoke:
        if args.browser_smoke:
            from cataloging_tool.release_check import run_browser_smoke

            report = run_browser_smoke(settings)
        else:
            from cataloging_tool.release_check import run_self_check

            report = run_self_check(settings)

        payload = json.dumps(report, ensure_ascii=False, indent=2)
        if args.report is not None:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(payload + "\n", encoding="utf-8")
        if sys.stdout is not None:
            if args.json:
                print(payload)
            else:
                for key, value in report.items():
                    print(f"{key}={value}")
        return 0 if report["ok"] else 3

    try:
        from cataloging_tool.ui.main_window import run_ui
    except ImportError as exc:
        if sys.stderr is not None:
            print(
                f"{settings.name} {settings.version}\n"
                "Không nạp được giao diện PySide6 trong bản chạy hiện tại.\n"
                f"Chi tiết: {exc}",
                file=sys.stderr,
            )
        return 2
    return run_ui(settings)


if __name__ == "__main__":
    raise SystemExit(main())
