from cataloging_tool.domain.enums import JobMode, JobStatus, RecordStatus
from cataloging_tool.domain.models import DocumentListItem, Job
from cataloging_tool.storage.database import Database
from cataloging_tool.storage.repositories import DocumentRecordRepository, JobRepository


def test_job_inventory_and_resume(tmp_path) -> None:
    database = Database(tmp_path / "test.sqlite3")
    database.initialize()
    jobs = JobRepository(database)
    records = DocumentRecordRepository(database)
    job = jobs.create(Job(id=None, profile_query="HS-1", mode=JobMode.ALL))
    jobs.set_status(job.id, JobStatus.RUNNING)
    records.upsert_inventory(
        job.id,
        [DocumentListItem("1", "https://x/UpdateDoc?id=1", "1 KH/ĐU", 1)],
    )
    rows = records.list_actionable(job.id)
    assert len(rows) == 1
    records.update_status(rows[0].id, RecordStatus.COMPLETED)
    assert records.list_actionable(job.id) == []
    assert jobs.find_resumable()[0].id == job.id


def test_inventory_skips_rows_already_completed_on_website(tmp_path) -> None:
    database = Database(tmp_path / "completed.sqlite3")
    database.initialize()
    jobs = JobRepository(database)
    records = DocumentRecordRepository(database)
    job = jobs.create(Job(id=None, profile_query="HS-2", mode=JobMode.ALL))
    records.upsert_inventory(
        job.id,
        [
            DocumentListItem(
                "1",
                "https://x/UpdateDoc?id=1",
                "1 TB/ĐU Hoàn thành",
                1,
                current_status_text="Hoàn thành",
            ),
            DocumentListItem(
                "2",
                "https://x/UpdateDoc?id=2",
                "2 TB/ĐU Chưa hoàn thành",
                2,
                current_status_text="Chưa hoàn thành",
            ),
        ],
    )
    actionable = records.list_actionable(job.id)
    assert [record.external_id for record in actionable] == ["2"]


def test_list_all_keeps_completed_rows_in_website_order(tmp_path) -> None:
    database = Database(tmp_path / "all.sqlite3")
    database.initialize()
    jobs = JobRepository(database)
    records = DocumentRecordRepository(database)
    job = jobs.create(Job(id=None, profile_query="HS-ALL", mode=JobMode.ALL))
    records.upsert_inventory(
        job.id,
        [
            DocumentListItem(
                "1", "https://x/UpdateDoc?id=1", "1 Hoàn thành", 1,
                current_status_text="Hoàn thành",
            ),
            DocumentListItem(
                "2", "https://x/UpdateDoc?id=2", "2 Chưa hoàn thành", 2,
                current_status_text="Chưa hoàn thành",
            ),
        ],
    )
    rows = records.list_all(job.id)
    assert [row.external_id for row in rows] == ["1", "2"]
    assert [row.status for row in rows] == [RecordStatus.COMPLETED, RecordStatus.PENDING]


def test_prepare_full_rerun_resets_every_record(tmp_path) -> None:
    database = Database(tmp_path / "full-rerun.sqlite3")
    database.initialize()
    jobs = JobRepository(database)
    records = DocumentRecordRepository(database)
    job = jobs.create(Job(id=None, profile_query="HS-RERUN", mode=JobMode.ALL))
    records.upsert_inventory(
        job.id,
        [
            DocumentListItem(
                "1", "https://x/UpdateDoc?id=1", "1 Hoàn thành", 1,
                current_status_text="Hoàn thành",
            ),
            DocumentListItem(
                "2", "https://x/UpdateDoc?id=2", "2 Chưa hoàn thành", 2,
                current_status_text="Chưa hoàn thành",
            ),
        ],
    )
    rows = records.list_all(job.id)
    records.increment_attempt(rows[0].id)
    records.update_status(rows[1].id, RecordStatus.FAILED, error="old")

    records.prepare_full_rerun(job.id)

    reset = records.list_all(job.id)
    assert [row.status for row in reset] == [RecordStatus.PENDING, RecordStatus.PENDING]
    assert [row.attempt_count for row in reset] == [0, 0]
    assert [row.last_error for row in reset] == ["", ""]


def test_submission_uncertain_is_actionable_until_website_confirms_completed(tmp_path) -> None:
    database = Database(tmp_path / "uncertain.sqlite3")
    database.initialize()
    jobs = JobRepository(database)
    records = DocumentRecordRepository(database)
    job = jobs.create(Job(id=None, profile_query="HS-U", mode=JobMode.ALL))
    records.upsert_inventory(
        job.id,
        [
            DocumentListItem(
                "1",
                "https://x/UpdateDoc?id=1",
                "1 Chưa hoàn thành",
                1,
                current_status_text="Chưa hoàn thành",
            )
        ],
    )
    row = records.list_all(job.id)[0]
    records.update_status(row.id, RecordStatus.SUBMISSION_UNCERTAIN, step="verify")

    assert records.list_actionable(job.id)[0].status == RecordStatus.SUBMISSION_UNCERTAIN

    # Resume refresh sees the authoritative website state and resolves it.
    records.upsert_inventory(
        job.id,
        [
            DocumentListItem(
                "1",
                "https://x/UpdateDoc?id=1",
                "1 Hoàn thành",
                1,
                current_status_text="Hoàn thành",
            )
        ],
    )
    assert records.list_actionable(job.id) == []
    assert records.list_all(job.id)[0].status == RecordStatus.COMPLETED


def test_database_v1_is_migrated_without_losing_record_state(tmp_path) -> None:
    import sqlite3

    path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE schema_info (version INTEGER NOT NULL);
        INSERT INTO schema_info(version) VALUES (1);
        CREATE TABLE jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_query TEXT NOT NULL,
            mode TEXT NOT NULL,
            target_document TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            total_records INTEGER NOT NULL DEFAULT 0,
            completed_records INTEGER NOT NULL DEFAULT 0,
            failed_records INTEGER NOT NULL DEFAULT 0,
            review_records INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE document_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            external_id TEXT NOT NULL,
            edit_url TEXT NOT NULL,
            row_text TEXT NOT NULL,
            position INTEGER NOT NULL,
            page_number INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_step TEXT NOT NULL DEFAULT '',
            last_error TEXT NOT NULL DEFAULT '',
            document_number TEXT NOT NULL DEFAULT '',
            symbol TEXT NOT NULL DEFAULT '',
            document_type TEXT NOT NULL DEFAULT '',
            abstract TEXT NOT NULL DEFAULT '',
            confidence REAL NOT NULL DEFAULT 0,
            pdf_path TEXT NOT NULL DEFAULT '',
            ocr_path TEXT NOT NULL DEFAULT '',
            artifact_path TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT,
            UNIQUE(job_id, external_id)
        );
        CREATE TABLE processing_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id INTEGER NOT NULL,
            attempt_number INTEGER NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            step TEXT NOT NULL DEFAULT '',
            error_type TEXT NOT NULL DEFAULT '',
            error_message TEXT NOT NULL DEFAULT '',
            artifact_path TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE manual_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id INTEGER NOT NULL,
            original_json TEXT NOT NULL,
            corrected_json TEXT NOT NULL,
            reviewed_at TEXT NOT NULL,
            review_note TEXT NOT NULL DEFAULT ''
        );
        INSERT INTO jobs(profile_query, mode, status, created_at)
        VALUES ('HS-OLD', 'all', 'running', '2026-08-20T00:00:00+00:00');
        INSERT INTO document_records(
            job_id, external_id, edit_url, row_text, position, status,
            document_number, symbol, document_type, abstract, confidence
        ) VALUES (
            1, 'old-1', 'https://x/1', 'old row', 1, 'failed',
            '12', 'CV/ĐU', 'Công văn', 'Về việc cũ', 0.77
        );
        """
    )
    connection.commit()
    connection.close()

    database = Database(path)
    database.initialize()

    with database.connection() as migrated:
        version = migrated.execute("SELECT version FROM schema_info").fetchone()[0]
        columns = {
            row["name"]
            for row in migrated.execute("PRAGMA table_info(document_records)").fetchall()
        }
        row = migrated.execute(
            "SELECT document_number, status, document_date, author, field_confidence_json "
            "FROM document_records WHERE external_id='old-1'"
        ).fetchone()

    assert version == 2
    assert {
        "document_date",
        "author",
        "signer_name",
        "security_level",
        "field_confidence_json",
        "field_source_json",
    }.issubset(columns)
    assert row["document_number"] == "12"
    assert row["status"] == "failed"
    assert row["document_date"] == ""
    assert row["author"] == ""
    assert row["field_confidence_json"] == "{}"


def test_save_result_persists_all_metadata_and_field_evidence(tmp_path) -> None:
    database = Database(tmp_path / "metadata.sqlite3")
    database.initialize()
    jobs = JobRepository(database)
    records = DocumentRecordRepository(database)
    job = jobs.create(Job(id=None, profile_query="HS-M", mode=JobMode.ALL))
    records.upsert_inventory(
        job.id,
        [DocumentListItem("1", "https://x/1", "row", 1)],
    )
    row = records.list_all(job.id)[0]
    records.save_result(
        row.id,
        document_number="12",
        symbol="CV/ĐU",
        document_type="Công văn",
        abstract="Về việc kiểm tra",
        document_date="2026-08-20",
        author="ĐẢNG ỦY PHƯỜNG 1 QUẬN ỦY QUẬN 6",
        signer_name="Nguyễn Văn A",
        security_level="Mật",
        confidence=0.93,
        field_confidence={"author": 0.99, "security_level": 0.995},
        field_sources={"author": "focused-author-header", "security_level": "security-header"},
        pdf_path="a.pdf",
        ocr_path="a.txt",
        artifact_path="artifact",
    )

    saved = records.list_all(job.id)[0]
    assert saved.document_date == "2026-08-20"
    assert saved.author == "ĐẢNG ỦY PHƯỜNG 1 QUẬN ỦY QUẬN 6"
    assert saved.signer_name == "Nguyễn Văn A"
    assert saved.security_level == "Mật"
    assert saved.field_confidence["author"] == 0.99
    assert saved.field_sources["security_level"] == "security-header"


def test_connection_scope_closes_sqlite_handle(tmp_path) -> None:
    import sqlite3

    database = Database(tmp_path / "close.sqlite3")
    database.initialize()
    with database.connection() as connection:
        connection.execute("SELECT 1").fetchone()
        leaked = connection

    try:
        leaked.execute("SELECT 1")
    except sqlite3.ProgrammingError as exc:
        assert "closed" in str(exc).casefold()
    else:
        raise AssertionError("Database.connection() leaked an open sqlite handle")


def test_needs_review_is_actionable_for_resume_without_reprocessing_completed(tmp_path) -> None:
    database = Database(tmp_path / "needs-review-resume.sqlite3")
    database.initialize()
    jobs = JobRepository(database)
    records = DocumentRecordRepository(database)
    job = jobs.create(Job(id=None, profile_query="HS-REVIEW", mode=JobMode.ALL))
    records.upsert_inventory(
        job.id,
        [
            DocumentListItem("1", "https://x/UpdateDoc?id=1", "1", 1),
            DocumentListItem("2", "https://x/UpdateDoc?id=2", "2", 2),
        ],
    )
    rows = records.list_all(job.id)
    records.update_status(rows[0].id, RecordStatus.NEEDS_REVIEW)
    records.update_status(rows[1].id, RecordStatus.COMPLETED)

    actionable = records.list_actionable(job.id)

    assert [record.external_id for record in actionable] == ["1"]


def test_completed_job_with_needs_review_is_resumable(tmp_path) -> None:
    database = Database(tmp_path / "completed-review-resume.sqlite3")
    database.initialize()
    jobs = JobRepository(database)
    records = DocumentRecordRepository(database)
    job = jobs.create(Job(id=None, profile_query="HS-REVIEW-RESUME", mode=JobMode.ALL))
    records.upsert_inventory(
        job.id,
        [DocumentListItem("1", "https://x/UpdateDoc?id=1", "1", 1)],
    )
    row = records.list_all(job.id)[0]
    records.update_status(row.id, RecordStatus.NEEDS_REVIEW)
    jobs.set_status(job.id, JobStatus.COMPLETED)

    resumable = jobs.find_resumable()

    assert resumable
    assert resumable[0].id == job.id
