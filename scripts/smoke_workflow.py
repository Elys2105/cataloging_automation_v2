from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace

from cataloging_tool.diagnostics.artifacts import ArtifactManager
from cataloging_tool.document.parser import DocumentParser
from cataloging_tool.document.validator import DocumentValidator
from cataloging_tool.domain.enums import DataSource, JobMode, RecordStatus
from cataloging_tool.domain.models import DocumentListItem, FormSnapshot
from cataloging_tool.storage.database import Database
from cataloging_tool.storage.repositories import DocumentRecordRepository, JobRepository
from cataloging_tool.workflow.runner import WorkflowRunner


class FakePage:
    url = "https://example.test/DocumentCataloging/ListDocument"

    async def screenshot(self, **kwargs):
        Path(kwargs["path"]).write_bytes(b"fake")

    async def content(self):
        return "<html></html>"


class FakeBrowser:
    def __init__(self):
        self.page = FakePage()

    async def open_base_page(self):
        return self.page


class FakeProfilePage:
    pass


class FakeTextExtractor:
    def extract(self, path, record_key):
        return SimpleNamespace(
            text="Số 27-KH/ĐU\nKẾ HOẠCH\nsắp xếp cán bộ, công chức, viên chức, người hoạt động không chuyên trách",
            source=DataSource.PDF_TEXT,
            confidence=0.98,
            ocr_text_path=None,
        )


class FakePdfAcquirer:
    async def acquire(self, page, record_key):
        return SimpleNamespace(path=Path(__file__), source="test")


async def main_async() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        database = Database(root / "workflow.sqlite3")
        database.initialize()
        jobs = JobRepository(database)
        records = DocumentRecordRepository(database)
        job = jobs.create(__import__("cataloging_tool.domain.models", fromlist=["Job"]).Job(id=None, profile_query="HS", mode=JobMode.ALL))
        records.upsert_inventory(job.id, [DocumentListItem("27", "https://x/UpdateDoc?id=27", "27 KH/ĐU", 1)])

        parser = DocumentParser(Path(__file__).resolve().parents[1] / "rules", "Tác giả", "Thường")
        runner = WorkflowRunner(
            browser_session=FakeBrowser(),
            pdf_acquirer=FakePdfAcquirer(),
            text_extractor=FakeTextExtractor(),
            parser=parser,
            validator=DocumentValidator(0.82),
            jobs=jobs,
            records=records,
            artifacts=ArtifactManager(root / "artifacts"),
            dry_run=True,
        )
        # Exercise processing core without live Page Objects by replacing the method boundary.
        async def fake_process_one(job_id, record, page, artifact_dir, position, total):
            parsed = parser.parse(
                FakeTextExtractor().extract(None, "27").text,
                source=DataSource.PDF_TEXT,
                source_confidence=0.98,
                existing_form=FormSnapshot(),
            )
            runner.validator.validate(parsed)
            records.save_result(
                record.id,
                document_number=parsed.document_number.value,
                symbol=parsed.symbol.value,
                document_type=parsed.document_type.value,
                abstract=parsed.abstract.value,
                confidence=parsed.overall_confidence,
                pdf_path="test.pdf",
                ocr_path="",
                artifact_path=str(artifact_dir),
            )
            records.update_status(record.id, RecordStatus.READY_TO_SUBMIT, step="dry_run")

        runner._process_one = fake_process_one
        record = records.list_actionable(job.id)[0]
        await runner._process_with_retry(job.id, record, FakePage(), 1, 1)
        assert records.find_by_target(job.id, "27")[0].status == RecordStatus.READY_TO_SUBMIT
    print("Workflow smoke test: OK")


if __name__ == "__main__":
    asyncio.run(main_async())
