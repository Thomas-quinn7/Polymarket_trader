"""
Generic Task Scheduler
Schedules one-shot tasks to fire at a specific UTC datetime.
Strategies can use this to time entries or exits without coupling
the infrastructure to any particular strategy's logic.
"""

from dataclasses import dataclass
from typing import Callable, Dict, List
from datetime import datetime, timezone

from utils.logger import logger


@dataclass
class ScheduledTask:
    """A task to be executed at a specific time."""

    task_id: str
    execute_at: datetime
    callback: Callable[[], None]
    label: str = ""


class TaskScheduler:
    """
    In-process scheduler for one-shot time-based callbacks.

    Usage:
        scheduler = TaskScheduler()
        scheduler.schedule("exit-pos-123", execute_at=dt, callback=fn)
        ready = scheduler.pop_ready()   # call each loop iteration
        for task in ready:
            task.callback()
    """

    def __init__(self) -> None:
        self._tasks: Dict[str, ScheduledTask] = {}

    def schedule(
        self,
        task_id: str,
        execute_at: datetime,
        callback: Callable[[], None],
        label: str = "",
    ) -> bool:
        """
        Register a task to fire at execute_at (UTC).
        Returns False if execute_at is already in the past.
        """
        now = datetime.now(timezone.utc)
        if execute_at <= now:
            logger.warning(
                "TaskScheduler: %s is already past (%s) — not scheduled",
                task_id,
                execute_at.isoformat(),
            )
            return False
        self._tasks[task_id] = ScheduledTask(
            task_id=task_id,
            execute_at=execute_at,
            callback=callback,
            label=label,
        )
        delay = (execute_at - now).total_seconds()
        logger.debug("TaskScheduler: scheduled %s in %.1fs (%s)", task_id, delay, label)
        return True

    def cancel(self, task_id: str) -> bool:
        """Remove a scheduled task. Returns True if it existed."""
        return self._tasks.pop(task_id, None) is not None

    def pop_ready(self) -> List[ScheduledTask]:
        """
        Return and remove all tasks whose execute_at has passed.
        Call once per trading-loop iteration.
        """
        now = datetime.now(timezone.utc)
        ready = [t for t in self._tasks.values() if now >= t.execute_at]
        for t in ready:
            del self._tasks[t.task_id]
            logger.debug("TaskScheduler: task %s ready (%s)", t.task_id, t.label)
        return ready

    @property
    def pending_count(self) -> int:
        return len(self._tasks)

    def clear(self) -> None:
        self._tasks.clear()
