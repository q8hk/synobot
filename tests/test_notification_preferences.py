import sqlite3
from datetime import datetime, timezone

import pytest

from synobot.notifications import TelegramNotificationService
from synobot.tasks import NotificationPreference, SQLiteTaskRepository, Task, TaskService


def test_preferences_default_enabled_and_are_durable(tmp_path):
    path = tmp_path / "tasks.db"
    first = TaskService(SQLiteTaskRepository(path))
    assert first.notification_preference(42) == NotificationPreference(42)
    saved = first.set_notification_preference(
        42, enabled=False, quiet_start="22:30", quiet_end="07:15",
        timezone_name="Asia/Kuwait",
    )
    assert not saved.enabled
    first.repository.close()

    second = TaskService(SQLiteTaskRepository(path))
    assert second.notification_preference(42) == saved


def test_quiet_hours_support_daytime_overnight_and_timezones():
    noon_utc = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
    assert not NotificationPreference(1, True, "14:00", "16:00", "Asia/Kuwait").allows(noon_utc)
    overnight = NotificationPreference(1, True, "22:00", "07:00", "UTC")
    assert not overnight.allows(datetime(2026, 8, 21, 23, 0, tzinfo=timezone.utc))
    assert overnight.allows(noon_utc)
    assert NotificationPreference(1, True, "00:00", "00:00").allows(noon_utc)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"quiet_start": "22:00"},
        {"quiet_start": "24:00", "quiet_end": "07:00"},
        {"quiet_start": "9:00", "quiet_end": "10:00"},
        {"timezone_name": "Not/A_Timezone"},
    ],
)
def test_invalid_preferences_are_rejected(kwargs):
    with pytest.raises(ValueError):
        NotificationPreference(1, **kwargs)


def test_schema_one_database_is_migrated_without_losing_metadata(tmp_path):
    path = tmp_path / "old.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE app_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    connection.execute("INSERT INTO app_metadata VALUES('schema_version', '1')")
    connection.execute("INSERT INTO app_metadata VALUES('custom', 'preserved')")
    connection.commit()
    connection.close()

    repository = SQLiteTaskRepository(path)
    assert repository.get_metadata("schema_version") == "2"
    assert repository.get_metadata("custom") == "preserved"
    assert repository.get_notification_preference(9) == NotificationPreference(9)


@pytest.mark.asyncio
async def test_delivery_obeys_muted_and_quiet_preferences(tmp_path):
    repository = SQLiteTaskRepository(tmp_path / "tasks.db")
    tasks = TaskService(repository)
    tasks.set_notification_preference(10, enabled=False)
    tasks.set_notification_preference(20, quiet_start="22:00", quiet_end="07:00")
    tasks.reconcile([Task("one", "One", 1, "owner", "downloading")])
    sends = []

    async def send(chat_id, text):
        sends.append((chat_id, text))

    service = TelegramNotificationService(tasks, [10, 20, 30], send=send)
    at = datetime(2026, 8, 21, 23, 0, tzinfo=timezone.utc)
    assert await service.drain(at=at) == 1
    assert [chat_id for chat_id, _ in sends] == [30]
    assert tasks.pending_notifications() == []
