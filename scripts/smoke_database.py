from __future__ import annotations

import tempfile
from pathlib import Path

from cataloging_tool.domain.enums import JobMode
from cataloging_tool.domain.models import DocumentListItem, Job
from cataloging_tool.storage.database import Database
from cataloging_tool.storage.repositories import DocumentRecordRepository, JobRepository


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "smoke.sqlite3")
        database.initialize()
        jobs = JobRepository(database)
        records = DocumentRecordRepository(database)
        job = jobs.create(Job(id=None, profile_query="HS-001", mode=JobMode.ALL))
        assert job.id is not None
        records.upsert_inventory(
            job.id,
            [
                DocumentListItem(
                    external_id="doc-1",
                    edit_url="https://example.test/UpdateDoc?id=1",
                    row_text="27 KH/ĐU",
                    position=1,
                )
            ],
        )
        actionable = records.list_actionable(job.id)
        assert len(actionable) == 1
        assert actionable[0].external_id == "doc-1"
        jobs.refresh_counts(job.id)
    print("Database smoke test: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
