from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from cataloging_tool.diagnostics.artifacts import ArtifactManager
from cataloging_tool.domain.models import FormSnapshot, ParsedDocument


def test_diagnostic_manifest_contains_pdf_checksum_and_evidence(tmp_path):
    manager = ArtifactManager(tmp_path / "artifacts")
    attempt = manager.attempt_dir(1, 2, 1)
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"sample-pdf")
    extracted = SimpleNamespace(
        source="paddle_ocr", confidence=0.8, header_evidence_text="HEADER",
        author_evidence_text="AUTHOR", signature_evidence_text="SIGNER", special_report_title="TITLE"
    )
    path = manager.write_diagnostic_manifest(
        attempt, source_pdf=pdf, ocr_path=tmp_path / "ocr.txt",
        existing_form=FormSnapshot(author="OLD"), parsed=ParsedDocument(author="NEW"),
        extracted=extracted, final_status="needs_review",
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["source_pdf"]["sha256"] == manager.sha256_file(pdf)
    assert payload["evidence"]["header"] == "HEADER"
    assert payload["existing_form"]["author"] == "OLD"
    assert payload["final_reconciliation"]["author"] == "NEW"
    assert payload["final_status"] == "needs_review"


def test_completed_attempt_prunes_only_heavy_browser_dump(tmp_path):
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    (attempt / "screenshot.png").write_bytes(b"png")
    (attempt / "page.html").write_text("html", encoding="utf-8")
    (attempt / "diagnostic.json").write_text("{}", encoding="utf-8")
    ArtifactManager.prune_completed_attempt(attempt)
    assert not (attempt / "screenshot.png").exists()
    assert not (attempt / "page.html").exists()
    assert (attempt / "diagnostic.json").exists()
