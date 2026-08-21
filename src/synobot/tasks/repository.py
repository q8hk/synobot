"""Thread-safe SQLite persistence for observed Download Station tasks."""

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from .models import Task, TaskEvent, utc_now


SCHEMA_VERSION = "1"
_MIGRATION_KEY = "legacy_taskdata_migrated"


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _datetime(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value) if value else None


class SQLiteTaskRepository:
    """Owns one SQLite connection and serializes its use across threads."""

    def __init__(self, database_path: Path) -> None:
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(str(self.path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        with self._lock:
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._initialize_schema()

    def _initialize_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS app_metadata (
                key TEXT PRIMARY KEY, value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
                owner TEXT NOT NULL,
                status TEXT NOT NULL,
                downloaded_bytes INTEGER NOT NULL DEFAULT 0,
                uploaded_bytes INTEGER NOT NULL DEFAULT 0,
                download_speed INTEGER NOT NULL DEFAULT 0,
                upload_speed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                removed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS task_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                old_status TEXT,
                new_status TEXT,
                observed_at TEXT NOT NULL,
                notification_state TEXT NOT NULL DEFAULT 'pending'
                    CHECK(notification_state IN ('pending', 'delivered', 'failed')),
                delivered_at TEXT,
                FOREIGN KEY(task_id) REFERENCES tasks(task_id)
            );
            CREATE INDEX IF NOT EXISTS idx_task_events_pending
                ON task_events(notification_state, id);
            CREATE INDEX IF NOT EXISTS idx_tasks_updated
                ON tasks(updated_at DESC);
            """
        )
        row = self._connection.execute(
            "SELECT value FROM app_metadata WHERE key = 'schema_version'"
        ).fetchone()
        if row is not None and row["value"] != SCHEMA_VERSION:
            raise RuntimeError("Unsupported task database schema version: %s" % row["value"])
        self._connection.execute(
            "INSERT OR IGNORE INTO app_metadata(key, value) VALUES('schema_version', ?)",
            (SCHEMA_VERSION,),
        )
        self._connection.commit()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                yield self._connection
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise

    def get_metadata(self, key: str) -> Optional[str]:
        with self._lock:
            row = self._connection.execute(
                "SELECT value FROM app_metadata WHERE key = ?", (key,)
            ).fetchone()
            return str(row["value"]) if row else None

    def upsert(self, task: Task, create_event: bool = True) -> Optional[TaskEvent]:
        now = task.updated_at or utc_now()
        with self._transaction() as connection:
            previous = connection.execute(
                "SELECT status, created_at, removed_at FROM tasks WHERE task_id = ?", (task.task_id,)
            ).fetchone()
            created = task.created_at or (_datetime(previous["created_at"]) if previous else now)
            completed = task.completed_at
            if completed is None and task.status == "finished":
                completed = now
            connection.execute(
                """INSERT INTO tasks(
                    task_id,title,size_bytes,owner,status,downloaded_bytes,uploaded_bytes,
                    download_speed,upload_speed,created_at,updated_at,completed_at,removed_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(task_id) DO UPDATE SET
                    title=excluded.title,size_bytes=excluded.size_bytes,owner=excluded.owner,
                    status=excluded.status,downloaded_bytes=excluded.downloaded_bytes,
                    uploaded_bytes=excluded.uploaded_bytes,download_speed=excluded.download_speed,
                    upload_speed=excluded.upload_speed,updated_at=excluded.updated_at,
                    completed_at=COALESCE(excluded.completed_at,tasks.completed_at),removed_at=NULL""",
                (task.task_id, task.title, task.size_bytes, task.owner, task.status,
                 task.downloaded_bytes, task.uploaded_bytes, task.download_speed,
                 task.upload_speed, _iso(created), _iso(now), _iso(completed), None),
            )
            old_status = str(previous["status"]) if previous else None
            reappeared = previous is not None and previous["removed_at"] is not None
            event_type = ("created" if previous is None else
                          "reappeared" if reappeared else "status_changed")
            if (not create_event or
                    (previous is not None and not reappeared and old_status == task.status)):
                return None
            event_id = self._insert_event(connection, task.task_id, event_type,
                                          old_status, task.status, now)
            return TaskEvent(event_id, task.task_id, event_type, old_status,
                             task.status, now)

    @staticmethod
    def _insert_event(connection: sqlite3.Connection, task_id: str, event_type: str,
                      old_status: Optional[str], new_status: Optional[str],
                      observed_at: datetime) -> int:
        cursor = connection.execute(
            """INSERT INTO task_events(task_id,event_type,old_status,new_status,observed_at)
               VALUES(?,?,?,?,?)""",
            (task_id, event_type, old_status, new_status, _iso(observed_at)),
        )
        return int(cursor.lastrowid)

    def mark_removed(self, task_id: str, observed_at: Optional[datetime] = None) -> Optional[TaskEvent]:
        now = observed_at or utc_now()
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT status, removed_at FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None or row["removed_at"] is not None:
                return None
            connection.execute("UPDATE tasks SET removed_at=?, updated_at=? WHERE task_id=?",
                               (_iso(now), _iso(now), task_id))
            event_id = self._insert_event(connection, task_id, "removed",
                                          str(row["status"]), "removed", now)
            return TaskEvent(event_id, task_id, "removed", str(row["status"]), "removed", now)

    def get(self, task_id: str) -> Optional[Task]:
        with self._lock:
            row = self._connection.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            return self._task(row) if row else None

    def list(self, include_removed: bool = False) -> List[Task]:
        where = "" if include_removed else "WHERE removed_at IS NULL"
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM tasks %s ORDER BY updated_at DESC" % where
            ).fetchall()
            return [self._task(row) for row in rows]

    def recent(self, limit: int = 20, include_removed: bool = True) -> List[Task]:
        if limit < 0:
            raise ValueError("limit must not be negative")
        where = "" if include_removed else "WHERE removed_at IS NULL"
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM tasks %s ORDER BY updated_at DESC LIMIT ?" % where, (limit,)
            ).fetchall()
            return [self._task(row) for row in rows]

    def pending_events(self, limit: int = 100) -> List[TaskEvent]:
        if limit < 0:
            raise ValueError("limit must not be negative")
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM task_events WHERE notification_state='pending' ORDER BY id LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._event(row) for row in rows]

    def mark_notification_delivered(self, event_id: int,
                                    delivered_at: Optional[datetime] = None) -> bool:
        with self._transaction() as connection:
            cursor = connection.execute(
                """UPDATE task_events SET notification_state='delivered', delivered_at=?
                   WHERE id=? AND notification_state='pending'""",
                (_iso(delivered_at or utc_now()), event_id),
            )
            return cursor.rowcount == 1

    def migrate_legacy_json(self, legacy_path: Path) -> int:
        """Import a complete legacy file once; the source is never changed."""
        path = Path(legacy_path)
        if self.get_metadata(_MIGRATION_KEY) is not None:
            return 0
        if not path.exists():
            return 0
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("legacy task data must be a JSON object")
        tasks: List[Task] = []
        for task_id, values in raw.items():
            if (not isinstance(task_id, str) or not isinstance(values, list)
                    or len(values) != 4):
                raise ValueError("invalid legacy task record")
            title, size, owner, status = values
            if (not isinstance(title, str) or isinstance(size, bool) or not isinstance(size, int)
                    or size < 0 or not isinstance(owner, str) or not isinstance(status, str)):
                raise ValueError("invalid legacy task fields")
            tasks.append(Task(task_id, title, size, owner, status))
        now = utc_now()
        with self._transaction() as connection:
            for task in tasks:
                connection.execute(
                    """INSERT OR IGNORE INTO tasks(
                       task_id,title,size_bytes,owner,status,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?)""",
                    (task.task_id, task.title, task.size_bytes, task.owner, task.status,
                     _iso(now), _iso(now)),
                )
            connection.execute(
                "INSERT INTO app_metadata(key,value) VALUES(?,?)",
                (_MIGRATION_KEY, str(path.resolve())),
            )
        return len(tasks)

    @staticmethod
    def _task(row: sqlite3.Row) -> Task:
        return Task(str(row["task_id"]), str(row["title"]), int(row["size_bytes"]),
                    str(row["owner"]), str(row["status"]), int(row["downloaded_bytes"]),
                    int(row["uploaded_bytes"]), int(row["download_speed"]),
                    int(row["upload_speed"]), _datetime(row["created_at"]),
                    _datetime(row["updated_at"]), _datetime(row["completed_at"]),
                    _datetime(row["removed_at"]))

    @staticmethod
    def _event(row: sqlite3.Row) -> TaskEvent:
        return TaskEvent(int(row["id"]), str(row["task_id"]), str(row["event_type"]),
                         row["old_status"], row["new_status"],
                         _datetime(row["observed_at"]), str(row["notification_state"]),
                         _datetime(row["delivered_at"]))  # type: ignore[arg-type]

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "SQLiteTaskRepository":
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()


TaskRepository = SQLiteTaskRepository
