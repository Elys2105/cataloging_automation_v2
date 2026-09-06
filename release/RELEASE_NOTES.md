# Automation biên mục tài liệu 0.1.27.4.19

- Build date: 2026-08-24T03:41:29+07:00
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
