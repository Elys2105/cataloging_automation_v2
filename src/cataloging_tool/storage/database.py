from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA_VERSION = 2


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Yield a database connection and always close it on scope exit.

        sqlite3.Connection's own context-manager protocol only commits or
        rolls back; it does not close the connection.  Using this wrapper for
        read-only scopes prevents leaked SQLite/WAL handles on Windows.
        """
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_info (
                    version INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS jobs (
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

                CREATE TABLE IF NOT EXISTS document_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
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
                    document_date TEXT NOT NULL DEFAULT '',
                    author TEXT NOT NULL DEFAULT '',
                    signer_name TEXT NOT NULL DEFAULT '',
                    security_level TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL DEFAULT 0,
                    field_confidence_json TEXT NOT NULL DEFAULT '{}',
                    field_source_json TEXT NOT NULL DEFAULT '{}',
                    pdf_path TEXT NOT NULL DEFAULT '',
                    ocr_path TEXT NOT NULL DEFAULT '',
                    artifact_path TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    completed_at TEXT,
                    UNIQUE(job_id, external_id)
                );

                CREATE TABLE IF NOT EXISTS processing_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id INTEGER NOT NULL REFERENCES document_records(id) ON DELETE CASCADE,
                    attempt_number INTEGER NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    step TEXT NOT NULL DEFAULT '',
                    error_type TEXT NOT NULL DEFAULT '',
                    error_message TEXT NOT NULL DEFAULT '',
                    artifact_path TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS manual_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id INTEGER NOT NULL REFERENCES document_records(id) ON DELETE CASCADE,
                    original_json TEXT NOT NULL,
                    corrected_json TEXT NOT NULL,
                    reviewed_at TEXT NOT NULL,
                    review_note TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS ix_records_job_status
                ON document_records(job_id, status, position);

                CREATE INDEX IF NOT EXISTS ix_attempts_record
                ON processing_attempts(record_id, attempt_number);
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(document_records)").fetchall()
            }
            additions = {
                "document_date": "TEXT NOT NULL DEFAULT ''",
                "author": "TEXT NOT NULL DEFAULT ''",
                "signer_name": "TEXT NOT NULL DEFAULT ''",
                "security_level": "TEXT NOT NULL DEFAULT ''",
                "field_confidence_json": "TEXT NOT NULL DEFAULT '{}'",
                "field_source_json": "TEXT NOT NULL DEFAULT '{}'",
            }
            for name, definition in additions.items():
                if name not in columns:
                    connection.execute(
                        f"ALTER TABLE document_records ADD COLUMN {name} {definition}"
                    )

            count = connection.execute("SELECT COUNT(*) FROM schema_info").fetchone()[0]
            if count == 0:
                connection.execute("INSERT INTO schema_info(version) VALUES (?)", (SCHEMA_VERSION,))
            else:
                connection.execute("UPDATE schema_info SET version = ?", (SCHEMA_VERSION,))
