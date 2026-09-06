from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime

from cataloging_tool.domain.enums import JobMode, JobStatus, RecordStatus
from cataloging_tool.domain.models import DocumentListItem, DocumentRecord, Job

from .database import Database


def _now() -> str:
    return datetime.now(UTC).isoformat()


class JobRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(self, job: Job) -> Job:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO jobs(profile_query, mode, target_document, status, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (job.profile_query, job.mode.value, job.target_document, job.status.value, job.created_at),
            )
            inserted_id = cursor.lastrowid
            if inserted_id is None:
                raise RuntimeError("SQLite không trả về id cho job vừa tạo")
            return replace(job, id=int(inserted_id))

    def set_status(self, job_id: int, status: JobStatus) -> None:
        started_at = _now() if status == JobStatus.RUNNING else None
        finished_at = _now() if status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED} else None
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET status = ?,
                    started_at = COALESCE(started_at, ?),
                    finished_at = COALESCE(?, finished_at)
                WHERE id = ?
                """,
                (status.value, started_at, finished_at, job_id),
            )

    def find_resumable(self) -> list[Job]:
        actionable_statuses = (
            RecordStatus.PENDING.value,
            RecordStatus.FAILED.value,
            RecordStatus.CANCELLED.value,
            RecordStatus.SUBMISSION_UNCERTAIN.value,
            RecordStatus.NEEDS_REVIEW.value,
        )
        placeholders = ",".join("?" for _ in actionable_statuses)
        query = f"""
            SELECT DISTINCT jobs.*
            FROM jobs
            LEFT JOIN document_records
                ON document_records.job_id = jobs.id
            WHERE jobs.status IN (?, ?)
               OR (
                    jobs.status = ?
                    AND document_records.status IN ({placeholders})
               )
            ORDER BY jobs.id DESC
        """
        with self.database.connection() as connection:
            rows = connection.execute(
                query,
                (
                    JobStatus.RUNNING.value,
                    JobStatus.PAUSED.value,
                    JobStatus.COMPLETED.value,
                    *actionable_statuses,
                ),
            ).fetchall()
        return [
            Job(
                id=row["id"],
                profile_query=row["profile_query"],
                mode=JobMode(row["mode"]),
                status=JobStatus(row["status"]),
                target_document=row["target_document"],
                created_at=row["created_at"],
                started_at=row["started_at"],
                finished_at=row["finished_at"],
            )
            for row in rows
        ]

    def refresh_counts(self, job_id: int) -> None:
        with self.database.transaction() as connection:
            total = connection.execute(
                "SELECT COUNT(*) FROM document_records WHERE job_id = ?", (job_id,)
            ).fetchone()[0]
            completed = connection.execute(
                "SELECT COUNT(*) FROM document_records WHERE job_id = ? AND status = ?",
                (job_id, RecordStatus.COMPLETED.value),
            ).fetchone()[0]
            failed = connection.execute(
                "SELECT COUNT(*) FROM document_records WHERE job_id = ? AND status = ?",
                (job_id, RecordStatus.FAILED.value),
            ).fetchone()[0]
            review = connection.execute(
                "SELECT COUNT(*) FROM document_records WHERE job_id = ? AND status = ?",
                (job_id, RecordStatus.NEEDS_REVIEW.value),
            ).fetchone()[0]
            connection.execute(
                """
                UPDATE jobs SET total_records=?, completed_records=?, failed_records=?, review_records=?
                WHERE id=?
                """,
                (total, completed, failed, review, job_id),
            )


class DocumentRecordRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert_inventory(self, job_id: int, items: list[DocumentListItem]) -> None:
        with self.database.transaction() as connection:
            for item in items:
                current_status = (item.current_status_text or "").strip().casefold()
                initial_status = (
                    RecordStatus.COMPLETED.value
                    if current_status == "Hoàn thành".casefold()
                    else RecordStatus.PENDING.value
                )
                connection.execute(
                    """
                    INSERT INTO document_records(
                        job_id, external_id, edit_url, row_text, position, page_number, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(job_id, external_id) DO UPDATE SET
                        edit_url=excluded.edit_url,
                        row_text=excluded.row_text,
                        position=excluded.position,
                        page_number=excluded.page_number,
                        status=CASE
                            WHEN excluded.status = 'completed' THEN 'completed'
                            ELSE document_records.status
                        END,
                        completed_at=CASE
                            WHEN excluded.status = 'completed'
                                THEN COALESCE(document_records.completed_at, CURRENT_TIMESTAMP)
                            ELSE document_records.completed_at
                        END,
                        updated_at=CURRENT_TIMESTAMP
                    """,
                    (
                        job_id,
                        item.external_id,
                        item.edit_url,
                        item.row_text,
                        item.position,
                        item.page_number,
                        initial_status,
                    ),
                )

    def prepare_full_rerun(self, job_id: int) -> None:
        """Reset every inventory row so a new Run All truly reprocesses 1..N."""
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE document_records
                SET status=?,
                    attempt_count=0,
                    last_step='full_rerun',
                    last_error='',
                    document_number='',
                    symbol='',
                    document_type='',
                    abstract='',
                    document_date='',
                    author='',
                    signer_name='',
                    security_level='',
                    confidence=0,
                    field_confidence_json='{}',
                    field_source_json='{}',
                    pdf_path='',
                    ocr_path='',
                    artifact_path='',
                    completed_at=NULL,
                    updated_at=CURRENT_TIMESTAMP
                WHERE job_id=?
                """,
                (RecordStatus.PENDING.value, job_id),
            )

    def list_all(self, job_id: int, start_position: int = 0) -> list[DocumentRecord]:
        """Return the complete inventory in website order, including completed rows."""
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM document_records
                WHERE job_id = ? AND position >= ?
                ORDER BY position
                """,
                (job_id, start_position),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def list_actionable(self, job_id: int, start_position: int = 0) -> list[DocumentRecord]:
        statuses = (
            RecordStatus.PENDING.value,
            RecordStatus.FAILED.value,
            RecordStatus.CANCELLED.value,
            RecordStatus.SUBMISSION_UNCERTAIN.value,
            # A reviewed hotfix must be able to retry only the red rows without
            # forcing "Chạy toàn bộ" and reprocessing records already completed.
            RecordStatus.NEEDS_REVIEW.value,
        )
        placeholders = ",".join("?" for _ in statuses)
        query = f"""
            SELECT * FROM document_records
            WHERE job_id = ? AND position >= ? AND status IN ({placeholders})
            ORDER BY position
        """
        with self.database.connection() as connection:
            rows = connection.execute(query, (job_id, start_position, *statuses)).fetchall()
        return [self._from_row(row) for row in rows]

    def find_by_target(self, job_id: int, target: str) -> list[DocumentRecord]:
        like = f"%{target}%"
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM document_records
                WHERE job_id = ? AND (row_text LIKE ? OR edit_url LIKE ?)
                ORDER BY position
                """,
                (job_id, like, like),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def update_status(
        self,
        record_id: int,
        status: RecordStatus,
        *,
        step: str = "",
        error: str = "",
    ) -> None:
        completed_at = _now() if status == RecordStatus.COMPLETED else None
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE document_records
                SET status=?, last_step=?, last_error=?, updated_at=CURRENT_TIMESTAMP,
                    completed_at=COALESCE(?, completed_at)
                WHERE id=?
                """,
                (status.value, step, error, completed_at, record_id),
            )

    def increment_attempt(self, record_id: int) -> int:
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE document_records SET attempt_count=attempt_count+1 WHERE id=?", (record_id,)
            )
            return int(
                connection.execute(
                    "SELECT attempt_count FROM document_records WHERE id=?", (record_id,)
                ).fetchone()[0]
            )

    def save_result(
        self,
        record_id: int,
        *,
        document_number: str,
        symbol: str,
        document_type: str,
        abstract: str,
        document_date: str,
        author: str,
        signer_name: str,
        security_level: str,
        confidence: float,
        field_confidence: dict[str, float],
        field_sources: dict[str, str],
        pdf_path: str,
        ocr_path: str,
        artifact_path: str,
    ) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE document_records SET
                    document_number=?, symbol=?, document_type=?, abstract=?,
                    document_date=?, author=?, signer_name=?, security_level=?,
                    confidence=?, field_confidence_json=?, field_source_json=?,
                    pdf_path=?, ocr_path=?, artifact_path=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    document_number,
                    symbol,
                    document_type,
                    abstract,
                    document_date,
                    author,
                    signer_name,
                    security_level,
                    confidence,
                    json.dumps(field_confidence, ensure_ascii=False, sort_keys=True),
                    json.dumps(field_sources, ensure_ascii=False, sort_keys=True),
                    pdf_path,
                    ocr_path,
                    artifact_path,
                    record_id,
                ),
            )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> DocumentRecord:
        return DocumentRecord(
            id=row["id"],
            job_id=row["job_id"],
            external_id=row["external_id"],
            edit_url=row["edit_url"],
            row_text=row["row_text"],
            position=row["position"],
            page_number=row["page_number"],
            status=RecordStatus(row["status"]),
            attempt_count=row["attempt_count"],
            last_step=row["last_step"],
            last_error=row["last_error"],
            document_number=row["document_number"],
            symbol=row["symbol"],
            document_type=row["document_type"],
            abstract=row["abstract"],
            document_date=row["document_date"],
            author=row["author"],
            signer_name=row["signer_name"],
            security_level=row["security_level"],
            confidence=row["confidence"],
            field_confidence=json.loads(row["field_confidence_json"] or "{}"),
            field_sources=json.loads(row["field_source_json"] or "{}"),
            pdf_path=row["pdf_path"],
            ocr_path=row["ocr_path"],
            artifact_path=row["artifact_path"],
        )
