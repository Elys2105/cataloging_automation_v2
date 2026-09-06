from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from cataloging_tool.automation.pages import (
    DocumentEditPage,
    DocumentListPage,
    ProfileListPage,
    form_needs_full_metadata_recovery,
)
from cataloging_tool.diagnostics.artifacts import ArtifactManager
from cataloging_tool.domain.enums import JobMode, JobStatus, RecordStatus, Severity
from cataloging_tool.domain.errors import (
    CatalogingError,
    OperationCancelledError,
    SubmissionUncertainError,
    error_code_for_exception,
)
from cataloging_tool.domain.models import (
    DocumentListItem,
    DocumentRecord,
    Job,
    ParsedDocument,
    ValidationIssue,
)
from cataloging_tool.document.cong_van_sequence import (
    CongVanNumberEvidence,
    CongVanNumberSequence,
)
from cataloging_tool.document.parser import DocumentParser
from cataloging_tool.document.text_extractor import DocumentTextExtractor
from cataloging_tool.document.validator import DocumentValidator
from cataloging_tool.storage.repositories import DocumentRecordRepository, JobRepository
from cataloging_tool.runtime_lock import HeldFileLock, SlotLockService

from .events import NullEventSink, ProgressEvent, WorkflowEventSink

logger = logging.getLogger(__name__)


class WorkflowRunner:
    def __init__(
        self,
        *,
        browser_session: Any,
        pdf_acquirer: Any,
        text_extractor: DocumentTextExtractor,
        parser: DocumentParser,
        validator: DocumentValidator,
        jobs: JobRepository,
        records: DocumentRecordRepository,
        artifacts: ArtifactManager,
        max_attempts: int = 3,
        continue_after_error: bool = True,
        auto_complete: bool = True,
        dry_run: bool = False,
        event_sink: WorkflowEventSink | None = None,
        slot_locks: SlotLockService | None = None,
        slot_id: int = 1,
    ) -> None:
        self.browser_session = browser_session
        self.pdf_acquirer = pdf_acquirer
        self.text_extractor = text_extractor
        self.parser = parser
        self.validator = validator
        self.jobs = jobs
        self.records = records
        self.artifacts = artifacts
        self.max_attempts = max_attempts
        self.continue_after_error = continue_after_error
        self.auto_complete = auto_complete
        self.dry_run = dry_run
        self.event_sink = event_sink or NullEventSink()
        self.cancel_event = asyncio.Event()
        self.cong_van_number_sequence = CongVanNumberSequence()
        self.slot_locks = slot_locks
        self.slot_id = slot_id

    def _parse_document(
        self,
        extracted: Any,
        *,
        existing_form: Any,
    ) -> ParsedDocument:
        return self.parser.parse(
            extracted.text,
            source=extracted.source,
            source_confidence=extracted.confidence,
            existing_form=existing_form,
            is_landscape=extracted.is_landscape,
            special_report_title=extracted.special_report_title,
            header_evidence_text=extracted.header_evidence_text,
            signature_evidence_text=extracted.signature_evidence_text,
            author_evidence_text=extracted.author_evidence_text,
        )

    @staticmethod
    def _cv_number_evidence(extracted: Any) -> CongVanNumberEvidence:
        return CongVanNumberEvidence(
            support=int(extracted.cv_number_support),
            score=float(extracted.cv_number_score),
            candidate_count=int(extracted.cv_number_candidate_count),
        )

    def _parse_and_reconcile(
        self,
        extracted: Any,
        *,
        existing_form: Any,
        record_position: int,
    ) -> ParsedDocument:
        # Kept as a small compatibility helper for unit tests/other callers. The
        # main workflow performs the OCR-retry decision before reconciliation.
        parsed = self._parse_document(extracted, existing_form=existing_form)
        return self.cong_van_number_sequence.reconcile(
            parsed,
            record_position=record_position,
            evidence=self._cv_number_evidence(extracted),
        )

    @staticmethod
    def _unknown_metadata_needs_retry(document: ParsedDocument) -> bool:
        fields = (
            document.document_number,
            document.symbol,
            document.document_type,
            document.abstract,
            document.document_date,
        )
        if any(not field.value.strip() for field in fields):
            return True
        if not document.author.strip():
            return True
        # A no-data record gets one aggressive retry whenever any recovered field
        # is below the normal auto-submit threshold. Security without an explicit
        # marking is intentionally 0.95 because ``Thường`` is the configured safe
        # default, not an OCR guess.
        confidences = [field.confidence for field in fields]
        confidences.append(document.author_confidence)
        confidences.append(document.security_confidence)
        return min(confidences, default=0.0) < 0.82

    @staticmethod
    def _require_complete_unknown_pdf_metadata(document: ParsedDocument) -> None:
        missing: list[str] = []
        if not document.document_type.value.strip():
            missing.append("Tên thể loại văn bản")
        if not document.document_number.value.strip():
            missing.append("Số văn bản")
        if not document.symbol.value.strip():
            missing.append("Ký hiệu văn bản")
        if not document.document_date.value.strip():
            missing.append("Ngày, tháng, năm văn bản")
        if not document.abstract.value.strip():
            missing.append("Trích yếu nội dung")
        if not document.author.strip():
            missing.append("Tác giả văn bản")
        if not document.security_level.strip():
            missing.append("Độ mật")

        low_confidence: list[str] = []
        confidence_pairs = (
            ("Số văn bản", document.document_number.confidence),
            ("Ký hiệu văn bản", document.symbol.confidence),
            ("Tên thể loại văn bản", document.document_type.confidence),
            ("Trích yếu nội dung", document.abstract.confidence),
            ("Ngày, tháng, năm văn bản", document.document_date.confidence),
            ("Tác giả văn bản", document.author_confidence),
            ("Độ mật", document.security_confidence),
        )
        low_confidence.extend(
            name for name, confidence in confidence_pairs
            if confidence < 0.82 and name not in missing
        )

        if not missing and not low_confidence:
            return

        details: list[str] = []
        if missing:
            details.append("thiếu: " + ", ".join(missing))
        if low_confidence:
            details.append("chưa đủ tin cậy: " + ", ".join(low_confidence))
        document.issues.append(
            ValidationIssue(
                code="UNKNOWN_PDF_METADATA_INCOMPLETE",
                field=None,
                message=(
                    "Bản ghi có PDF nhưng chưa phục hồi đủ metadata sau OCR tăng cường ("
                    + "; ".join(details)
                    + "). Không được bấm Hoàn thành với dữ liệu thiếu/suy đoán."
                ),
                severity=Severity.ERROR,
            )
        )

    def request_cancel(self) -> None:
        self.cancel_event.set()

    async def run_new(self, profile_query: str, mode: JobMode, target_document: str = "") -> Job:
        held_lock: HeldFileLock | None = None
        if self.slot_locks is not None:
            held_lock = self.slot_locks.acquire_job(profile_query)
        try:
            job = self.jobs.create(
                Job(id=None, profile_query=profile_query, mode=mode, target_document=target_document)
            )
            assert job.id is not None
            self.jobs.set_status(job.id, JobStatus.RUNNING)
            try:
                page = await self.browser_session.open_base_page()
                artifact_root = getattr(self.artifacts, "root", None)
                profile_page = (
                    ProfileListPage(page, artifact_root=artifact_root)
                    if artifact_root is not None
                    else ProfileListPage(page)
                )
                await profile_page.search_and_open(profile_query)
                list_url = str(page.url)
                inventory = await DocumentListPage(page).inventory_all()
                self.records.upsert_inventory(job.id, inventory)
                self.jobs.refresh_counts(job.id)
                return await self._run_inventory(
                    job,
                    page,
                    list_url=list_url,
                    force_reprocess_all=(mode == JobMode.ALL),
                )
            except OperationCancelledError:
                self.jobs.set_status(job.id, JobStatus.PAUSED)
                return job
            except Exception:
                self.jobs.set_status(job.id, JobStatus.FAILED)
                raise
        finally:
            if held_lock is not None:
                held_lock.release()

    async def resume(self, job: Job) -> Job:
        if job.id is None:
            raise ValueError("Job resume phải có ID")
        held_lock: HeldFileLock | None = None
        if self.slot_locks is not None:
            held_lock = self.slot_locks.acquire_job(job.profile_query)
        try:
            self.jobs.set_status(job.id, JobStatus.RUNNING)
            page = await self.browser_session.open_base_page()
            artifact_root = getattr(self.artifacts, "root", None)
            profile_page = (
                ProfileListPage(page, artifact_root=artifact_root)
                if artifact_root is not None
                else ProfileListPage(page)
            )
            await profile_page.search_and_open(job.profile_query)
            list_url = str(page.url)
            # Re-read the website inventory before deciding what is actionable.
            # This resolves a previous submission_uncertain row to completed when
            # the website confirms that the first submit actually succeeded.
            inventory = await DocumentListPage(page).inventory_all()
            self.records.upsert_inventory(job.id, inventory)
            self.jobs.refresh_counts(job.id)
            return await self._run_inventory(
                job,
                page,
                list_url=list_url,
                force_reprocess_all=False,
            )
        finally:
            if held_lock is not None:
                held_lock.release()

    async def _run_inventory(
        self,
        job: Job,
        page: Any,
        *,
        list_url: str,
        force_reprocess_all: bool = False,
    ) -> Job:
        assert job.id is not None
        start_position = 0
        if job.mode == JobMode.ONE:
            matches = self.records.find_by_target(job.id, job.target_document)
            records_to_visit = matches[:1]
        elif job.mode == JobMode.CONTINUE_FROM:
            matches = self.records.find_by_target(job.id, job.target_document)
            if not matches:
                raise ValueError(f"Không tìm thấy bản ghi bắt đầu: {job.target_document}")
            start_position = matches[0].position
            records_to_visit = self.records.list_actionable(
                job.id, start_position=start_position
            )
        elif job.mode == JobMode.ALL and force_reprocess_all:
            # A brand-new "Run all" is an explicit full rebuild. Reset every
            # inventory row, including rows that the website already marks as
            # completed, then process positions 1..N in website order.
            self.records.prepare_full_rerun(job.id)
            records_to_visit = self.records.list_all(job.id)
            logger.info(
                "Chạy toàn bộ: bắt buộc xử lý lại từ đầu %s/%s bản ghi",
                len(records_to_visit),
                len(records_to_visit),
            )
        else:
            # Resume keeps its original meaning: continue only pending/failed
            # rows and never restart rows already finished by the same job.
            records_to_visit = self.records.list_actionable(job.id)

        # The decreasing number fallback is stateful only inside the Công văn
        # branch. Prime it from the last completed Công văn when resuming; a new
        # full run starts from the first PDF header and does not reuse stale form
        # values from the website.
        self.cong_van_number_sequence.reset()
        if records_to_visit and not force_reprocess_all:
            first_position = records_to_visit[0].position
            prior_cv = [
                item
                for item in self.records.list_all(job.id)
                if item.position < first_position
                and item.document_type == "Công văn"
                and item.document_number.isdigit()
            ]
            if prior_cv:
                anchor = max(prior_cv, key=lambda item: item.position)
                self.cong_van_number_sequence.prime(
                    position=anchor.position,
                    number=anchor.document_number,
                )

        total = len(records_to_visit)
        for index, record in enumerate(records_to_visit, start=1):
            self._check_cancel()
            message = (
                "Bắt đầu xử lý lại từ đầu"
                if job.mode == JobMode.ALL and force_reprocess_all
                else "Bắt đầu xử lý"
            )
            self._publish(job.id, record, index, total, record.status, message)
            await self._process_with_retry(job.id, record, page, index, total)
            self.jobs.refresh_counts(job.id)

        if job.mode == JobMode.ALL and self.auto_complete and not self.dry_run:
            completed, total_rows = await DocumentListPage(page).verify_all_completed(
                list_url, strict=False
            )
            if completed < total_rows:
                logger.warning(
                    "Kết thúc có bản ghi cần xem lại: Hoàn thành %s/%s",
                    completed,
                    total_rows,
                )
            else:
                logger.info(
                    "Đã xác minh trạng thái Hoàn thành %s/%s bản ghi",
                    completed,
                    total_rows,
                )

        self.jobs.set_status(job.id, JobStatus.COMPLETED)
        self.jobs.refresh_counts(job.id)
        return job

    async def _process_with_retry(
        self,
        job_id: int,
        record: DocumentRecord,
        page: Any,
        position: int,
        total: int,
    ) -> None:
        last_error: Exception | None = None
        while record.attempt_count < self.max_attempts:
            self._check_cancel()
            attempt = self.records.increment_attempt(record.id or 0)
            record.attempt_count = attempt
            artifact_dir = self.artifacts.attempt_dir(job_id, record.id or 0, attempt)
            try:
                await self._process_one(job_id, record, page, artifact_dir, position, total)
                return
            except OperationCancelledError:
                self.records.update_status(record.id or 0, RecordStatus.CANCELLED, step="cancelled")
                raise
            except SubmissionUncertainError as exc:
                await self.artifacts.capture_page(page, artifact_dir)
                self.artifacts.write_json(
                    artifact_dir / "error.json",
                    self._error_payload(exc, record=record, artifact_dir=artifact_dir),
                )
                logger.error(
                    "[%s/%s] SUBMISSION UNCERTAIN %s",
                    position, total, exc,
                    extra=self._log_extra(job_id, record, position, total, "SUBMISSION UNCERTAIN", RecordStatus.SUBMISSION_UNCERTAIN, artifact_dir=artifact_dir, exc=exc),
                )
                self.records.update_status(
                    record.id or 0,
                    RecordStatus.SUBMISSION_UNCERTAIN,
                    step=exc.step,
                    error=str(exc),
                )
                self._publish(job_id, record, position, total, RecordStatus.SUBMISSION_UNCERTAIN, str(exc))
                return
            except Exception as exc:
                last_error = exc
                retryable = isinstance(exc, CatalogingError) and exc.retryable
                await self.artifacts.capture_page(page, artifact_dir)
                self.artifacts.write_json(
                    artifact_dir / "error.json",
                    self._error_payload(
                        exc,
                        record=record,
                        artifact_dir=artifact_dir,
                        retryable=retryable,
                    ),
                )
                logger.exception(
                    "[%s/%s] FAILED stage=%s record=%s: %s",
                    position, total, getattr(exc, "step", "unknown"), record.external_id, exc,
                    extra=self._log_extra(job_id, record, position, total, "FAILED", RecordStatus.FAILED, artifact_dir=artifact_dir, exc=exc),
                )
                if retryable and attempt < self.max_attempts:
                    self.records.update_status(
                        record.id or 0,
                        RecordStatus.PENDING,
                        step=getattr(exc, "step", "retry"),
                        error=str(exc),
                    )
                    self._publish(job_id, record, position, total, RecordStatus.PENDING, "Sẽ thử lại")
                    await asyncio.sleep(min(2**attempt, 8))
                    continue
                self.records.update_status(
                    record.id or 0,
                    RecordStatus.FAILED,
                    step=getattr(exc, "step", "failed"),
                    error=str(exc),
                )
                self._publish(job_id, record, position, total, RecordStatus.FAILED, str(exc))
                if not self.continue_after_error:
                    raise
                return
        if last_error:
            raise last_error

    async def _process_one(
        self,
        job_id: int,
        record: DocumentRecord,
        page: Any,
        artifact_dir: Path,
        position: int,
        total: int,
    ) -> None:
        record_id = record.id or 0
        list_page = DocumentListPage(page)
        self.records.update_status(record_id, RecordStatus.OPENING, step="open_record")
        self._stage(job_id, record, position, total, "OPEN RECORD", "Mở bản ghi", RecordStatus.OPENING)
        await list_page.open_record(
            DocumentListItem(
                external_id=record.external_id,
                edit_url=record.edit_url,
                row_text=record.row_text,
                position=record.position,
                page_number=record.page_number,
            )
        )
        edit_page = DocumentEditPage(
            page=page,
            pdf_acquirer=self.pdf_acquirer,
            artifact_root=getattr(self.artifacts, "root", None),
        )
        existing_form = await edit_page.read_form()
        self.artifacts.write_json(artifact_dir / "before-form.json", existing_form)

        # PDF.js may expose an exact Unicode text layer even when the original PDF
        # endpoint is hidden. Prefer it over raster OCR because it preserves all
        # Vietnamese diacritics.
        viewer_text = await edit_page.read_viewer_text()
        if viewer_text:
            (artifact_dir / "viewer-text.txt").write_text(viewer_text, encoding="utf-8")

        # Never skip an unidentified record from a DOM/page-count heuristic before
        # attempting PDF acquisition.  The website can leave a hidden stale 0/0
        # toolbar beside a fully rendered 1/N viewer.  A record is skippable only
        # after acquisition itself fails and the viewer still confirms a real 0/0.
        metadata_recovery_record = form_needs_full_metadata_recovery(existing_form)
        signature_source_image = None
        if metadata_recovery_record and not existing_form.signer_name.strip():
            signature_source_image = await edit_page.capture_last_page_image(
                record.external_id, artifact_dir
            )

        self._check_cancel()
        self.records.update_status(record_id, RecordStatus.PDF_ACQUIRING, step="pdf_acquire")
        self._stage(job_id, record, position, total, "ACQUIRE PDF", "Lấy PDF/viewer", RecordStatus.PDF_ACQUIRING)
        try:
            acquired = await edit_page.acquire_pdf(record.external_id)
        except Exception:
            if metadata_recovery_record and await edit_page.should_skip_missing_pdf(
                existing_form, viewer_text
            ):
                await self.artifacts.capture_page(page, artifact_dir)
                self.artifacts.write_json(
                    artifact_dir / "skipped.json",
                    {
                        "reason": "missing_pdf",
                        "message": (
                            "Đã thử lấy PDF nhưng thất bại; viewer vẫn xác nhận 0 trên 0."
                        ),
                        "form": existing_form,
                    },
                )
                self.records.update_status(
                    record_id,
                    RecordStatus.SKIPPED_NO_PDF,
                    step="missing_pdf",
                    error="Bỏ qua bản ghi Không xác định sau khi xác nhận không có PDF",
                )
                self._publish(
                    job_id,
                    record,
                    position,
                    total,
                    RecordStatus.SKIPPED_NO_PDF,
                    "Bỏ qua: đã thử lấy PDF và viewer xác nhận 0 trên 0",
                )
                return
            raise

        self.records.update_status(record_id, RecordStatus.PDF_READING, step="pdf_read")
        symbol_hint = "" if metadata_recovery_record else existing_form.symbol
        type_hint = "" if metadata_recovery_record else existing_form.document_type
        date_hint = "" if metadata_recovery_record else existing_form.document_date

        extracted = self.text_extractor.extract(
            acquired.path,
            f"record-{record.external_id}",
            preferred_text=viewer_text,
            source_image=acquired.image_path,
            document_symbol_hint=symbol_hint,
            document_type_hint=type_hint,
            document_date_hint=date_hint,
            metadata_recovery=metadata_recovery_record,
            signature_source_image=signature_source_image,
            signer_name_hint=existing_form.signer_name,
            stage_callback=lambda stage, message: self._stage(
                job_id, record, position, total, stage, message, RecordStatus.OCR_RUNNING
            ),
        )

        self.records.update_status(record_id, RecordStatus.PARSING, step="parse")
        self._stage(job_id, record, position, total, "PARSE", "Phân tích metadata", RecordStatus.PARSING)
        # Parse FIRST, but do not apply the decreasing Công-văn sequence yet.
        # Sequence reconciliation used to run before the OCR retry and could turn
        # a weak/missed scan into a high-confidence ``previous - 1`` value. That
        # masked the fact that the current PDF number had never been confirmed.
        parsed = self._parse_document(extracted, existing_form=existing_form)
        number_evidence = self._cv_number_evidence(extracted)

        metadata_retry_needed = (
            metadata_recovery_record and self._unknown_metadata_needs_retry(parsed)
        )
        number_retry_needed = self.cong_van_number_sequence.needs_ocr_retry(
            parsed,
            record_position=record.position,
            evidence=number_evidence,
        )

        # One cache-bypassing focused retry is mandatory whenever a Công văn
        # number is missing or weakly conflicts with the sequence. Empty/unknown
        # forms use the same pass for all mandatory metadata, so we never do two
        # redundant expensive retries for the same PDF.
        if metadata_retry_needed or number_retry_needed:
            retry_stage = "METADATA RETRY" if metadata_retry_needed else "NUMBER RETRY"
            retry_message = (
                "Quét tăng cường đủ Số/Ký hiệu/Thể loại/Ngày/Trích yếu/Tác giả"
                if metadata_retry_needed
                else "Quét lại riêng đầu văn bản để xác nhận Số văn bản trước khi dùng đếm ngược"
            )
            self._stage(
                job_id, record, position, total,
                retry_stage,
                retry_message,
                RecordStatus.OCR_RUNNING,
            )

            forced = self.text_extractor.extract(
                acquired.path,
                f"record-{record.external_id}",
                preferred_text="",
                source_image=acquired.image_path,
                document_symbol_hint=("" if metadata_recovery_record else existing_form.symbol),
                document_type_hint=("" if metadata_recovery_record else existing_form.document_type),
                document_date_hint=("" if metadata_recovery_record else existing_form.document_date),
                metadata_recovery=metadata_recovery_record,
                force_metadata_recovery=True,
                signature_source_image=signature_source_image,
                signer_name_hint=existing_form.signer_name,
                stage_callback=lambda stage, message: self._stage(
                    job_id, record, position, total, stage, message, RecordStatus.OCR_RUNNING
                ),
            )

            forced_parsed = self._parse_document(
                forced, existing_form=existing_form
            )
            number_evidence = self.cong_van_number_sequence.merge_retry_evidence(
                parsed,
                self._cv_number_evidence(extracted),
                forced_parsed,
                self._cv_number_evidence(forced),
            )

            combined_text = "\n".join(
                part for part in (extracted.text, forced.text) if part
            )
            combined_header = "\n".join(
                part
                for part in (extracted.header_evidence_text, forced.header_evidence_text)
                if part
            )
            combined_author = "\n".join(
                part
                for part in (extracted.author_evidence_text, forced.author_evidence_text)
                if part
            )
            parsed = self.parser.parse(
                combined_text,
                source=forced.source,
                source_confidence=max(extracted.confidence, forced.confidence),
                existing_form=existing_form,
                is_landscape=(extracted.is_landscape or forced.is_landscape),
                special_report_title=(
                    forced.special_report_title or extracted.special_report_title
                ),
                header_evidence_text=combined_header,
                signature_evidence_text=(
                    forced.signature_evidence_text or extracted.signature_evidence_text
                ),
                author_evidence_text=combined_author,
            )
            extracted = forced

        # Only now is the fallback sequence allowed to run. In 0.1.27.4.19 the
        # sequence class itself enforces the same hard rule: if any numeric OCR
        # candidate exists, it cannot be replaced merely by ``previous - 1``.
        parsed = self.cong_van_number_sequence.reconcile(
            parsed,
            record_position=record.position,
            evidence=number_evidence,
        )

        if metadata_recovery_record:
            self._require_complete_unknown_pdf_metadata(parsed)
        self.records.update_status(record_id, RecordStatus.VALIDATING, step="validate")
        self._stage(job_id, record, position, total, "VALIDATE", "Đối chiếu dữ liệu và confidence", RecordStatus.VALIDATING)
        self.validator.validate(parsed)
        self.artifacts.write_json(artifact_dir / "parsed.json", parsed.to_dict())

        self.records.save_result(
            record_id,
            document_number=parsed.document_number.value,
            symbol=parsed.symbol.value,
            document_type=parsed.document_type.value,
            abstract=parsed.abstract.value,
            document_date=parsed.document_date.value,
            author=parsed.author,
            signer_name=parsed.signer_name.value,
            security_level=parsed.security_level,
            confidence=parsed.overall_confidence,
            field_confidence=parsed.confidence_map(),
            field_sources=parsed.source_map(),
            pdf_path=str(acquired.path),
            ocr_path=str(extracted.ocr_text_path or ""),
            artifact_path=str(artifact_dir),
        )
        self.artifacts.write_diagnostic_manifest(
            artifact_dir,
            source_pdf=acquired.path,
            ocr_path=extracted.ocr_text_path,
            existing_form=existing_form,
            parsed=parsed,
            extracted=extracted,
            final_status="validated",
        )

        if not self.validator.can_auto_submit(parsed):
            self.records.update_status(record_id, RecordStatus.NEEDS_REVIEW, step="needs_review")
            await self.artifacts.capture_page(page, artifact_dir)
            self.artifacts.write_diagnostic_manifest(
                artifact_dir,
                source_pdf=acquired.path,
                ocr_path=extracted.ocr_text_path,
                existing_form=existing_form,
                parsed=parsed,
                extracted=extracted,
                final_status=RecordStatus.NEEDS_REVIEW.value,
            )
            errors = "; ".join(issue.message for issue in parsed.issues if issue.severity == Severity.ERROR)
            self._publish(job_id, record, position, total, RecordStatus.NEEDS_REVIEW, errors)
            return

        if self.dry_run:
            self.records.update_status(
                record_id, RecordStatus.READY_TO_SUBMIT, step="dry_run"
            )
            self._publish(
                job_id,
                record,
                position,
                total,
                RecordStatus.READY_TO_SUBMIT,
                "Dry-run đạt yêu cầu; chưa sửa form",
            )
            return

        # Luôn điền đủ sáu giá trị bắt buộc như tool gốc:
        # Số, Ký hiệu, Thể loại, Trích yếu, Tác giả và Độ mật.
        self._check_cancel()
        self.records.update_status(
            record_id, RecordStatus.READY_TO_SUBMIT, step="fill_form"
        )
        self._stage(job_id, record, position, total, "FILL FORM", "Điền và đọc lại form", RecordStatus.READY_TO_SUBMIT)
        after_form = await edit_page.fill_from_parsed(parsed, existing_form)
        self.artifacts.write_json(artifact_dir / "after-form.json", after_form)

        if not self.auto_complete:
            self.records.update_status(
                record_id,
                RecordStatus.READY_TO_SUBMIT,
                step="filled_not_submitted",
            )
            self._publish(
                job_id,
                record,
                position,
                total,
                RecordStatus.READY_TO_SUBMIT,
                "Đã điền và đọc lại đủ trường bắt buộc; chưa bấm Hoàn thành",
            )
            return

        self.records.update_status(
            record_id, RecordStatus.SUBMITTING, step="submit"
        )
        self._stage(job_id, record, position, total, "SUBMIT", "Bấm Hoàn thành một lần", RecordStatus.SUBMITTING)
        await edit_page.complete_and_verify()
        self._stage(job_id, record, position, total, "VERIFY", "Xác minh trạng thái sau submit", RecordStatus.VERIFYING)
        self.records.update_status(record_id, RecordStatus.COMPLETED, step="verified")
        self.artifacts.prune_completed_attempt(artifact_dir)
        self._publish(job_id, record, position, total, RecordStatus.COMPLETED, "Đã hoàn thành và xác minh")

    def _check_cancel(self) -> None:
        if self.cancel_event.is_set():
            raise OperationCancelledError("Đã dừng an toàn theo yêu cầu.", step="cancelled")

    @staticmethod
    def _error_payload(
        exc: Exception,
        *,
        record: DocumentRecord,
        artifact_dir: Path,
        retryable: bool | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "error_code": error_code_for_exception(exc),
            "type": type(exc).__name__,
            "message": str(exc),
            "stage": getattr(exc, "step", "unknown") or "unknown",
            "field": getattr(exc, "field", None),
            "record": {
                "id": record.id,
                "external_id": record.external_id,
                "position": record.position,
            },
            "artifact": str(artifact_dir),
        }
        if retryable is not None:
            payload["retryable"] = retryable
        return payload

    def _log_extra(
        self,
        job_id: int,
        record: DocumentRecord,
        position: int,
        total: int,
        stage: str,
        status: RecordStatus | None,
        *,
        artifact_dir: Path | None = None,
        exc: Exception | None = None,
    ) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "job_id": job_id,
            "record_id": record.id,
            "record_external_id": record.external_id,
            "record_position": record.position,
            "position": position,
            "total": total,
            "status": status.value if status else "",
            "stage": stage,
            "step": getattr(exc, "step", "") if exc else "",
            "error_code": error_code_for_exception(exc) if exc else "",
            "field": getattr(exc, "field", None) if exc else None,
            "artifact": str(artifact_dir or ""),
        }

    def _stage(
        self,
        job_id: int,
        record: DocumentRecord,
        position: int,
        total: int,
        stage: str,
        message: str,
        status: RecordStatus | None = None,
    ) -> None:
        logger.info(
            "[%s/%s] %s - %s",
            position,
            total,
            stage,
            message,
            extra=self._log_extra(job_id, record, position, total, stage, status),
        )
        self.event_sink.publish(
            ProgressEvent(
                job_id=job_id,
                record_id=record.id,
                record_position=record.position,
                position=position,
                total=total,
                status=status,
                message=message,
                stage=stage,
            )
        )

    def _publish(
        self,
        job_id: int,
        record: DocumentRecord,
        position: int,
        total: int,
        status: RecordStatus | None,
        message: str,
        *,
        stage: str = "",
    ) -> None:
        logger.info(
            "[%s/%s] %s%s",
            position,
            total,
            f"{stage} - " if stage else "",
            message,
            extra=self._log_extra(job_id, record, position, total, stage, status),
        )
        self.event_sink.publish(
            ProgressEvent(
                job_id=job_id,
                record_id=record.id,
                record_position=record.position,
                position=position,
                total=total,
                status=status,
                message=message,
                stage=stage,
            )
        )
