from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from synobot.healthcheck import HealthStateStore, is_healthy, main
from synobot.monitoring import MonitorHealth


def test_health_state_is_atomic_and_dsm_outage_remains_live(tmp_path: Path):
    path = tmp_path / "health.json"
    store = HealthStateStore(path)

    store.write(MonitorHealth(True, False, None, "DSM offline"))

    payload = json.loads(path.read_text())
    assert payload["running"] is True
    assert payload["dsm_connected"] is False
    assert is_healthy(path)


def test_stopped_stale_missing_and_malformed_states_are_unhealthy(tmp_path: Path):
    path = tmp_path / "health.json"
    HealthStateStore(path).write(MonitorHealth(False, True, None, None))
    assert not is_healthy(path)

    path.write_text(json.dumps({
        "running": True,
        "heartbeat": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    }))
    assert not is_healthy(path, max_age_seconds=10)
    path.write_text("not-json")
    assert not is_healthy(path)
    assert not is_healthy(tmp_path / "missing.json")


def test_healthcheck_command_returns_process_exit_codes(tmp_path: Path):
    path = tmp_path / "health.json"
    HealthStateStore(path).write(MonitorHealth(True, True, None, None))

    assert main(["--state", str(path), "--max-age", "60"]) == 0
    assert main(["--state", str(tmp_path / "missing")]) == 1
