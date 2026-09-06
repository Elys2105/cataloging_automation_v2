from __future__ import annotations

import asyncio

from cataloging_tool.domain.enums import JobMode, JobStatus, RecordStatus
from cataloging_tool.domain.models import DocumentListItem, DocumentRecord, Job
from cataloging_tool.workflow.runner import WorkflowRunner


class _Records:
    def __init__(self) -> None:
        self.prepared = False
        self.rows = [
            DocumentRecord(
                id=1, job_id=7, external_id="1", edit_url="https://x/1",
                row_text="1 Hoàn thành", position=1, page_number=1,
                status=RecordStatus.COMPLETED,
            ),
            DocumentRecord(
                id=2, job_id=7, external_id="2", edit_url="https://x/2",
                row_text="2 Chưa hoàn thành", position=2, page_number=1,
                status=RecordStatus.PENDING,
            ),
        ]

    def prepare_full_rerun(self, _job_id: int) -> None:
        self.prepared = True
        for row in self.rows:
            row.status = RecordStatus.PENDING
            row.attempt_count = 0

    def list_all(self, _job_id: int):
        return self.rows

    def list_actionable(self, _job_id: int, start_position: int = 0):
        return [row for row in self.rows if row.position >= start_position and row.status != RecordStatus.COMPLETED]

    def find_by_target(self, _job_id: int, _target: str):
        return []


class _Jobs:
    def __init__(self) -> None:
        self.statuses = []

    def refresh_counts(self, _job_id: int) -> None:
        return None

    def set_status(self, _job_id: int, status: JobStatus) -> None:
        self.statuses.append(status)


def _runner(records: _Records, jobs: _Jobs) -> WorkflowRunner:
    return WorkflowRunner(
        browser_session=None,
        pdf_acquirer=None,
        text_extractor=None,  # type: ignore[arg-type]
        parser=None,  # type: ignore[arg-type]
        validator=None,  # type: ignore[arg-type]
        jobs=jobs,  # type: ignore[arg-type]
        records=records,  # type: ignore[arg-type]
        artifacts=None,  # type: ignore[arg-type]
        auto_complete=False,
        dry_run=False,
    )


def test_new_run_all_reprocesses_completed_and_pending_in_order() -> None:
    records = _Records()
    jobs = _Jobs()
    runner = _runner(records, jobs)
    visited = []

    async def fake_process(_job_id, record, _page, position, total):
        visited.append((record.external_id, position, total))

    runner._process_with_retry = fake_process  # type: ignore[method-assign]
    job = Job(id=7, profile_query="HS", mode=JobMode.ALL)

    asyncio.run(
        runner._run_inventory(
            job, object(), list_url="https://x/list", force_reprocess_all=True
        )
    )

    assert records.prepared is True
    assert visited == [("1", 1, 2), ("2", 2, 2)]


def test_resume_does_not_restart_completed_rows() -> None:
    records = _Records()
    jobs = _Jobs()
    runner = _runner(records, jobs)
    visited = []

    async def fake_process(_job_id, record, _page, position, total):
        visited.append(record.external_id)

    runner._process_with_retry = fake_process  # type: ignore[method-assign]
    job = Job(id=7, profile_query="HS", mode=JobMode.ALL)

    asyncio.run(
        runner._run_inventory(
            job, object(), list_url="https://x/list", force_reprocess_all=False
        )
    )

    assert records.prepared is False
    assert visited == ["2"]


def test_resume_refreshes_website_inventory_before_selecting_actionable_rows(monkeypatch) -> None:
    import cataloging_tool.workflow.runner as runner_module

    page = type("Page", (), {"url": "https://x/ListDocument"})()

    class Browser:
        async def open_base_page(self):
            return page

    class ProfilePage:
        def __init__(self, _page):
            pass

        async def search_and_open(self, query):
            assert query == "HS"

    inventory = [
        DocumentListItem(
            "1",
            "https://x/UpdateDoc?id=1",
            "1 Hoàn thành",
            1,
            current_status_text="Hoàn thành",
        )
    ]

    class ListPage:
        def __init__(self, _page):
            pass

        async def inventory_all(self):
            return inventory

    class Records:
        def __init__(self):
            self.refreshed = None

        def upsert_inventory(self, job_id, items):
            self.refreshed = (job_id, list(items))

    class Jobs:
        def __init__(self):
            self.statuses = []
            self.refreshed = []

        def set_status(self, job_id, status):
            self.statuses.append((job_id, status))

        def refresh_counts(self, job_id):
            self.refreshed.append(job_id)

    monkeypatch.setattr(runner_module, "ProfileListPage", ProfilePage)
    monkeypatch.setattr(runner_module, "DocumentListPage", ListPage)

    records = Records()
    jobs = Jobs()
    runner = WorkflowRunner(
        browser_session=Browser(),
        pdf_acquirer=None,
        text_extractor=None,  # type: ignore[arg-type]
        parser=None,  # type: ignore[arg-type]
        validator=None,  # type: ignore[arg-type]
        jobs=jobs,  # type: ignore[arg-type]
        records=records,  # type: ignore[arg-type]
        artifacts=None,  # type: ignore[arg-type]
        auto_complete=False,
    )

    seen = {}

    async def fake_run_inventory(job, got_page, *, list_url, force_reprocess_all):
        seen["job"] = job
        seen["page"] = got_page
        seen["list_url"] = list_url
        seen["force"] = force_reprocess_all
        return job

    runner._run_inventory = fake_run_inventory  # type: ignore[method-assign]
    job = Job(id=7, profile_query="HS", mode=JobMode.RESUME)

    result = asyncio.run(runner.resume(job))

    assert result is job
    assert records.refreshed == (7, inventory)
    assert jobs.refreshed == [7]
    assert seen["page"] is page
    assert seen["list_url"] == "https://x/ListDocument"
    assert seen["force"] is False
