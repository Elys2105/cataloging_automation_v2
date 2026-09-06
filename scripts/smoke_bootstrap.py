from __future__ import annotations

from pathlib import Path

from cataloging_tool.bootstrap import build_runner
from cataloging_tool.config.settings import load_settings


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    settings = load_settings(root)
    runner = build_runner(settings)
    assert runner.browser_session is not None
    assert runner.parser is not None
    assert runner.validator is not None
    assert runner.jobs is not None
    print("UI bootstrap smoke test: OK (PySide6 remains optional in this container)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
