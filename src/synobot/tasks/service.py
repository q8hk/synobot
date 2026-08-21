"""Task reconciliation independent of the polling transport."""

from datetime import datetime
from typing import Iterable, List, Set

from .models import NotificationPreference, Task, TaskEvent
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

    def history(self, limit: int = 20) -> List[TaskEvent]:
        return self.repository.recent_events(limit)

    def notification_delivered(self, event_id: int) -> bool:
        return self.repository.mark_notification_delivered(event_id)

    def notification_preference(self, user_id: int) -> NotificationPreference:
        return self.repository.get_notification_preference(user_id)

    def set_notification_preference(
        self,
        user_id: int,
        *,
        enabled: bool = True,
        quiet_start: str | None = None,
        quiet_end: str | None = None,
        timezone_name: str = "UTC",
    ) -> NotificationPreference:
        preference = NotificationPreference(
            int(user_id), enabled, quiet_start, quiet_end, timezone_name
        )
        return self.repository.set_notification_preference(preference)

    def notification_allowed(self, user_id: int, at: datetime | None = None) -> bool:
        return self.notification_preference(user_id).allows(at)
