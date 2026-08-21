"""Persistent task models, independent from DSM and Telegram adapters."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


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
