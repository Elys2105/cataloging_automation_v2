from __future__ import annotations

from enum import StrEnum


class JobMode(StrEnum):
    ALL = "all"
    ONE = "one"
    CONTINUE_FROM = "continue_from"
    RESUME = "resume"


class JobStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RecordStatus(StrEnum):
    PENDING = "pending"
    OPENING = "opening"
    PDF_ACQUIRING = "pdf_acquiring"
    PDF_READING = "pdf_reading"
    OCR_RUNNING = "ocr_running"
    PARSING = "parsing"
    VALIDATING = "validating"
    NEEDS_REVIEW = "needs_review"
    READY_TO_SUBMIT = "ready_to_submit"
    SUBMITTING = "submitting"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    SKIPPED_NO_PDF = "skipped_no_pdf"
    SUBMISSION_UNCERTAIN = "submission_uncertain"


class DataSource(StrEnum):
    PDF_TEXT = "pdf_text"
    PADDLE_OCR = "paddle_ocr"
    TESSERACT_OCR = "tesseract_ocr"
    EXISTING_FORM = "existing_form"
    MANUAL_OVERRIDE = "manual_override"
    UNKNOWN = "unknown"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
