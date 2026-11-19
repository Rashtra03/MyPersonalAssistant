"""Core scheduling and cron engine for JUGNU.

Provides a pure Python 5-field cron evaluator, persistent task data models,
atomic task storage, and a thread-safe background execution scheduler daemon.
"""

from __future__ import annotations

import ast
import json
import os
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

DEFAULT_TASKS_FILE = "jugnu_tasks.json"

# Standard cron presets
CRON_PRESETS: Dict[str, str] = {
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
}

# Day and Month name mappings
MONTH_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
}
DOW_NAMES = {
    "sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6
}
DOW_LABELS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


class CronField:
    """Represents a single field in a 5-field cron expression."""

    def __init__(self, spec: str, min_val: int, max_val: int, name: str, name_map: Optional[Dict[str, int]] = None):
        self.spec = str(spec).strip().lower()
        self.min_val = min_val
        self.max_val = max_val
        self.name = name
        self.name_map = name_map or {}
        self.values: Set[int] = self._parse(self.spec)

    def _replace_names(self, part: str) -> str:
        for name, val in self.name_map.items():
            part = re.sub(rf"\b{name}\b", str(val), part, flags=re.IGNORECASE)
        return part

    def _parse_range_or_step(self, item: str) -> Set[int]:
        item = self._replace_names(item)
        step = 1
        if "/" in item:
            parts = item.split("/")
            if len(parts) != 2:
                raise ValueError(f"Invalid step syntax in cron {self.name}: '{item}'")
            range_part, step_part = parts[0], parts[1]
            try:
                step = int(step_part)
                if step <= 0:
                    raise ValueError()
            except ValueError:
                raise ValueError(f"Step must be a positive integer in cron {self.name}: '{item}'")
        else:
            range_part = item

        if range_part == "*":
            start, end = self.min_val, self.max_val
        elif "-" in range_part:
            bounds = range_part.split("-")
            if len(bounds) != 2:
                raise ValueError(f"Invalid range in cron {self.name}: '{range_part}'")
            try:
                start, end = int(bounds[0]), int(bounds[1])
            except ValueError:
                raise ValueError(f"Range bounds must be integers in cron {self.name}: '{range_part}'")
            if start > end:
                raise ValueError(f"Range start must be <= end in cron {self.name}: '{range_part}'")
        else:
            try:
                start = end = int(range_part)
            except ValueError:
                raise ValueError(f"Invalid value in cron {self.name}: '{range_part}'")

        if start < self.min_val or end > self.max_val:
            raise ValueError(
                f"Value {range_part} out of range ({self.min_val}-{self.max_val}) for {self.name}"
            )

        return set(range(start, end + 1, step))

    def _parse(self, spec: str) -> Set[int]:
        if not spec:
            raise ValueError(f"Empty specification for cron {self.name}")
        values: Set[int] = set()
        for item in spec.split(","):
            item = item.strip()
            if not item:
                continue
            values.update(self._parse_range_or_step(item))
        if not values:
            raise ValueError(f"No valid values parsed for cron {self.name}: '{spec}'")
        return values

    def matches(self, val: int) -> bool:
        return val in self.values

    @property
    def is_wildcard(self) -> bool:
        return len(self.values) == (self.max_val - self.min_val + 1)


class CronEvaluator:
    """Parses standard 5-field cron specifications and computes next execution timestamps."""

    def __init__(self, expression: str):
        self.raw_expression = str(expression).strip()
        self.expression = self._normalize_expression(self.raw_expression)
        parts = self.expression.split()
        if len(parts) != 5:
            raise ValueError(
                f"Invalid cron expression '{self.raw_expression}': expected 5 fields (min hour dom mon dow), got {len(parts)}"
            )

        self.minute = CronField(parts[0], 0, 59, "minute")
        self.hour = CronField(parts[1], 0, 23, "hour")
        self.day_of_month = CronField(parts[2], 1, 31, "day_of_month")
        self.month = CronField(parts[3], 1, 12, "month", MONTH_NAMES)
        # Cron DOW standard: 0=Sun, 1=Mon, ..., 6=Sat, 7=Sun
        self.day_of_week = CronField(parts[4], 0, 7, "day_of_week", DOW_NAMES)
        # Normalize 7 to 0 (Sunday)
        if 7 in self.day_of_week.values:
            self.day_of_week.values.add(0)

    @classmethod
    def _normalize_expression(cls, expr: str) -> str:
        expr = expr.strip()
        lower = expr.lower()
        if lower in CRON_PRESETS:
            return CRON_PRESETS[lower]

        # Natural language helpers
        m_every_min = re.match(r"^every\s+(\d+)\s+min(?:ute)?s?$", lower)
        if m_every_min:
            n = int(m_every_min.group(1))
            return f"*/{n} * * * *"

        m_every_hour = re.match(r"^every\s+(\d+)\s+hours?$", lower)
        if m_every_hour:
            n = int(m_every_hour.group(1))
            return f"0 */{n} * * *"

        if lower in ("hourly", "every hour"):
            return "0 * * * *"

        m_daily_at = re.match(r"^(?:every\s+day|daily)\s+at\s+(\d{1,2}):(\d{2})$", lower)
        if m_daily_at:
            h, m = int(m_daily_at.group(1)), int(m_daily_at.group(2))
            return f"{m} {h} * * *"

        m_weekdays_at = re.match(r"^(?:every\s+weekday|weekdays)\s+at\s+(\d{1,2}):(\d{2})$", lower)
        if m_weekdays_at:
            h, m = int(m_weekdays_at.group(1)), int(m_weekdays_at.group(2))
            return f"{m} {h} * * 1-5"

        return expr

    def matches(self, dt: datetime) -> bool:
        """Check if the given datetime satisfies the cron rule."""
        if not self.minute.matches(dt.minute):
            return False
        if not self.hour.matches(dt.hour):
            return False
        if not self.month.matches(dt.month):
            return False

        # Day matching logic: standard POSIX cron specifies that if both
        # DOM and DOW are specified (neither is *), either matching qualifies.
        cron_dow = (dt.weekday() + 1) % 7  # 0=Sunday, 1=Monday, ..., 6=Saturday
        dom_matches = self.day_of_month.matches(dt.day)
        dow_matches = self.day_of_week.matches(cron_dow)

        if not self.day_of_month.is_wildcard and not self.day_of_week.is_wildcard:
            return dom_matches or dow_matches
        elif not self.day_of_month.is_wildcard:
            return dom_matches
        elif not self.day_of_week.is_wildcard:
            return dow_matches
        return True

    def next_run_after(self, dt: Optional[datetime] = None, max_days: int = 730) -> datetime:
        """Compute the next datetime strictly after `dt` that satisfies the cron schedule."""
        if dt is None:
            dt = datetime.now()

        # Start from the next minute, zeroing out seconds and microseconds
        current = dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
        end_horizon = current + timedelta(days=max_days)

        while current <= end_horizon:
            # Month check
            if not self.month.matches(current.month):
                # Jump to start of next month
                if current.month == 12:
                    current = current.replace(year=current.year + 1, month=1, day=1, hour=0, minute=0)
                else:
                    current = current.replace(month=current.month + 1, day=1, hour=0, minute=0)
                continue

            # Day check (DOM / DOW)
            cron_dow = (current.weekday() + 1) % 7
            dom_m = self.day_of_month.matches(current.day)
            dow_m = self.day_of_week.matches(cron_dow)
            day_matches = (
                (dom_m or dow_m)
                if (not self.day_of_month.is_wildcard and not self.day_of_week.is_wildcard)
                else (dom_m if not self.day_of_month.is_wildcard else (dow_m if not self.day_of_week.is_wildcard else True))
            )

            if not day_matches:
                # Advance to next day at 00:00
                current = (current + timedelta(days=1)).replace(hour=0, minute=0)
                continue

            # Hour check
            if not self.hour.matches(current.hour):
                # Advance to next hour at 00
                current = (current + timedelta(hours=1)).replace(minute=0)
                continue

            # Minute check
            if not self.minute.matches(current.minute):
                current += timedelta(minutes=1)
                continue

            return current

        raise ValueError(f"No execution found within {max_days} days for cron: '{self.raw_expression}'")

    def describe(self) -> str:
        """Produce a friendly human-readable description of the cron schedule."""
        expr = self.expression
        if expr == "* * * * *":
            return "Every minute"
        if re.match(r"^\*/(\d+)\s+\*\s+\*\s+\*\s+\*$", expr):
            m = re.match(r"^\*/(\d+)\s+\*\s+\*\s+\*\s+\*$", expr)
            return f"Every {m.group(1)} minutes"
        if expr == "0 * * * *":
            return "Every hour at minute 0"
        if re.match(r"^0\s+\*/(\d+)\s+\*\s+\*\s+\*$", expr):
            h = re.match(r"^0\s+\*/(\d+)\s+\*\s+\*\s+\*$", expr)
            return f"Every {h.group(1)} hours"
        if re.match(r"^(\d+)\s+(\d+)\s+\*\s+\*\s+\*$", expr):
            m, h = expr.split()[:2]
            return f"Every day at {int(h):02d}:{int(m):02d}"
        if re.match(r"^(\d+)\s+(\d+)\s+\*\s+\*\s+1-5$", expr):
            m, h = expr.split()[:2]
            return f"Every weekday (Mon-Fri) at {int(h):02d}:{int(m):02d}"
        if re.match(r"^(\d+)\s+(\d+)\s+\*\s+\*\s+0$", expr) or re.match(r"^(\d+)\s+(\d+)\s+\*\s+\*\s+7$", expr):
            m, h = expr.split()[:2]
            return f"Every Sunday at {int(h):02d}:{int(m):02d}"
        if re.match(r"^(\d+)\s+(\d+)\s+1\s+\*\s+\*$", expr):
            m, h = expr.split()[:2]
            return f"1st of every month at {int(h):02d}:{int(m):02d}"

        # General fallback description
        parts = expr.split()
        return f"Cron ({parts[0]} {parts[1]} {parts[2]} {parts[3]} {parts[4]})"


@dataclass
class ScheduledTask:
    """Represents a scheduled background task in JUGNU."""

    id: str
    title: str
    cron_expression: str
    prompt: str
    persona: str = "default"
    model: Optional[str] = None
    enabled: bool = True
    last_run: Optional[str] = None
    last_status: str = "idle"  # idle, running, success, failed
    last_output: Optional[str] = None
    next_run: Optional[str] = None
    created_at: Optional[str] = None
    target_chat_id: Optional[str] = None

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.next_run and self.enabled:
            self.update_next_run()

    def update_next_run(self, after_dt: Optional[datetime] = None) -> Optional[str]:
        """Recalculate next_run timestamp using the cron expression."""
        if not self.enabled:
            self.next_run = None
            return None
        try:
            evaluator = CronEvaluator(self.cron_expression)
            next_dt = evaluator.next_run_after(after_dt)
            self.next_run = next_dt.isoformat()
            return self.next_run
        except Exception:
            self.next_run = None
            return None

    def is_due(self, now_dt: Optional[datetime] = None) -> bool:
        """Check if the task is currently due for execution."""
        if not self.enabled:
            return False
        if not self.next_run:
            self.update_next_run(now_dt)
            if not self.next_run:
                return False
        if now_dt is None:
            now_dt = datetime.now()
        try:
            target = datetime.fromisoformat(self.next_run)
            return now_dt >= target
        except Exception:
            return False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ScheduledTask:
        return cls(
            id=data.get("id", uuid.uuid4().hex[:8]),
            title=data.get("title", "Untitled Task"),
            cron_expression=data.get("cron_expression", "0 9 * * *"),
            prompt=data.get("prompt", ""),
            persona=data.get("persona", "default"),
            model=data.get("model"),
            enabled=data.get("enabled", True),
            last_run=data.get("last_run"),
            last_status=data.get("last_status", "idle"),
            last_output=data.get("last_output"),
            next_run=data.get("next_run"),
            created_at=data.get("created_at"),
            target_chat_id=data.get("target_chat_id"),
        )


class TaskStore:
    """Thread-safe persistent task store with atomic file writes."""

    def __init__(self, filepath: Optional[str] = None):
        self.filepath = filepath or DEFAULT_TASKS_FILE
        self._lock = threading.Lock()
        self._tasks: Dict[str, ScheduledTask] = {}
        self.load()

    def load(self) -> List[ScheduledTask]:
        """Load tasks from disk."""
        with self._lock:
            self._tasks.clear()
            if not os.path.exists(self.filepath):
                return []
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and "id" in item:
                            task = ScheduledTask.from_dict(item)
                            self._tasks[task.id] = task
            except Exception:
                pass
            return list(self._tasks.values())

    def save(self) -> None:
        """Atomically persist tasks to disk."""
        with self._lock:
            data = [t.to_dict() for t in self._tasks.values()]
            tmp_path = f"{self.filepath}.tmp.{uuid.uuid4().hex[:6]}"
            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                os.replace(tmp_path, self.filepath)
            except Exception:
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
                raise

    def add(
        self,
        title: str,
        cron_expression: str,
        prompt: str,
        persona: str = "default",
        model: Optional[str] = None,
        enabled: bool = True,
        target_chat_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> ScheduledTask:
        """Register a new scheduled task."""
        # Validate cron expression upfront
        CronEvaluator(cron_expression)
        tid = task_id or uuid.uuid4().hex[:8]
        task = ScheduledTask(
            id=tid,
            title=title.strip() or "Scheduled Task",
            cron_expression=cron_expression.strip(),
            prompt=prompt.strip(),
            persona=persona,
            model=model,
            enabled=enabled,
            target_chat_id=target_chat_id,
        )
        task.update_next_run()
        with self._lock:
            self._tasks[task.id] = task
        self.save()
        return task

    def get(self, task_id: str) -> Optional[ScheduledTask]:
        with self._lock:
            return self._tasks.get(task_id)

    def update(self, task_id: str, **kwargs) -> Optional[ScheduledTask]:
        """Update fields of an existing task."""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            for key, val in kwargs.items():
                if hasattr(task, key):
                    setattr(task, key, val)
            if "cron_expression" in kwargs or "enabled" in kwargs:
                task.update_next_run()
        self.save()
        return task

    def delete(self, task_id: str) -> bool:
        """Remove a task by ID."""
        with self._lock:
            if task_id in self._tasks:
                del self._tasks[task_id]
                deleted = True
            else:
                deleted = False
        if deleted:
            self.save()
        return deleted

    def toggle(self, task_id: str) -> Optional[ScheduledTask]:
        """Toggle task enabled state."""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            task.enabled = not task.enabled
            task.update_next_run()
        self.save()
        return task

    def all(self) -> List[ScheduledTask]:
        with self._lock:
            return list(self._tasks.values())

    def get_due_tasks(self, now_dt: Optional[datetime] = None) -> List[ScheduledTask]:
        """Return all tasks currently due for execution."""
        if now_dt is None:
            now_dt = datetime.now()
        with self._lock:
            return [t for t in self._tasks.values() if t.is_due(now_dt)]


class BackgroundScheduler:
    """Thread-safe proactive background scheduler daemon."""

    def __init__(
        self,
        store: TaskStore,
        check_interval: float = 5.0,
        executor_fn: Optional[Callable[[ScheduledTask], Tuple[str, bool]]] = None,
    ):
        self.store = store
        self.check_interval = max(0.05, float(check_interval))
        self.executor_fn = executor_fn
        self._running = False
        self._paused = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_tick: Optional[datetime] = None

        # Observer hooks
        self.on_task_started: Optional[Callable[[ScheduledTask], None]] = None
        self.on_task_finished: Optional[Callable[[ScheduledTask, str, bool], None]] = None
        self.on_notification: Optional[Callable[[str, str], None]] = None

    @property
    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    @property
    def is_paused(self) -> bool:
        return self._paused

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def start(self) -> None:
        """Start the background daemon thread."""
        if self.is_running:
            return
        self._running = True
        self._stop_event.clear()
        self._last_tick = datetime.now()
        self._thread = threading.Thread(target=self._run_loop, name="JugnuSchedulerDaemon", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        """Stop the background daemon thread."""
        self._running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None

    def trigger_task_now(self, task_id: str) -> bool:
        """Manually trigger immediate execution of a task in a background worker."""
        task = self.store.get(task_id)
        if not task:
            return False

        def worker():
            self._execute_single_task(task, manual=True)

        t = threading.Thread(target=worker, name=f"ManualTaskWorker-{task.id}", daemon=True)
        t.start()
        return True

    def _execute_single_task(self, task: ScheduledTask, manual: bool = False) -> None:
        now_str = datetime.now().isoformat()
        self.store.update(task.id, last_status="running", last_run=now_str)

        if self.on_task_started:
            try:
                self.on_task_started(task)
            except Exception:
                pass

        output = ""
        is_error = False

        try:
            if self.executor_fn:
                output, is_error = self.executor_fn(task)
            else:
                # Default fallback executor calling Ollama directly
                import jugnu_core as core
                chat = {
                    "messages": [{"role": "user", "content": task.prompt}],
                    "persona": task.persona or "default",
                }
                answer, err = core.ask_ollama(chat, "en", persona=task.persona)
                output = answer
                is_error = err
        except Exception as e:
            output = f"Execution error: {e}"
            is_error = True

        status = "failed" if is_error else "success"
        snippet = (output[:160] + "…") if len(output) > 160 else output
        self.store.update(
            task.id,
            last_status=status,
            last_output=snippet,
            last_run=now_str,
        )
        # Advance next_run time
        task.update_next_run(datetime.now())
        self.store.update(task.id, next_run=task.next_run)

        if self.on_task_finished:
            try:
                self.on_task_finished(task, output, is_error)
            except Exception:
                pass

        if self.on_notification:
            try:
                title = f"Task: {task.title}"
                msg = f"✓ Completed: {snippet}" if not is_error else f"⚠ Error: {snippet}"
                self.on_notification(title, msg)
            except Exception:
                pass

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            now = datetime.now()

            # Handle clock jump (e.g. system hibernate/wake)
            if self._last_tick and (now - self._last_tick) > timedelta(minutes=5):
                # Clock jumped forward significantly; due tasks will be triggered once
                pass
            self._last_tick = now

            if not self._paused:
                due_tasks = self.store.get_due_tasks(now)
                for task in due_tasks:
                    if self._stop_event.is_set():
                        break
                    # Spawn worker thread per due task to avoid delaying other schedules
                    t = threading.Thread(
                        target=self._execute_single_task,
                        args=(task, False),
                        name=f"CronWorker-{task.id}",
                        daemon=True,
                    )
                    t.start()

            # Sleep until next check or until stop requested
            self._stop_event.wait(timeout=self.check_interval)
