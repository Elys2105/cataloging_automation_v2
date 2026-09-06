from __future__ import annotations

import sys
import tomllib
from pathlib import Path


def read_project_version(root: Path) -> str:
    pyproject = root / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    version = str(data["project"]["version"]).strip()
    if not version:
        raise ValueError("project.version is empty")
    return version


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
    print(read_project_version(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
