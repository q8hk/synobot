import asyncio
from datetime import datetime, timezone

import pytest

from synobot.monitoring import AsyncTaskMonitor
from synobot.notifications import TelegramNotificationService
from synobot.tasks.models import TaskEvent


class FakeCore:
    def __init__(self, outcomes=()):
        self.outcomes = list(outcomes)
        self.calls = 0

    def synchronize_tasks(self):
        self.calls += 1
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
        return []


@pytest.mark.asyncio
async def test_monitor_reports_outage_once_and_recovery_once():
    core = FakeCore([RuntimeError("offline"), RuntimeError("still offline"), None])
    messages = []

    async def notify(message):
        messages.append(message)

    monitor = AsyncTaskMonitor(core, status_callback=notify)
    assert not await monitor.poll_once()
    assert not await monitor.poll_once()
    assert await monitor.poll_once()

    assert messages == ["DSM connection lost", "DSM connection recovered"]
    assert monitor.health.dsm_connected
    assert monitor.health.last_error is None
    assert isinstance(monitor.health.last_success, datetime)


@pytest.mark.asyncio
async def test_successful_poll_drains_notifications_without_affecting_health():
    drained = []

    async def drain():
        drained.append(True)
        raise RuntimeError("Telegram temporarily unavailable")

    monitor = AsyncTaskMonitor(FakeCore(), notification_callback=drain)

    assert await monitor.poll_once()
    assert drained == [True]
    assert monitor.health.dsm_connected


@pytest.mark.asyncio
async def test_monitor_lifecycle_and_backoff_are_cancellation_safe():
    core = FakeCore([RuntimeError("offline")])
    delays = []
    sleeping = asyncio.Event()

    async def sleep(delay):
        delays.append(delay)
        sleeping.set()
        await asyncio.Event().wait()

    monitor = AsyncTaskMonitor(core, interval=2, max_backoff=8, sleep=sleep)
    first = monitor.start()
    assert monitor.start() is first
    await sleeping.wait()
    assert delays == [4]
    assert monitor.health.running
    await monitor.stop()
    assert not monitor.health.running
    await monitor.stop()


class FakeTasks:
    def __init__(self, events):
        self.events = events
        self.marked = []

    def pending_notifications(self, limit=100):
        return self.events[:limit]

    def notification_delivered(self, event_id):
        self.marked.append(event_id)
        return True


def event(event_id, kind, old=None, new=None):
    return TaskEvent(
        event_id, "task-%s" % event_id, kind, old, new, datetime.now(timezone.utc)
    )


@pytest.mark.asyncio
async def test_notifications_mark_only_after_every_recipient_succeeds():
    tasks = FakeTasks([event(1, "created", new="downloading")])
    sends = []

    async def send(chat_id, text):
        sends.append((chat_id, text))

    service = TelegramNotificationService(tasks, [10, 20, 10], send=send)
    assert await service.drain() == 1
    assert [chat for chat, _ in sends] == [10, 20]
    assert tasks.marked == [1]
    assert "created" in sends[0][1]


@pytest.mark.asyncio
async def test_notification_failure_leaves_event_pending_and_stops_drain():
    tasks = FakeTasks([event(1, "status", "waiting", "downloading"), event(2, "removed")])

    async def send(chat_id, text):
        if chat_id == 20:
            raise RuntimeError("Telegram unavailable")

    service = TelegramNotificationService(tasks, [10, 20], send=send)
    assert await service.drain() == 0
    assert tasks.marked == []


def test_event_formatting_covers_durable_event_types():
    assert "created" in TelegramNotificationService.format_event(event(1, "created", new="waiting"))
    assert "waiting → downloading" in TelegramNotificationService.format_event(
        event(2, "status_changed", "waiting", "downloading")
    )
    assert "removed" in TelegramNotificationService.format_event(event(3, "removed"))
    assert "reappeared" in TelegramNotificationService.format_event(
        event(4, "reappeared", new="seeding")
    )


@pytest.mark.asyncio
async def test_empty_recipient_list_does_not_discard_events():
    tasks = FakeTasks([event(1, "created")])

    async def send(chat_id, text):
        raise AssertionError("must not send")

    service = TelegramNotificationService(tasks, [], send=send)
    assert await service.drain() == 0
    assert tasks.marked == []
