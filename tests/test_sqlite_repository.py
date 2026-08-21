import json
import threading
from pathlib import Path

import pytest

from synobot.tasks import SQLiteTaskRepository, Task, TaskService


def task(task_id="dbid_1", status="downloading", downloaded=0):
    return Task(task_id, "Ubuntu", 1000, "synobot", status,
                downloaded_bytes=downloaded)


def test_schema_and_context_manager(tmp_path: Path):
    path = tmp_path / "data" / "synobot.db"
    with SQLiteTaskRepository(path) as repository:
        assert repository.get_metadata("schema_version") == "2"
    assert path.exists()


def test_upsert_only_creates_events_for_meaningful_changes(tmp_path: Path):
    repository = SQLiteTaskRepository(tmp_path / "db.sqlite")
    created = repository.upsert(task())
    assert created is not None and created.event_type == "created"
    assert repository.upsert(task(downloaded=500)) is None
    changed = repository.upsert(task(status="finished", downloaded=1000))
    assert changed is not None
    assert (changed.old_status, changed.new_status) == ("downloading", "finished")
    saved = repository.get("dbid_1")
    assert saved is not None and saved.completed_at is not None
    assert len(repository.pending_events()) == 2


def test_notifications_are_durable_and_delivered_once(tmp_path: Path):
    path = tmp_path / "db.sqlite"
    first = SQLiteTaskRepository(path)
    event = first.upsert(task())
    assert event is not None
    first.close()
    second = SQLiteTaskRepository(path)
    assert [item.event_id for item in second.pending_events()] == [event.event_id]
    assert second.mark_notification_delivered(event.event_id)
    assert not second.mark_notification_delivered(event.event_id)
    second.close()
    third = SQLiteTaskRepository(path)
    assert third.pending_events() == []


def test_service_reconciles_removals_without_duplicate_event(tmp_path: Path):
    repository = SQLiteTaskRepository(tmp_path / "db.sqlite")
    service = TaskService(repository)
    assert [event.event_type for event in service.reconcile([task()])] == ["created"]
    assert service.reconcile([task(downloaded=50)]) == []
    events = service.reconcile([])
    assert len(events) == 1 and events[0].event_type == "removed"
    assert service.reconcile([]) == []
    assert repository.get("dbid_1").removed_at is not None


def test_reappearing_task_is_active_again(tmp_path: Path):
    repository = SQLiteTaskRepository(tmp_path / "db.sqlite")
    service = TaskService(repository)
    service.reconcile([task()])
    service.reconcile([])
    events = service.reconcile([task(status="paused")])
    assert len(events) == 1 and events[0].event_type == "reappeared"
    assert repository.get("dbid_1").removed_at is None


def test_legacy_migration_is_validated_preserved_and_idempotent(tmp_path: Path):
    legacy = tmp_path / "taskdata.json"
    contents = {"dbid_1": ["Ubuntu", 1000, "synobot", "downloading"]}
    legacy.write_text(json.dumps(contents), encoding="utf-8")
    repository = SQLiteTaskRepository(tmp_path / "db.sqlite")
    assert repository.migrate_legacy_json(legacy) == 1
    assert repository.get("dbid_1").title == "Ubuntu"
    assert repository.pending_events() == []
    assert json.loads(legacy.read_text(encoding="utf-8")) == contents
    assert repository.migrate_legacy_json(legacy) == 0


@pytest.mark.parametrize("contents", [[], {"id": ["title", -1, "owner", "status"]},
                                       {"id": ["too", "short"]}])
def test_invalid_legacy_file_has_no_partial_effect(tmp_path: Path, contents):
    legacy = tmp_path / "taskdata.json"
    legacy.write_text(json.dumps(contents), encoding="utf-8")
    repository = SQLiteTaskRepository(tmp_path / "db.sqlite")
    with pytest.raises(ValueError):
        repository.migrate_legacy_json(legacy)
    assert repository.list(include_removed=True) == []
    assert repository.get_metadata("legacy_taskdata_migrated") is None


def test_repository_serializes_threads(tmp_path: Path):
    repository = SQLiteTaskRepository(tmp_path / "db.sqlite")
    errors = []

    def writer(index):
        try:
            repository.upsert(task("id_%s" % index))
        except Exception as error:  # pragma: no cover - assertion captures it
            errors.append(error)

    threads = [threading.Thread(target=writer, args=(index,)) for index in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert len(repository.list()) == 20


def test_list_recent_and_duplicate_poll_validation(tmp_path: Path):
    repository = SQLiteTaskRepository(tmp_path / "db.sqlite")
    service = TaskService(repository)
    service.reconcile([task("one"), task("two")])
    assert len(repository.recent(limit=1)) == 1
    with pytest.raises(ValueError, match="duplicate"):
        service.reconcile([task("same"), task("same")])
    with pytest.raises(ValueError):
        repository.recent(-1)


def test_history_returns_newest_lifecycle_events(tmp_path: Path):
    repository = SQLiteTaskRepository(tmp_path / "db.sqlite")
    service = TaskService(repository)
    service.reconcile([task("one")])
    service.reconcile([task("one", status="finished")])
    events = service.history(limit=1)
    assert len(events) == 1
    assert events[0].event_type == "status_changed"
    assert events[0].new_status == "finished"
    with pytest.raises(ValueError):
        service.history(-1)
