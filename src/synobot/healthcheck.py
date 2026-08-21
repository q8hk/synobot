"""Container liveness state and command-line health probe."""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Optional


class HealthStateStore:
    """Persist monitor health atomically for an out-of-process probe."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, health: Any) -> None:
        payload = asdict(health)
        payload["heartbeat"] = datetime.now(timezone.utc).isoformat()
        for key in ("last_success",):
            value = payload.get(key)
            if isinstance(value, datetime):
                payload[key] = value.isoformat()
        descriptor, temporary = tempfile.mkstemp(
            prefix=".synobot-health-", dir=str(self.path.parent), text=True
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def read(self) -> Mapping[str, Any]:
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("health state must be a JSON object")
        return value


def is_healthy(path: Path, max_age_seconds: float = 300.0) -> bool:
    if max_age_seconds <= 0:
        return False
    try:
        state = HealthStateStore(path).read()
        heartbeat = datetime.fromisoformat(str(state["heartbeat"]))
        if heartbeat.tzinfo is None:
            heartbeat = heartbeat.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - heartbeat.astimezone(timezone.utc)).total_seconds()
        return state.get("running") is True and 0 <= age <= max_age_seconds
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return False


def main(arguments: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Check Synobot process liveness")
    parser.add_argument(
        "--state",
        type=Path,
        default=Path(os.environ.get("HEALTH_STATE_PATH", "/data/health.json")),
    )
    parser.add_argument(
        "--max-age",
        type=float,
        default=float(os.environ.get("HEALTH_MAX_AGE_SECONDS", "300")),
    )
    options = parser.parse_args(arguments)
    return 0 if is_healthy(options.state, options.max_age) else 1


if __name__ == "__main__":
    raise SystemExit(main())
