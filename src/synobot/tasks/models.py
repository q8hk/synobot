"""Persistent task models, independent from DSM and Telegram adapters."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Task:
    task_id: str
    title: str
    size_bytes: int
    owner: str
    status: str
    downloaded_bytes: int = 0
    uploaded_bytes: int = 0
    download_speed: int = 0
    upload_speed: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    removed_at: Optional[datetime] = None


@dataclass(frozen=True)
class TaskEvent:
    event_id: int
    task_id: str
    event_type: str
    old_status: Optional[str]
    new_status: Optional[str]
    observed_at: datetime
    notification_state: str = "pending"
    delivered_at: Optional[datetime] = None


@dataclass(frozen=True)
class NotificationPreference:
    """Persisted notification policy for one Telegram user."""

    user_id: int
    enabled: bool = True
    quiet_start: Optional[str] = None
    quiet_end: Optional[str] = None
    timezone_name: str = "UTC"

    def __post_init__(self) -> None:
        if (self.quiet_start is None) != (self.quiet_end is None):
            raise ValueError("quiet_start and quiet_end must be set together")
        for value in (self.quiet_start, self.quiet_end):
            if value is not None:
                try:
                    parsed = datetime.strptime(value, "%H:%M")
                except ValueError as error:
                    raise ValueError("quiet hours must use HH:MM") from error
                if parsed.strftime("%H:%M") != value:
                    raise ValueError("quiet hours must use HH:MM")
        try:
            ZoneInfo(self.timezone_name)
        except (KeyError, ValueError) as error:
            raise ValueError("unknown timezone: %s" % self.timezone_name) from error

    def allows(self, instant: Optional[datetime] = None) -> bool:
        if not self.enabled:
            return False
        if self.quiet_start is None or self.quiet_end is None:
            return True
        current = instant or utc_now()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        local_time = current.astimezone(ZoneInfo(self.timezone_name)).strftime("%H:%M")
        if self.quiet_start == self.quiet_end:
            return True
        if self.quiet_start < self.quiet_end:
            quiet = self.quiet_start <= local_time < self.quiet_end
        else:
            quiet = local_time >= self.quiet_start or local_time < self.quiet_end
        return not quiet
