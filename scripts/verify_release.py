from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import yaml


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    source_files = list((root / "src").rglob("*.py"))
    source = "\n".join(path.read_text(encoding="utf-8") for path in source_files)
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    default = yaml.safe_load((root / "config" / "default.yaml").read_text(encoding="utf-8")) or {}
    overrides = yaml.safe_load((root / "rules" / "known_overrides.yaml").read_text(encoding="utf-8")) or []
    checks = {
        "no_selenium_in_new_source": "selenium" not in source.casefold(),
        "no_time_sleep_for_web": "time.sleep(" not in source,
        "no_bare_except_pass": not bool(re.search(r"except\s*:\s*pass", source)),
        "config_exists": (root / "config" / "default.yaml").exists(),
        "rules_exist": (root / "rules" / "document_types.yaml").exists(),
        "spec_exists": (root / "build" / "CatalogingAutomation.spec").exists(),
        "version_single_source": str(pyproject["project"]["version"]) == str(default["application"]["version"]),
        "record_overrides_empty": overrides == [],
        "installer_source_exists": (root / "installer" / "AutomationBienMuc.iss").exists(),
        "runtime_hook_exists": (root / "build" / "runtime_hook.py").exists(),
        "release_resource_stager_exists": (root / "scripts" / "stage_release_resources.py").exists(),
        "installed_mode_support_exists": (root / "src" / "cataloging_tool" / "config" / "deployment.py").exists(),
    }
    pytest = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(root / "tests")],
        cwd=root,
        env={**__import__("os").environ, "PYTHONPATH": str(root / "src"), "PYTHONNOUSERSITE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    checks["tests_pass"] = pytest.returncode == 0
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    print(pytest.stdout)
    if pytest.stderr:
        print(pytest.stderr, file=sys.stderr)
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
