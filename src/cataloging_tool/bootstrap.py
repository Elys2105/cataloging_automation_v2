from __future__ import annotations

from cataloging_tool.automation.browser import BrowserSession
from cataloging_tool.automation.pdf_detector import PdfAcquirer
from cataloging_tool.config.settings import AppSettings
from cataloging_tool.diagnostics.artifacts import ArtifactManager
from cataloging_tool.diagnostics.logging_config import configure_logging
from cataloging_tool.document.ocr import PaddleOcrEngine
from cataloging_tool.document.parser import DocumentParser
from cataloging_tool.document.pdf_pipeline import PdfPipeline
from cataloging_tool.document.text_extractor import DocumentTextExtractor
from cataloging_tool.document.validator import DocumentValidator
from cataloging_tool.storage.database import Database
from cataloging_tool.storage.repositories import DocumentRecordRepository, JobRepository
from cataloging_tool.runtime_lock import SlotLockService
from cataloging_tool.workflow.events import WorkflowEventSink
from cataloging_tool.workflow.runner import WorkflowRunner


def build_runner(settings: AppSettings, event_sink: WorkflowEventSink | None = None) -> WorkflowRunner:
    configure_logging(settings.paths.logs)
    database = Database(settings.paths.database)
    database.initialize()
    jobs = JobRepository(database)
    records = DocumentRecordRepository(database)
    slot_locks = SlotLockService(settings.paths.lock_root, settings.slot_id)

    browser = BrowserSession(
        settings=settings.browser,
        profile_dir=settings.browser.profile_dir,
        downloads_dir=settings.paths.downloads,
        trace_dir=settings.paths.artifacts / "traces",
        slot_locks=slot_locks,
    )
    acquirer = PdfAcquirer(
        settings.paths.pdf_cache,
        collector=browser.pdf_collector,
        fast_viewer_fallback=settings.pdf.fast_viewer_fallback,
        viewer_ready_timeout_ms=settings.pdf.viewer_ready_timeout_ms,
    )
    pdf_pipeline = PdfPipeline(
        settings.paths.rendered,
        render_dpi=settings.pdf.render_dpi,
        minimum_text_length=settings.pdf.minimum_text_length,
    )
    ocr = PaddleOcrEngine(settings.ocr)
    extractor = DocumentTextExtractor(
        pdf_pipeline,
        ocr,
        settings.paths.ocr,
        reuse_ocr_cache=settings.ocr.reuse_ocr_cache,
        direct_viewer_image=settings.pdf.direct_viewer_image,
    )
    parser = DocumentParser(
        settings.paths.root / "rules",
        author=settings.defaults.author,
        security_level=settings.defaults.security_level,
    )
    validator = DocumentValidator(settings.ocr.minimum_confidence, require_author=True)
    return WorkflowRunner(
        browser_session=browser,
        pdf_acquirer=acquirer,
        text_extractor=extractor,
        parser=parser,
        validator=validator,
        jobs=jobs,
        records=records,
        artifacts=ArtifactManager(settings.paths.artifacts),
        max_attempts=settings.workflow.max_attempts,
        continue_after_error=settings.workflow.continue_after_record_error,
        auto_complete=settings.workflow.auto_complete,
        dry_run=settings.workflow.dry_run,
        event_sink=event_sink,
        slot_locks=slot_locks,
        slot_id=settings.slot_id,
    )
