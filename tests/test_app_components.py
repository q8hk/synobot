from pathlib import Path
import tempfile

import pytest

from synobot.app import SynobotCore, build_components, persistent_task
from synobot.config import ConfigurationError, Settings
from synobot.synology.models import Task as SynologyTask, TransferStats
from synobot.tasks import SQLiteTaskRepository, TaskService


class _Client:
    def __init__(self, tasks):
        self.tasks = tasks
        self.closed = False

    def list_tasks(self, details=False):
        assert details is True
        return self.tasks

    def close(self):
        self.closed = True


def _settings(database: Path, password="secret"):
    return Settings(
        telegram_bot_token="token",
        telegram_admin_user_ids=(1,),
        telegram_notify_user_ids=(1,),
        dsm_base_url="https://nas.example:5001",
        dsm_username="synobot",
        dsm_password=password,
        database_path=database,
    )


def test_transport_task_conversion_preserves_transfer_values():
    source = SynologyTask(
        task_id="1",
        title="image.iso",
        size_bytes=100,
        username="user",
        status="downloading",
        transfer=TransferStats(10, 2, 3, 4),
        raw={"additional": {"detail": {"destination": "Movies"}}},
    )

    result = persistent_task(source)

    assert result.task_id == "1"
    assert result.downloaded_bytes == 10
    assert result.uploaded_bytes == 2
    assert result.destination == "Movies"
    assert result.download_speed == 3
    assert result.upload_speed == 4


def test_core_reconciles_client_tasks_without_singletons():
    with tempfile.TemporaryDirectory() as directory:
        repository = SQLiteTaskRepository(Path(directory) / "tasks.db")
        client = _Client([
            SynologyTask(
                task_id="1",
                title="image.iso",
                size_bytes=100,
                status="downloading",
                username="user",
            )
        ])
        core = SynobotCore(client, TaskService(repository))

        events = core.synchronize_tasks()

        assert [event.event_type for event in events] == ["created"]
        assert repository.get("1").title == "image.iso"
        core.close()
        assert client.closed is True


def test_component_builder_requires_unattended_password():
    with tempfile.TemporaryDirectory() as directory:
        settings = _settings(Path(directory) / "tasks.db", password=None)

        with pytest.raises(ConfigurationError, match="unattended startup"):
            build_components(settings, legacy_task_path=None)


def test_component_builder_wires_authorization_client_and_repository():
    with tempfile.TemporaryDirectory() as directory:
        settings = _settings(Path(directory) / "tasks.db")

        with build_components(settings, legacy_task_path=None) as components:
            assert components.authorization.role_for(1).value == "admin"
            assert components.client.base_url == settings.dsm_base_url
            assert components.tasks.repository is components.repository
