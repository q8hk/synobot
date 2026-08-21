"""Telegram delivery of durable task events."""

import inspect
from typing import Any, Awaitable, Callable, Iterable, Optional, Tuple

from .tasks.models import TaskEvent
from .tasks.service import TaskService


SendCallback = Callable[[int, str], Awaitable[Any]]


class TelegramNotificationService:
    """Deliver pending events to every recipient before acknowledging them."""

    def __init__(
        self,
        tasks: TaskService,
        notify_chat_ids: Iterable[int],
        *,
        bot: Optional[Any] = None,
        send: Optional[SendCallback] = None,
    ) -> None:
        recipients = tuple(dict.fromkeys(int(value) for value in notify_chat_ids))
        if send is None:
            if bot is None or not callable(getattr(bot, "send_message", None)):
                raise ValueError("bot or send callback is required")

            async def bot_send(chat_id: int, text: str) -> Any:
                result = bot.send_message(chat_id=chat_id, text=text)
                return await result if inspect.isawaitable(result) else result

            send = bot_send
        self._tasks = tasks
        self._recipients: Tuple[int, ...] = recipients
        self._send = send

    async def drain(self, limit: int = 100) -> int:
        """Deliver pending events in order and return acknowledged event count.

        Delivery stops on the first failure, preserving that event and all later
        events for a subsequent attempt.  An empty recipient list intentionally
        leaves events pending rather than silently discarding them.
        """
        if not self._recipients:
            return 0
        delivered = 0
        for event in self._tasks.pending_notifications(limit):
            message = self.format_event(event)
            try:
                for chat_id in self._recipients:
                    await self._send(chat_id, message)
            except Exception:
                break
            if not self._tasks.notification_delivered(event.event_id):
                break
            delivered += 1
        return delivered

    @staticmethod
    def format_event(event: TaskEvent) -> str:
        task = event.task_id
        if event.event_type == "created":
            return "Download task created: %s (%s)" % (task, event.new_status or "unknown")
        if event.event_type == "removed":
            return "Download task removed: %s" % task
        if event.event_type == "reappeared":
            return "Download task reappeared: %s (%s)" % (task, event.new_status or "unknown")
        if event.event_type in ("status", "status_changed"):
            return "Download task %s: %s → %s" % (
                task,
                event.old_status or "unknown",
                event.new_status or "unknown",
            )
        return "Download task %s: %s%s" % (
            task,
            event.event_type,
            " (%s)" % event.new_status if event.new_status else "",
        )
