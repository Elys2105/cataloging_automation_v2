from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from .enums import DataSource, JobMode, JobStatus, RecordStatus, Severity


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class ValidationIssue:
    code: str
    message: str
    severity: Severity = Severity.WARNING
    field: str | None = None


@dataclass(slots=True)
class OcrLine:
    text: str
    confidence: float
    box: list[list[float]] | None = None


@dataclass(slots=True)
class OcrResult:
    raw_text: str
    confidence: float
    lines: list[OcrLine] = field(default_factory=list)
    engine: str = "unknown"
    duration_ms: int = 0


@dataclass(slots=True)
class ParsedField:
    value: str = ""
    confidence: float = 0.0
    source_text: str = ""


@dataclass(slots=True)
class ParsedDocument:
    document_number: ParsedField = field(default_factory=ParsedField)
    symbol: ParsedField = field(default_factory=ParsedField)
    document_type: ParsedField = field(default_factory=ParsedField)
    abstract: ParsedField = field(default_factory=ParsedField)
    document_date: ParsedField = field(default_factory=ParsedField)
    signer_name: ParsedField = field(default_factory=ParsedField)
    author: str = ""
    author_confidence: float = 0.0
    author_source_text: str = ""
    security_level: str = "Thường"
    security_confidence: float = 0.0
    security_source_text: str = ""
    source: DataSource = DataSource.UNKNOWN
    overall_confidence: float = 0.0
    issues: list[ValidationIssue] = field(default_factory=list)
    raw_text: str = ""

    def confidence_map(self) -> dict[str, float]:
        return {
            "document_number": float(self.document_number.confidence),
            "symbol": float(self.symbol.confidence),
            "document_type": float(self.document_type.confidence),
            "abstract": float(self.abstract.confidence),
            "document_date": float(self.document_date.confidence),
            "author": float(self.author_confidence),
            "signer_name": float(self.signer_name.confidence),
            "security_level": float(self.security_confidence),
        }

    def source_map(self) -> dict[str, str]:
        return {
            "document_number": self.document_number.source_text,
            "symbol": self.symbol.source_text,
            "document_type": self.document_type.source_text,
            "abstract": self.abstract.source_text,
            "document_date": self.document_date.source_text,
            "author": self.author_source_text,
            "signer_name": self.signer_name.source_text,
            "security_level": self.security_source_text,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["field_confidence"] = self.confidence_map()
        payload["field_sources"] = self.source_map()
        return payload


@dataclass(slots=True)
class DocumentListItem:
    external_id: str
    edit_url: str
    row_text: str
    position: int
    page_number: int = 1
    current_status_text: str = ""


@dataclass(slots=True)
class FormSnapshot:
    document_number: str = ""
    symbol: str = ""
    document_type: str = ""
    abstract: str = ""
    document_date: str = ""
    author: str = ""
    security_level: str = ""
    signer_name: str = ""


@dataclass(slots=True)
class Job:
    id: int | None
    profile_query: str
    mode: JobMode
    status: JobStatus = JobStatus.CREATED
    target_document: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    started_at: str | None = None
    finished_at: str | None = None


@dataclass(slots=True)
class DocumentRecord:
    id: int | None
    job_id: int
    external_id: str
    edit_url: str
    row_text: str
    position: int
    page_number: int = 1
    status: RecordStatus = RecordStatus.PENDING
    attempt_count: int = 0
    last_step: str = ""
    last_error: str = ""
    document_number: str = ""
    symbol: str = ""
    document_type: str = ""
    abstract: str = ""
    document_date: str = ""
    author: str = ""
    signer_name: str = ""
    security_level: str = ""
    confidence: float = 0.0
    field_confidence: dict[str, float] = field(default_factory=dict)
    field_sources: dict[str, str] = field(default_factory=dict)
    pdf_path: str = ""
    ocr_path: str = ""
    artifact_path: str = ""
