"""Application-facing Download Station models."""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


def _integer(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True)
class TransferStats:
    downloaded_bytes: int = 0
    uploaded_bytes: int = 0
    download_speed: int = 0
    upload_speed: int = 0

    @classmethod
    def from_mapping(cls, value: Any) -> "TransferStats":
        item = value if isinstance(value, dict) else {}
        return cls(
            downloaded_bytes=_integer(item.get("size_downloaded")),
            uploaded_bytes=_integer(item.get("size_uploaded")),
            download_speed=_integer(item.get("speed_download")),
            upload_speed=_integer(item.get("speed_upload")),
        )


@dataclass(frozen=True)
class Task:
    task_id: str
    title: str = ""
    size_bytes: int = 0
    status: str = "unknown"
    username: Optional[str] = None
    transfer: TransferStats = field(default_factory=TransferStats)
    raw: Dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_mapping(cls, value: Any) -> "Task":
        if not isinstance(value, dict) or not value.get("id"):
            raise ValueError("Download Station task is missing a valid id")
        additional = value.get("additional")
        additional = additional if isinstance(additional, dict) else {}
        return cls(
            task_id=str(value["id"]),
            title=str(value.get("title") or ""),
            size_bytes=_integer(value.get("size")),
            status=str(value.get("status") or "unknown"),
            username=(str(value["username"]) if value.get("username") is not None else None),
            transfer=TransferStats.from_mapping(additional.get("transfer")),
            raw=dict(value),
        )
