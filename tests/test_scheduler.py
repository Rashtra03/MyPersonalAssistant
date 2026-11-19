"""Unit and integration test suite for JUGNU's Background Task Scheduler and System Tray Daemon.

Covers cron evaluation, next execution calculations, TaskStore atomic persistence,
BackgroundScheduler daemon execution loops, CLI schedule commands, and PySide6 UI dialogs.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

import jugnu_core as core
from scheduler import (
    BackgroundScheduler,
    CronEvaluator,
    CronField,
    ScheduledTask,
    TaskStore,
)
from tray_daemon import JugnuTrayIcon, QuickAskDialog, create_fallback_tray_icon
from automation_dialog import AutomationDialog


# ---------- CronEvaluator Unit Tests ----------

def test_cron_field_parsing_and_matching():
    field = CronField("1,15,30-32,*/20", 0, 59, "minute")
    assert field.matches(1)
    assert field.matches(15)
    assert field.matches(30)
    assert field.matches(31)
    assert field.matches(32)
    assert field.matches(0)
    assert field.matches(20)
    assert field.matches(40)
    assert not field.matches(2)
    assert not field.matches(59)


def test_cron_field_invalid_values():
    with pytest.raises(ValueError):
        CronField("60", 0, 59, "minute")

    with pytest.raises(ValueError):
        CronField("10-5", 0, 59, "minute")

    with pytest.raises(ValueError):
        CronField("*/0", 0, 59, "minute")

    with pytest.raises(ValueError):
        CronField("abc", 0, 59, "minute")


def test_cron_presets():
    e_daily = CronEvaluator("@daily")
    assert e_daily.expression == "0 0 * * *"

    e_hourly = CronEvaluator("@hourly")
    assert e_hourly.expression == "0 * * * *"

    e_weekly = CronEvaluator("@weekly")
    assert e_weekly.expression == "0 0 * * 0"

    e_monthly = CronEvaluator("@monthly")
    assert e_monthly.expression == "0 0 1 * *"

    e_yearly = CronEvaluator("@yearly")
    assert e_yearly.expression == "0 0 1 1 *"


def test_cron_natural_intervals():
    e1 = CronEvaluator("every 15 minutes")
    assert e1.expression == "*/15 * * * *"

    e2 = CronEvaluator("every 2 hours")
    assert e2.expression == "0 */2 * * *"

    e3 = CronEvaluator("daily at 09:30")
    assert e3.expression == "30 9 * * *"

    e4 = CronEvaluator("weekdays at 18:00")
    assert e4.expression == "0 18 * * 1-5"


def test_cron_invalid_expressions():
    with pytest.raises(ValueError):
        CronEvaluator("* * *")  # Too few fields

    with pytest.raises(ValueError):
        CronEvaluator("* * * * * *")  # Too many fields


def test_cron_matches():
    evaluator = CronEvaluator("30 9 * * 1-5")  # Weekdays at 09:30

    # 2026-11-16 is a Monday (1)
    dt_match = datetime(2026, 11, 16, 9, 30, 0)
    assert evaluator.matches(dt_match)

    # 09:31 does not match
    dt_no_match = datetime(2026, 11, 16, 9, 31, 0)
    assert not evaluator.matches(dt_no_match)

    # 2026-11-15 is Sunday (0), so it shouldn't match
    dt_sunday = datetime(2026, 11, 15, 9, 30, 0)
    assert not evaluator.matches(dt_sunday)


def test_cron_next_run_after():
    evaluator = CronEvaluator("0 9 * * *")  # Daily at 09:00
    base = datetime(2026, 11, 16, 8, 15, 0)
    nxt = evaluator.next_run_after(base)
    assert nxt == datetime(2026, 11, 16, 9, 0, 0)

    # If already past 9:00 today, should be tomorrow at 9:00
    base_past = datetime(2026, 11, 16, 9, 30, 0)
    nxt_tomorrow = evaluator.next_run_after(base_past)
    assert nxt_tomorrow == datetime(2026, 11, 17, 9, 0, 0)


def test_cron_describe():
    assert "15 minutes" in CronEvaluator("*/15 * * * *").describe()
    assert "09:00" in CronEvaluator("0 9 * * *").describe()
    assert "weekday" in CronEvaluator("0 10 * * 1-5").describe().lower()
    assert "Sunday" in CronEvaluator("0 0 * * 0").describe()


# ---------- ScheduledTask Model Tests ----------

def test_scheduled_task_model():
    task = ScheduledTask(
        id="t1",
        title="Morning News",
        cron_expression="0 9 * * *",
        prompt="Tell me top news",
        persona="concise",
    )
    assert task.enabled is True
    assert task.last_status == "idle"
    assert task.next_run is not None

    d = task.to_dict()
    assert d["id"] == "t1"
    assert d["title"] == "Morning News"
    assert d["cron_expression"] == "0 9 * * *"

    restored = ScheduledTask.from_dict(d)
    assert restored.id == task.id
    assert restored.title == task.title
    assert restored.cron_expression == task.cron_expression
    assert restored.persona == "concise"


def test_scheduled_task_is_due():
    task = ScheduledTask(
        id="t2",
        title="Check",
        cron_expression="0 9 * * *",
        prompt="Ping",
    )
    # Target next_run set to 1 hour in the past
    past_dt = datetime.now() - timedelta(hours=1)
    task.next_run = past_dt.isoformat()
    assert task.is_due(datetime.now()) is True

    # When disabled, should never be due
    task.enabled = False
    assert task.is_due(datetime.now()) is False

    # When next_run is in the future
    task.enabled = True
    future_dt = datetime.now() + timedelta(hours=2)
    task.next_run = future_dt.isoformat()
    assert task.is_due(datetime.now()) is False


# ---------- TaskStore Tests ----------

def test_task_store_crud(tmp_path):
    fpath = str(tmp_path / "test_tasks.json")
    store = TaskStore(fpath)
    assert store.all() == []

    # Add task
    t1 = store.add("Daily Digest", "0 9 * * *", "Summarize notes", persona="default")
    assert t1.id in [t.id for t in store.all()]
    assert os.path.exists(fpath)

    # Get task
    fetched = store.get(t1.id)
    assert fetched is not None
    assert fetched.title == "Daily Digest"

    # Update task
    updated = store.update(t1.id, title="Morning Daily Digest", cron_expression="30 8 * * *")
    assert updated.title == "Morning Daily Digest"
    assert updated.cron_expression == "30 8 * * *"

    # Toggle task
    toggled = store.toggle(t1.id)
    assert toggled.enabled is False
    toggled_again = store.toggle(t1.id)
    assert toggled_again.enabled is True

    # Reload from disk
    new_store = TaskStore(fpath)
    assert len(new_store.all()) == 1
    assert new_store.get(t1.id).title == "Morning Daily Digest"

    # Delete task
    assert store.delete(t1.id) is True
    assert store.all() == []
    assert new_store.load() == []


# ---------- BackgroundScheduler Daemon Tests ----------

def test_background_scheduler_lifecycle(tmp_path):
    fpath = str(tmp_path / "sched_tasks.json")
    store = TaskStore(fpath)
    scheduler = BackgroundScheduler(store, check_interval=0.1)

    assert not scheduler.is_running
    scheduler.start()
    assert scheduler.is_running
    assert not scheduler.is_paused

    scheduler.pause()
    assert scheduler.is_paused

    scheduler.resume()
    assert not scheduler.is_paused

    scheduler.stop()
    assert not scheduler.is_running


def test_background_scheduler_execution(tmp_path):
    fpath = str(tmp_path / "sched_tasks.json")
    store = TaskStore(fpath)
    # Add a task whose next_run is explicitly set in the past
    task = store.add("Health Check", "*/5 * * * *", "Check system")
    task.next_run = (datetime.now() - timedelta(minutes=1)).isoformat()
    store.save()

    completed_event = threading.Event()
    results = []

    def mock_executor(t):
        results.append((t.id, t.prompt))
        completed_event.set()
        return "System OK", False

    scheduler = BackgroundScheduler(store, check_interval=0.05, executor_fn=mock_executor)
    scheduler.start()

    # Wait for execution
    assert completed_event.wait(timeout=3.0)
    scheduler.stop()

    assert len(results) == 1
    assert results[0][0] == task.id
    refreshed = store.get(task.id)
    assert refreshed.last_status == "success"
    assert "System OK" in (refreshed.last_output or "")
    assert refreshed.last_run is not None


def test_background_scheduler_manual_trigger(tmp_path):
    fpath = str(tmp_path / "sched_tasks.json")
    store = TaskStore(fpath)
    task = store.add("Manual Run Test", "0 0 1 1 *", "Run this immediately")

    completed_event = threading.Event()

    def mock_executor(t):
        completed_event.set()
        return "Manual success", False

    scheduler = BackgroundScheduler(store, check_interval=1.0, executor_fn=mock_executor)
    assert scheduler.trigger_task_now(task.id) is True
    assert completed_event.wait(timeout=3.0)

    refreshed = store.get(task.id)
    assert refreshed.last_status == "success"
    assert "Manual success" in refreshed.last_output


# ---------- CLI Schedule Command Tests ----------

def test_cli_schedule_commands(monkeypatch, tmp_path, capsys):
    import assistant
    tasks_file = str(tmp_path / "cli_tasks.json")
    monkeypatch.setattr("scheduler.DEFAULT_TASKS_FILE", tasks_file)

    store = TaskStore(tasks_file)
    store.add("Daily Brief", "0 9 * * *", "Briefing prompt")

    # Mock inputs: list tasks, then bye
    inputs = iter(["/schedule list", "/schedule toggle 1", "bye"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    assistant.run_assistant()
    captured = capsys.readouterr().out
    assert "Daily Brief" in captured
    assert "0 9 * * *" in captured
    assert "disabled" in captured.lower() or "enabled" in captured.lower()


# ---------- Qt UI Tests ----------

@pytest.fixture
def qt_window(qtbot, tmp_path, monkeypatch):
    import desktop_app
    history_file = str(tmp_path / "jugnu_test_history.json")
    settings_file = str(tmp_path / "jugnu_test_settings.json")
    tasks_file = str(tmp_path / "jugnu_test_tasks.json")

    monkeypatch.setattr("jugnu_core.HISTORY_FILE", history_file)
    monkeypatch.setattr("jugnu_core.SETTINGS_FILE", settings_file)
    monkeypatch.setattr("jugnu_core.TASKS_FILE", tasks_file)

    win = desktop_app.JugnuWindow(history_file=history_file, settings_file=settings_file)
    qtbot.addWidget(win)
    yield win
    win.close()


def test_desktop_automation_dialog_flow(qt_window, qtbot):
    # Click automation button on header
    assert hasattr(qt_window, "auto_btn")
    qt_window.open_automation_dialog()
    dialog = qt_window.automation_dialog
    assert dialog is not None
    qtbot.addWidget(dialog)

    # Initial dialog state
    assert dialog.isVisible()
    assert dialog.task_list is not None

    # Fill form to add a task
    dialog.on_new_task()
    dialog.title_edit.setText("Evening Sync")
    dialog.cron_edit.setText("0 18 * * 1-5")
    dialog.prompt_edit.setPlainText("Give me an evening summary of accomplishments.")
    dialog.on_save()

    # Verify task was added to store
    tasks = qt_window.task_store.all()
    assert any(t.title == "Evening Sync" for t in tasks)

    # Toggle task
    dialog.on_toggle_enabled()
    t = next(t for t in qt_window.task_store.all() if t.title == "Evening Sync")
    assert t.enabled is False

    dialog.close()


def test_tray_icon_and_menu(qt_window):
    icon = qt_window.tray_icon
    if icon is None:
        icon = JugnuTrayIcon(qt_window, qt_window.scheduler)

    assert icon is not None
    assert icon.menu is not None
    actions = [a.text() for a in icon.menu.actions()]
    assert any("Open JUGNU" in a for a in actions)
    assert any("Quick Ask" in a for a in actions)
    assert any("Automation Studio" in a for a in actions)

    # Test notification dispatch does not crash
    icon.notify("Test Notification", "JUGNU test message")

    # Test pause toggle
    initial_paused = qt_window.scheduler.is_paused
    icon.toggle_scheduler_pause()
    assert qt_window.scheduler.is_paused != initial_paused
    icon.toggle_scheduler_pause()
    assert qt_window.scheduler.is_paused == initial_paused


def test_fallback_tray_icon_generation():
    icon = create_fallback_tray_icon()
    assert not icon.isNull()
