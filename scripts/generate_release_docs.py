from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import platform
import tomllib
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--setup", type=Path, required=True)
    parser.add_argument("--portable", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    release = root / "release"
    release.mkdir(parents=True, exist_ok=True)
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    version = str(data["project"]["version"])
    built = dt.datetime.now().astimezone().isoformat(timespec="seconds")

    sums = [
        f"{sha256(args.setup)}  {args.setup.name}",
        f"{sha256(args.portable)}  {args.portable.name}",
    ]
    (release / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")

    (release / "RELEASE_NOTES.md").write_text(f"""# Automation biên mục tài liệu {version}

- Build date: {built}
- Platform: Windows x64
- Packaging: PyInstaller onedir + Inno Setup
- Chrome: uses installed Google Chrome
- OCR: bundled PaddleOCR models and bundled Tesseract `vie` + `eng`
- Slot 1 and Slot 2 use isolated runtime state and machine-level locks.

## Major fixes in this release

- PDF-backed Unknown records continue through OCR.
- Author is recovered from PDF header evidence; no default Bình Tiên fallback.
- Record-specific production overrides were removed.
- Report/Công văn/Nghị quyết parsing regressions are protected by tests.
- Paddle empty OCR results no longer reset the model.
- Date dropdowns are written sequentially and verified.
- Signer/security extraction is evidence-gated.
- Resume includes `submission_uncertain` reconciliation.
- Slot 1/2 runtime and profile locks are isolated.
- Structured stage logging and diagnostic manifests are enabled.

## System requirements

- Windows 10/11 x64
- Google Chrome installed
- Sufficient local disk space for OCR/runtime cache

## Known issues

- Authentication is stored in the dedicated automation Chrome profile; a personal Chrome session is not shared automatically.
- Runtime caches can grow with large document batches and should be managed using the application retention policy.
""", encoding="utf-8")

    (release / "INSTALL.md").write_text(f"""# Install {version}

1. Run `{args.setup.name}` as an administrator.
2. Keep the default installation directory unless your IT policy requires another location.
3. Launch **Automation biên mục tài liệu - Slot 1** from the Start Menu.
4. Sign in to the archive website in the automation Chrome profile when required.
5. Use Slot 2 only for a different dossier; the application prevents both slots from processing the same dossier.

Writable user data is stored under `%LOCALAPPDATA%\\KhoLuuTruAutomation` and is not stored in Program Files.
""", encoding="utf-8")

    (release / "UNINSTALL.md").write_text("""# Uninstall

Use **Apps > Installed apps > Automation biên mục tài liệu > Uninstall**.

Uninstall removes application binaries and shortcuts. It intentionally preserves user runtime data, configuration, job database, logs and Chrome profiles under LocalAppData so an upgrade/reinstall does not lose state.

To remove user data permanently, delete `%LOCALAPPDATA%\\KhoLuuTruAutomation` and any legacy automation Chrome profile only after confirming no recovery data is required.
""", encoding="utf-8")

    (release / "CHANGELOG.md").write_text(f"""# Changelog

## {version}

Release hardening and Windows installer milestone.

- Removed unsafe author fallback and record-specific overrides.
- Hardened OCR engine lifecycle and metadata reconciliation.
- Added field-level persistence/resume improvements.
- Added Slot 1/2 isolation and cross-process locks.
- Added rotating structured logs and diagnostic artifacts.
- Normalized OpenCV dependency and passed production Pyright checks.
- Added installed-mode LocalAppData paths and offline OCR release resources.
""", encoding="utf-8")

    print(f"Release docs generated for {version} on {platform.platform()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
