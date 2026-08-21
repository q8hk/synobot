"""Task reconciliation independent of the polling transport."""

from collections import Counter
from datetime import datetime
from typing import Iterable, List, Optional, Sequence, Set

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

    def destination_preference(self, user_id: int) -> Optional[str]:
        return self.repository.get_destination_preference(user_id)

    def set_destination_preference(
        self, user_id: int, destination: Optional[str]
    ) -> Optional[str]:
        return self.repository.set_destination_preference(user_id, destination)

    def record_destination_use(self, user_id: int, destination: str) -> None:
        self.repository.record_destination_use(user_id, destination)

    def rank_destinations(
        self,
        user_id: int,
        observed: Iterable[str],
        fallbacks: Sequence[str],
    ) -> List[str]:
        """Rank canonical destinations using DSM frequency and durable user history."""
        observed_counts = Counter(value for value in observed if value)
        usage = self.repository.destination_usage(user_id)
        preference = self.destination_preference(user_id)
        scores: dict[str, int] = {}
        for destination, count in observed_counts.items():
            scores[destination] = scores.get(destination, 0) + count * 100
        for index, (destination, count) in enumerate(usage):
            scores[destination] = (
                scores.get(destination, 0) + count * 25 + max(0, 20 - index)
            )
        if preference:
            scores[preference] = scores.get(preference, 0) + 50
        for index, destination in enumerate(fallbacks):
            scores[destination] = scores.get(destination, 0) + max(1, 10 - index)
        return sorted(scores, key=lambda value: (-scores[value], value.casefold()))
