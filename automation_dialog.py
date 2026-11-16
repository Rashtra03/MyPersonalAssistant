"""PySide6 Automation Studio Dialog for JUGNU.

Provides visual cron schedule configuration, task creation & management,
live schedule translation, and manual task trigger execution.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from scheduler import CronEvaluator, ScheduledTask, TaskStore

SCHEDULE_PRESETS = [
    ("Every 15 minutes", "*/15 * * * *"),
    ("Every 30 minutes", "*/30 * * * *"),
    ("Every hour", "0 * * * *"),
    ("Daily morning briefing (09:00 AM)", "0 9 * * *"),
    ("Daily evening wrap-up (06:00 PM)", "0 18 * * *"),
    ("Every weekday at 10:00 AM", "0 10 * * 1-5"),
    ("Every Sunday at midnight", "0 0 * * 0"),
    ("Custom Cron Expression…", ""),
]


class AutomationDialog(QDialog):
    """Visual schedule builder and manager for proactive JUGNU automation."""

    def __init__(self, window, store: TaskStore, scheduler=None):
        super().__init__(window)
        self.window = window
        self.store = store
        self.scheduler = scheduler
        self.selected_task_id: Optional[str] = None

        self.setWindowTitle(self.window.t("auto_dialog_title") if hasattr(self.window, "t") else "Automation Studio")
        self.setMinimumSize(850, 560)
        self.resize(920, 600)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(12)

        # Header bar
        header_row = QHBoxLayout()
        header_title = QLabel("⏱  " + (self.window.t("auto_dialog_title") if hasattr(self.window, "t") else "Automation Studio"))
        header_title.setObjectName("autoHeaderTitle")
        header_title.setStyleSheet("font-size: 15pt; font-weight: 700; color: #8B5CF6;")
        header_row.addWidget(header_title)

        header_row.addStretch()

        self.status_pill = QLabel("● Scheduler: Active")
        self.status_pill.setStyleSheet("font-size: 9pt; font-weight: 600; padding: 4px 10px; border-radius: 6px;")
        header_row.addWidget(self.status_pill)

        self.pause_btn = QPushButton("⏸ Pause")
        self.pause_btn.clicked.connect(self.on_toggle_pause)
        header_row.addWidget(self.pause_btn)

        self.new_task_btn = QPushButton("+ New Task")
        self.new_task_btn.clicked.connect(self.on_new_task)
        header_row.addWidget(self.new_task_btn)

        main_layout.addLayout(header_row)

        # Splitter: Left Task List, Right Task Details / Form
        splitter = QSplitter(Qt.Horizontal)

        # Left panel: Task List Table
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        self.task_list = QListWidget()
        self.task_list.currentRowChanged.connect(self.on_select_task)
        left_layout.addWidget(self.task_list, 1)

        splitter.addWidget(left_widget)

        # Right panel: Form / Inspector
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(10)

        # Form fields
        self.name_label = QLabel("Task Title:")
        self.name_label.setProperty("variant", "field")
        right_layout.addWidget(self.name_label)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("e.g. Morning Tech Briefing")
        right_layout.addWidget(self.title_edit)

        # Preset & Cron
        self.schedule_label = QLabel("Schedule:")
        self.schedule_label.setProperty("variant", "field")
        right_layout.addWidget(self.schedule_label)

        preset_row = QHBoxLayout()
        self.preset_combo = QComboBox()
        for label, expr in SCHEDULE_PRESETS:
            self.preset_combo.addItem(label, expr)
        self.preset_combo.currentIndexChanged.connect(self.on_preset_changed)
        preset_row.addWidget(self.preset_combo, 1)
        right_layout.addLayout(preset_row)

        self.cron_edit = QLineEdit()
        self.cron_edit.setPlaceholderText("Cron expression (min hour dom mon dow)")
        self.cron_edit.textChanged.connect(self.on_cron_text_changed)
        right_layout.addWidget(self.cron_edit)

        self.cron_preview = QLabel("Every day at 09:00")
        self.cron_preview.setStyleSheet("font-size: 8pt; color: #10B981; font-style: italic;")
        right_layout.addWidget(self.cron_preview)

        # Prompt
        self.prompt_label = QLabel("Prompt Template:")
        self.prompt_label.setProperty("variant", "field")
        right_layout.addWidget(self.prompt_label)

        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setPlaceholderText("Enter the prompt that JUGNU will execute automatically...")
        right_layout.addWidget(self.prompt_edit, 1)

        # Persona row
        persona_row = QHBoxLayout()
        persona_lbl = QLabel("Persona:")
        persona_lbl.setProperty("variant", "field")
        persona_row.addWidget(persona_lbl)

        self.persona_combo = QComboBox()
        self.persona_combo.addItem("Default (General Assistant)", "default")
        # Populate custom personas if available in parent window
        if hasattr(self.window, "persona_manager") and self.window.persona_manager:
            for p in self.window.persona_manager.all():
                if p.id != "default":
                    self.persona_combo.addItem(p.display_label, p.id)
        persona_row.addWidget(self.persona_combo, 1)
        right_layout.addLayout(persona_row)

        # Last Output Preview
        self.output_label = QLabel("Last Execution Output:")
        self.output_label.setProperty("variant", "field")
        right_layout.addWidget(self.output_label)

        self.output_preview = QPlainTextEdit()
        self.output_preview.setReadOnly(True)
        self.output_preview.setMaximumHeight(80)
        self.output_preview.setPlaceholderText("No run history yet.")
        right_layout.addWidget(self.output_preview)

        # Action Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.run_btn = QPushButton("▶ Run Now")
        self.run_btn.clicked.connect(self.on_run_now)
        btn_row.addWidget(self.run_btn)

        self.toggle_enable_btn = QPushButton("Disable Task")
        self.toggle_enable_btn.clicked.connect(self.on_toggle_enabled)
        btn_row.addWidget(self.toggle_enable_btn)

        self.save_btn = QPushButton("Save Task")
        self.save_btn.clicked.connect(self.on_save)
        btn_row.addWidget(self.save_btn)

        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setProperty("variant", "danger")
        self.delete_btn.clicked.connect(self.on_delete)
        btn_row.addWidget(self.delete_btn)

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        btn_row.addWidget(self.close_btn)

        right_layout.addLayout(btn_row)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        main_layout.addWidget(splitter, 1)

        self.update_scheduler_status_pill()
        self.populate_tasks()

    def update_scheduler_status_pill(self):
        """Update top status pill text and pause button."""
        if not self.scheduler or not self.scheduler.is_running:
            self.status_pill.setText("● Scheduler: Stopped")
            self.status_pill.setStyleSheet("font-size: 9pt; font-weight: 600; padding: 4px 10px; border-radius: 6px; color: #EF4444;")
            self.pause_btn.setText("▶ Start")
        elif self.scheduler.is_paused:
            self.status_pill.setText("⏸ Scheduler: Paused")
            self.status_pill.setStyleSheet("font-size: 9pt; font-weight: 600; padding: 4px 10px; border-radius: 6px; color: #F59E0B;")
            self.pause_btn.setText("▶ Resume")
        else:
            active_count = len([t for t in self.store.all() if t.enabled])
            self.status_pill.setText(f"● Scheduler: Active ({active_count} tasks)")
            self.status_pill.setStyleSheet("font-size: 9pt; font-weight: 600; padding: 4px 10px; border-radius: 6px; color: #10B981;")
            self.pause_btn.setText("⏸ Pause")

    def populate_tasks(self, select_id: Optional[str] = None):
        """Refresh task list."""
        self.task_list.clear()
        tasks = self.store.all()
        target_row = 0

        for idx, task in enumerate(tasks):
            status_icon = "●" if task.enabled else "⏸"
            item_text = f"{status_icon}  {task.title}\n    {task.cron_expression} • {task.last_status}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, task.id)
            self.task_list.addItem(item)
            if select_id and task.id == select_id:
                target_row = idx

        if tasks:
            self.task_list.setCurrentRow(target_row)
        else:
            self.on_new_task()

    def on_select_task(self, row: int):
        """Handle user selecting a task from the list."""
        if row < 0:
            return
        item = self.task_list.item(row)
        if not item:
            return
        task_id = item.data(Qt.UserRole)
        task = self.store.get(task_id)
        if not task:
            return

        self.selected_task_id = task.id
        self.title_edit.setText(task.title)
        self.cron_edit.setText(task.cron_expression)
        self.prompt_edit.setPlainText(task.prompt)

        # Set preset combo if matches
        matched_idx = -1
        for i in range(self.preset_combo.count()):
            if self.preset_combo.itemData(i) == task.cron_expression:
                matched_idx = i
                break
        if matched_idx >= 0:
            self.preset_combo.setCurrentIndex(matched_idx)
        else:
            self.preset_combo.setCurrentIndex(self.preset_combo.count() - 1)  # Custom

        # Persona combo
        idx = self.persona_combo.findData(task.persona)
        if idx >= 0:
            self.persona_combo.setCurrentIndex(idx)

        # Output preview
        out_text = f"Last Run: {task.last_run or 'Never'}\nStatus: {task.last_status}\nNext Run: {task.next_run or 'N/A'}\n\n{task.last_output or ''}"
        self.output_preview.setPlainText(out_text.strip())

        # Enable/Disable toggle button text
        self.toggle_enable_btn.setText("Disable Task" if task.enabled else "Enable Task")
        self.run_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)

    def on_new_task(self):
        """Reset form to create a new task."""
        self.selected_task_id = None
        self.task_list.setCurrentRow(-1)
        self.title_edit.setText("")
        self.preset_combo.setCurrentIndex(3)  # Daily 09:00 AM
        self.cron_edit.setText("0 9 * * *")
        self.prompt_edit.setPlainText("Provide a morning update: summary of tasks, news, or notes for today.")
        self.output_preview.setPlainText("New task — not run yet.")
        self.toggle_enable_btn.setText("Disable Task")
        self.run_btn.setEnabled(False)
        self.delete_btn.setEnabled(False)
        self.title_edit.setFocus()

    def on_preset_changed(self, idx: int):
        expr = self.preset_combo.itemData(idx)
        if expr:
            self.cron_edit.setText(expr)

    def on_cron_text_changed(self, text: str):
        try:
            evaluator = CronEvaluator(text)
            desc = evaluator.describe()
            self.cron_preview.setText(f"✓ {desc}")
            self.cron_preview.setStyleSheet("font-size: 8pt; color: #10B981; font-style: italic;")
        except Exception as e:
            self.cron_preview.setText(f"⚠ Invalid: {e}")
            self.cron_preview.setStyleSheet("font-size: 8pt; color: #EF4444; font-style: italic;")

    def on_save(self):
        title = self.title_edit.text().strip()
        cron = self.cron_edit.text().strip()
        prompt = self.prompt_edit.toPlainText().strip()
        persona = self.persona_combo.currentData() or "default"

        if not title:
            QMessageBox.warning(self, "Invalid Title", "Please enter a task title.")
            return
        if not prompt:
            QMessageBox.warning(self, "Invalid Prompt", "Task prompt cannot be empty.")
            return
        try:
            CronEvaluator(cron)
        except Exception as e:
            QMessageBox.warning(self, "Invalid Cron Expression", str(e))
            return

        if self.selected_task_id:
            task = self.store.update(
                self.selected_task_id,
                title=title,
                cron_expression=cron,
                prompt=prompt,
                persona=persona,
            )
        else:
            task = self.store.add(
                title=title,
                cron_expression=cron,
                prompt=prompt,
                persona=persona,
            )

        self.update_scheduler_status_pill()
        self.populate_tasks(select_id=task.id if task else None)

    def on_delete(self):
        if not self.selected_task_id:
            return
        task = self.store.get(self.selected_task_id)
        if not task:
            return
        if QMessageBox.question(
            self,
            "Confirm Delete",
            f"Are you sure you want to delete scheduled task '{task.title}'?",
            QMessageBox.Yes | QMessageBox.No,
        ) == QMessageBox.Yes:
            self.store.delete(self.selected_task_id)
            self.update_scheduler_status_pill()
            self.populate_tasks()

    def on_toggle_enabled(self):
        if not self.selected_task_id:
            return
        task = self.store.toggle(self.selected_task_id)
        if task:
            self.toggle_enable_btn.setText("Disable Task" if task.enabled else "Enable Task")
            self.update_scheduler_status_pill()
            self.populate_tasks(select_id=task.id)

    def on_run_now(self):
        """Immediately trigger execution of the selected task."""
        if not self.selected_task_id:
            return
        task = self.store.get(self.selected_task_id)
        if not task:
            return
        if self.scheduler:
            self.run_btn.setEnabled(False)
            self.run_btn.setText("⏳ Running…")
            self.scheduler.trigger_task_now(task.id)
            QTimer.singleShot(1500, self._refresh_after_run)

    def _refresh_after_run(self):
        self.run_btn.setEnabled(True)
        self.run_btn.setText("▶ Run Now")
        self.populate_tasks(select_id=self.selected_task_id)

    def on_toggle_pause(self):
        if not self.scheduler:
            return
        if self.scheduler.is_paused:
            self.scheduler.resume()
        else:
            self.scheduler.pause()
        self.update_scheduler_status_pill()
        if hasattr(self.window, "tray_icon") and self.window.tray_icon:
            self.window.tray_icon.build_menu()
