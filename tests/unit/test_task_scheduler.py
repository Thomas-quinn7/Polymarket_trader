"""
Unit tests for utils/execution_timer.py — TaskScheduler and ScheduledTask.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from utils.execution_timer import TaskScheduler, ScheduledTask


def _future(seconds=60) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


def _past(seconds=60) -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=seconds)


class TestSchedule:
    def test_schedule_future_returns_true(self):
        scheduler = TaskScheduler()
        result = scheduler.schedule("t1", execute_at=_future(60), callback=lambda: None)
        assert result is True

    def test_schedule_past_returns_false(self):
        scheduler = TaskScheduler()
        result = scheduler.schedule("t1", execute_at=_past(60), callback=lambda: None)
        assert result is False

    def test_schedule_adds_to_pending(self):
        scheduler = TaskScheduler()
        scheduler.schedule("t1", execute_at=_future(60), callback=lambda: None)
        assert scheduler.pending_count == 1

    def test_schedule_past_does_not_add_to_pending(self):
        scheduler = TaskScheduler()
        scheduler.schedule("t1", execute_at=_past(1), callback=lambda: None)
        assert scheduler.pending_count == 0

    def test_schedule_multiple_tasks(self):
        scheduler = TaskScheduler()
        for i in range(5):
            scheduler.schedule(f"t{i}", execute_at=_future(60 + i), callback=lambda: None)
        assert scheduler.pending_count == 5

    def test_overwrite_same_id(self):
        scheduler = TaskScheduler()
        scheduler.schedule("t1", execute_at=_future(60), callback=lambda: None)
        scheduler.schedule("t1", execute_at=_future(120), callback=lambda: None)
        assert scheduler.pending_count == 1

    def test_label_stored(self):
        scheduler = TaskScheduler()
        scheduler.schedule("t1", execute_at=_future(60), callback=lambda: None, label="my-label")
        assert scheduler._tasks["t1"].label == "my-label"


class TestCancel:
    def test_cancel_existing_returns_true(self):
        scheduler = TaskScheduler()
        scheduler.schedule("t1", execute_at=_future(60), callback=lambda: None)
        assert scheduler.cancel("t1") is True

    def test_cancel_removes_from_pending(self):
        scheduler = TaskScheduler()
        scheduler.schedule("t1", execute_at=_future(60), callback=lambda: None)
        scheduler.cancel("t1")
        assert scheduler.pending_count == 0

    def test_cancel_nonexistent_returns_false(self):
        scheduler = TaskScheduler()
        assert scheduler.cancel("ghost") is False

    def test_cancel_does_not_affect_other_tasks(self):
        scheduler = TaskScheduler()
        scheduler.schedule("t1", execute_at=_future(60), callback=lambda: None)
        scheduler.schedule("t2", execute_at=_future(60), callback=lambda: None)
        scheduler.cancel("t1")
        assert scheduler.pending_count == 1
        assert "t2" in scheduler._tasks


class TestPopReady:
    def test_no_tasks_ready_in_future(self):
        scheduler = TaskScheduler()
        scheduler.schedule("t1", execute_at=_future(60), callback=lambda: None)
        ready = scheduler.pop_ready()
        assert ready == []
        assert scheduler.pending_count == 1

    def test_past_task_is_ready(self):
        """Manually insert a past task to simulate time passing."""
        scheduler = TaskScheduler()
        cb = MagicMock()
        # Directly inject an already-past task
        scheduler._tasks["t1"] = ScheduledTask(
            task_id="t1",
            execute_at=_past(1),
            callback=cb,
            label="test",
        )
        ready = scheduler.pop_ready()
        assert len(ready) == 1
        assert ready[0].task_id == "t1"

    def test_ready_task_removed_from_pending(self):
        scheduler = TaskScheduler()
        scheduler._tasks["t1"] = ScheduledTask(
            task_id="t1", execute_at=_past(1), callback=lambda: None
        )
        scheduler.pop_ready()
        assert scheduler.pending_count == 0

    def test_only_past_tasks_returned(self):
        scheduler = TaskScheduler()
        scheduler._tasks["past"] = ScheduledTask(
            task_id="past", execute_at=_past(1), callback=lambda: None
        )
        scheduler.schedule("future", execute_at=_future(60), callback=lambda: None)
        ready = scheduler.pop_ready()
        assert len(ready) == 1
        assert ready[0].task_id == "past"
        assert scheduler.pending_count == 1

    def test_multiple_ready_tasks_all_returned(self):
        scheduler = TaskScheduler()
        for i in range(3):
            scheduler._tasks[f"t{i}"] = ScheduledTask(
                task_id=f"t{i}", execute_at=_past(i + 1), callback=lambda: None
            )
        ready = scheduler.pop_ready()
        assert len(ready) == 3
        assert scheduler.pending_count == 0

    def test_callback_is_correct_object(self):
        scheduler = TaskScheduler()
        cb = MagicMock()
        scheduler._tasks["t1"] = ScheduledTask(
            task_id="t1", execute_at=_past(1), callback=cb
        )
        ready = scheduler.pop_ready()
        assert ready[0].callback is cb


class TestClear:
    def test_clear_removes_all(self):
        scheduler = TaskScheduler()
        for i in range(5):
            scheduler.schedule(f"t{i}", execute_at=_future(60), callback=lambda: None)
        scheduler.clear()
        assert scheduler.pending_count == 0

    def test_clear_empty_scheduler_is_safe(self):
        scheduler = TaskScheduler()
        scheduler.clear()
        assert scheduler.pending_count == 0


class TestPendingCount:
    def test_empty_is_zero(self):
        assert TaskScheduler().pending_count == 0

    def test_count_increments_with_schedule(self):
        scheduler = TaskScheduler()
        scheduler.schedule("t1", execute_at=_future(10), callback=lambda: None)
        scheduler.schedule("t2", execute_at=_future(20), callback=lambda: None)
        assert scheduler.pending_count == 2


class TestScheduledTask:
    def test_task_dataclass_fields(self):
        cb = lambda: None
        task = ScheduledTask(
            task_id="t1",
            execute_at=_future(30),
            callback=cb,
            label="my-task",
        )
        assert task.task_id == "t1"
        assert task.callback is cb
        assert task.label == "my-task"

    def test_label_defaults_to_empty_string(self):
        task = ScheduledTask(
            task_id="t1",
            execute_at=_future(30),
            callback=lambda: None,
        )
        assert task.label == ""
