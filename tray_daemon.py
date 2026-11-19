"""PySide6 System Tray Daemon and Native OS Notification Manager for JUGNU.

Provides seamless system tray integration (QSystemTrayIcon), status tooltips,
tray context menus, background task monitoring, and native desktop notifications.
"""

from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import QObject, Qt, Signal, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
)

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ICON_PATH = os.path.join(HERE, "jugnu_bot.png")


def create_fallback_tray_icon() -> QIcon:
    """Generate a crisp vector-style QIcon in case jugnu_bot.png is unavailable."""
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    # Outer circle in purple
    painter.setBrush(QColor("#8B5CF6"))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(2, 2, 28, 28)

    # Inner glowing bulb dot in pink
    painter.setBrush(QColor("#EC4899"))
    painter.drawEllipse(10, 10, 12, 12)

    painter.end()
    return QIcon(pixmap)


class QuickAskDialog(QDialog):
    """Minimalist popup dialog to quickly ask JUGNU a question from the system tray."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("JUGNU Quick Ask")
        self.setFixedWidth(450)
        self.setWindowFlags(Qt.Dialog | Qt.WindowStaysOnTopHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QLabel("⚡ Quick Ask JUGNU:")
        header.setStyleSheet("font-weight: 700; font-size: 13pt; color: #8B5CF6;")
        layout.addWidget(header)

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Ask a question, calculation, or command...")
        self.input_field.returnPressed.connect(self.on_submit)
        layout.addWidget(self.input_field)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self.on_submit)
        btn_row.addWidget(self.send_btn)

        self.close_btn = QPushButton("Cancel")
        self.close_btn.setProperty("variant", "danger")
        self.close_btn.clicked.connect(self.close)
        btn_row.addWidget(self.close_btn)

        layout.addLayout(btn_row)

    def on_submit(self):
        text = self.input_field.text().strip()
        if not text:
            return
        self.close()
        # Restore window and inject query
        self.window.restore_from_tray()
        if hasattr(self.window, "input_box"):
            self.window.input_box.setPlainText(text)
            self.window.send_message()


class JugnuTrayIcon(QSystemTrayIcon):
    """System tray icon controller with dynamic menus and desktop notifications."""

    def __init__(self, window, scheduler=None):
        super().__init__(window)
        self.window = window
        self.scheduler = scheduler

        # Load or generate icon
        if os.path.exists(DEFAULT_ICON_PATH):
            self.icon = QIcon(DEFAULT_ICON_PATH)
        else:
            self.icon = create_fallback_tray_icon()
        self.setIcon(self.icon)

        # Context menu
        self.menu = QMenu()
        self.setContextMenu(self.menu)
        self.build_menu()

        # Connect signals
        self.activated.connect(self.on_tray_activated)
        self.messageClicked.connect(self.on_notification_clicked)

        # Hook scheduler notifications if scheduler provided
        if self.scheduler:
            self.scheduler.on_notification = self.notify

        self.update_tooltip()

    def build_menu(self):
        """Construct the tray context menu."""
        self.menu.clear()

        # Open Window
        open_action = QAction("🖥  Open JUGNU", self)
        open_action.triggered.connect(self.window.restore_from_tray)
        self.menu.addAction(open_action)

        # Quick Ask
        quick_action = QAction("⚡  Quick Ask…", self)
        quick_action.triggered.connect(self.open_quick_ask)
        self.menu.addAction(quick_action)

        # Automation Studio
        auto_action = QAction("⏱  Automation Studio…", self)
        auto_action.triggered.connect(self.open_automation_studio)
        self.menu.addAction(auto_action)

        self.menu.addSeparator()

        # Scheduler pause / resume
        if self.scheduler:
            is_paused = self.scheduler.is_paused
            pause_label = "▶  Resume Scheduled Tasks" if is_paused else "⏸  Pause Scheduled Tasks"
            pause_action = QAction(pause_label, self)
            pause_action.triggered.connect(self.toggle_scheduler_pause)
            self.menu.addAction(pause_action)

            # Submenu: Run task now
            tasks = [t for t in self.scheduler.store.all() if t.enabled]
            if tasks:
                run_submenu = self.menu.addMenu("▶  Run Task Now")
                for t in tasks:
                    action = run_submenu.addAction(f"▶  {t.title}")
                    action.triggered.connect(lambda chk=False, tid=t.id: self.scheduler.trigger_task_now(tid))

        self.menu.addSeparator()

        # Quit
        quit_action = QAction("✕  Quit JUGNU", self)
        quit_action.triggered.connect(self.quit_app)
        self.menu.addAction(quit_action)

    def update_tooltip(self):
        """Update system tray tooltip with current state and task counts."""
        task_count = len(self.scheduler.store.all()) if self.scheduler else 0
        active_count = len([t for t in self.scheduler.store.all() if t.enabled]) if self.scheduler else 0
        paused_str = " (Paused)" if (self.scheduler and self.scheduler.is_paused) else ""
        tooltip = f"JUGNU Assistant{paused_str}\n{active_count} active / {task_count} total tasks"
        self.setToolTip(tooltip)

    def open_quick_ask(self):
        """Open the Quick Ask dialog."""
        dialog = QuickAskDialog(self.window)
        dialog.exec()

    def open_automation_studio(self):
        """Open the Automation Studio dialog."""
        if hasattr(self.window, "open_automation_dialog"):
            self.window.open_automation_dialog()

    def toggle_scheduler_pause(self):
        """Pause or resume the background scheduler."""
        if not self.scheduler:
            return
        if self.scheduler.is_paused:
            self.scheduler.resume()
            self.notify("Scheduler Resumed", "Background task automation is active.")
        else:
            self.scheduler.pause()
            self.notify("Scheduler Paused", "Background task automation paused.")
        self.build_menu()
        self.update_tooltip()

    def on_tray_activated(self, reason):
        """Handle tray icon click or trigger."""
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if self.window.isVisible() and not self.window.isMinimized():
                self.window.hide()
            else:
                self.window.restore_from_tray()

    def on_notification_clicked(self):
        """Handle user clicking on a desktop notification toast."""
        self.window.restore_from_tray()

    def notify(self, title: str, message: str, icon=QSystemTrayIcon.Information, timeout_ms: int = 5000):
        """Dispatch native OS desktop notification toast."""
        try:
            self.showMessage(title, message, icon, timeout_ms)
        except Exception:
            pass

    def quit_app(self):
        """Quit the application completely."""
        if self.scheduler:
            self.scheduler.stop()
        self.hide()
        QApplication.instance().quit()
