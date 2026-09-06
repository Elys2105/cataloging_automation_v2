from __future__ import annotations

from typing import Any

from PySide6.QtCore import QThread, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cataloging_tool.bootstrap import build_runner
from cataloging_tool.config.settings import AppSettings
from cataloging_tool.domain.enums import JobMode, RecordStatus
from cataloging_tool.workflow.events import ProgressEvent

from .worker import AutomationWorker


class MainWindow(QMainWindow):
    def __init__(self, settings: AppSettings) -> None:
        super().__init__()
        self.settings = settings
        self.worker_thread: QThread | None = None
        self.worker: AutomationWorker | None = None
        self.row_by_record: dict[int, int] = {}
        self.setWindowTitle(f"{settings.name} {settings.version} - Slot {settings.slot_id}")
        self.resize(1120, 680)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QWidget(self)
        layout = QVBoxLayout(root)

        form = QFormLayout()
        self.profile_input = QLineEdit()
        self.profile_input.setPlaceholderText("Nhập số/ký hiệu hồ sơ")
        self.document_input = QLineEdit()
        self.document_input.setPlaceholderText("Chỉ dùng khi chạy một bản ghi hoặc tiếp tục từ bản ghi")
        form.addRow("Số/ký hiệu hồ sơ:", self.profile_input)
        form.addRow("Số/ký hiệu văn bản:", self.document_input)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        self.run_all_button = QPushButton("Chạy toàn bộ")
        self.run_all_button.setToolTip("Luôn xử lý lại toàn bộ bản ghi từ 1 đến hết, kể cả đã Hoàn thành")
        self.run_one_button = QPushButton("Chạy 1 bản ghi")
        self.continue_button = QPushButton("Tiếp tục từ bản ghi")
        self.resume_button = QPushButton("Tiếp tục job đang dở")
        self.stop_button = QPushButton("Dừng an toàn")
        self.stop_button.setEnabled(False)
        for button in (
            self.run_all_button,
            self.run_one_button,
            self.continue_button,
            self.resume_button,
            self.stop_button,
        ):
            buttons.addWidget(button)
        layout.addLayout(buttons)

        self.status_label = QLabel(f"Slot {self.settings.slot_id} - Trạng thái: Sẵn sàng")
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        layout.addWidget(self.progress_bar)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["STT", "Bản ghi", "Trạng thái", "Tiến độ", "Chi tiết", "Job"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)

        self.run_all_button.clicked.connect(lambda: self._start(JobMode.ALL))
        self.run_one_button.clicked.connect(lambda: self._start(JobMode.ONE))
        self.continue_button.clicked.connect(lambda: self._start(JobMode.CONTINUE_FROM))
        self.resume_button.clicked.connect(lambda: self._start(JobMode.RESUME))
        self.stop_button.clicked.connect(self._stop)
        self.setCentralWidget(root)

    def _start(self, mode: JobMode) -> None:
        if self.worker_thread is not None:
            return
        profile = self.profile_input.text().strip()
        target = self.document_input.text().strip()
        if mode != JobMode.RESUME and not profile:
            QMessageBox.warning(self, "Thiếu hồ sơ", "Vui lòng nhập số/ký hiệu hồ sơ.")
            return
        if mode in {JobMode.ONE, JobMode.CONTINUE_FROM} and not target:
            QMessageBox.warning(self, "Thiếu văn bản", "Vui lòng nhập số/ký hiệu văn bản.")
            return

        self.table.setRowCount(0)
        self.row_by_record.clear()
        runner = build_runner(self.settings)
        self.worker_thread = QThread(self)
        self.worker = AutomationWorker(runner, profile, mode, target)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self._on_finished)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self._set_running(True)
        self.status_label.setText(f"Slot {self.settings.slot_id} - Trạng thái: Đang khởi động automation...")
        self.worker_thread.start()

    def _stop(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self.status_label.setText(f"Slot {self.settings.slot_id} - Trạng thái: Đã yêu cầu dừng sau bước an toàn hiện tại...")
            self.stop_button.setEnabled(False)

    def _on_progress(self, event: ProgressEvent) -> None:
        if event.record_id is None:
            return
        row = self.row_by_record.get(event.record_id)
        if row is None:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.row_by_record[event.record_id] = row
            self.table.setItem(row, 0, QTableWidgetItem(str(event.position)))
            self.table.setItem(row, 1, QTableWidgetItem(str(event.record_position or event.record_id)))
            self.table.setItem(row, 5, QTableWidgetItem(str(event.job_id)))
        status = event.status.value if event.status else ""
        self.table.setItem(row, 2, QTableWidgetItem(status))
        self.table.setItem(row, 3, QTableWidgetItem(f"{event.position}/{event.total}"))
        detail_text = f"[{event.stage}] {event.message}" if event.stage else event.message
        detail = QTableWidgetItem(detail_text)
        if event.status in {RecordStatus.FAILED, RecordStatus.NEEDS_REVIEW, RecordStatus.SUBMISSION_UNCERTAIN}:
            detail.setBackground(QColor("#ffd6d6"))
        elif event.status == RecordStatus.COMPLETED:
            detail.setBackground(QColor("#d8f5d0"))
        elif event.status in {RecordStatus.SKIPPED, RecordStatus.SKIPPED_NO_PDF}:
            detail.setBackground(QColor("#fff2b8"))
        self.table.setItem(row, 4, detail)
        percent = int(event.position * 100 / max(event.total, 1))
        self.progress_bar.setValue(percent)
        self.status_label.setText(
            f"Slot {self.settings.slot_id} - Trạng thái: {detail_text} "
            f"({event.position}/{event.total})"
        )

    def _on_failed(self, details: str) -> None:
        self.status_label.setText(f"Slot {self.settings.slot_id} - Trạng thái: Có lỗi nghiêm trọng")
        QMessageBox.critical(self, "Automation lỗi", details[-4000:])

    def _on_finished(self) -> None:
        self.status_label.setText(f"Slot {self.settings.slot_id} - Trạng thái: Đã kết thúc")
        self.progress_bar.setValue(100)
        self._set_running(False)
        self.worker = None
        self.worker_thread = None

    def _set_running(self, running: bool) -> None:
        for button in (self.run_all_button, self.run_one_button, self.continue_button, self.resume_button):
            button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.profile_input.setEnabled(not running)
        self.document_input.setEnabled(not running)

    def closeEvent(self, event: Any) -> None:  # noqa: N802 - Qt API
        if self.worker is not None:
            answer = QMessageBox.question(
                self,
                "Đang chạy",
                "Automation đang chạy. Dừng an toàn và đóng ứng dụng?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.worker.cancel()
        event.accept()


def run_ui(settings: AppSettings) -> int:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(settings)
    window.show()
    return app.exec()
