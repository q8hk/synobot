"""Task reconciliation independent of the polling transport."""

from typing import Iterable, List, Set

from .models import Task, TaskEvent
from .repository import SQLiteTaskRepository


class TaskService:
    def __init__(self, repository: SQLiteTaskRepository) -> None:
        self.repository = repository

    def reconcile(self, observed_tasks: Iterable[Task]) -> List[TaskEvent]:
        observed = list(observed_tasks)
        ids: Set[str] = set()
        events: List[TaskEvent] = []
        for task in observed:
            if task.task_id in ids:
                raise ValueError("duplicate observed task id: %s" % task.task_id)
            ids.add(task.task_id)
            event = self.repository.upsert(task)
            if event is not None:
                events.append(event)
        for existing in self.repository.list():
            if existing.task_id not in ids:
                event = self.repository.mark_removed(existing.task_id)
                if event is not None:
                    events.append(event)
        return events

    def pending_notifications(self, limit: int = 100) -> List[TaskEvent]:
        return self.repository.pending_events(limit)

    def notification_delivered(self, event_id: int) -> bool:
        return self.repository.mark_notification_delivered(event_id)
