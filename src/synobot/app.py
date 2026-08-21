"""Composition root for the modern Synobot core.

Telegram delivery remains an adapter concern. This module wires configuration,
authorization, DSM access, and durable task state without global singletons.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, List, Optional

import pyotp

from .authorization import AuthorizationPolicy
from .config import ConfigurationError, Settings
from .synology import SynologyClient
from .synology.models import Task as SynologyTask
from .tasks import SQLiteTaskRepository, Task, TaskEvent, TaskService


def _totp_provider(secret: Optional[str]) -> Optional[Callable[[], str]]:
    if not secret:
        return None
    generator = pyotp.TOTP(secret)
    return generator.now


def persistent_task(task: SynologyTask) -> Task:
    """Translate the transport model into the persistence-domain model."""
    transfer = task.transfer
    return Task(
        task_id=task.task_id,
        title=task.title,
        size_bytes=task.size_bytes,
        owner=task.username or "",
        status=task.status,
        downloaded_bytes=transfer.downloaded_bytes if transfer else 0,
        uploaded_bytes=transfer.uploaded_bytes if transfer else 0,
        download_speed=transfer.download_speed if transfer else 0,
        upload_speed=transfer.upload_speed if transfer else 0,
    )


class SynobotCore:
    """Application service used by Telegram or future adapters."""

    def __init__(self, client: SynologyClient, tasks: TaskService) -> None:
        self.client = client
        self.tasks = tasks

    def synchronize_tasks(self) -> List[TaskEvent]:
        observed = (persistent_task(item) for item in self.client.list_tasks(details=True))
        return self.tasks.reconcile(observed)

    def close(self) -> None:
        self.client.close()
        self.tasks.repository.close()


@dataclass
class ApplicationComponents:
    settings: Settings
    authorization: AuthorizationPolicy
    client: SynologyClient
    repository: SQLiteTaskRepository
    tasks: TaskService
    core: SynobotCore

    def close(self) -> None:
        self.core.close()

    def __enter__(self) -> "ApplicationComponents":
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()


def build_components(
    settings: Settings,
    *,
    session: Optional[Any] = None,
    legacy_task_path: Optional[Path] = Path("taskdata.json"),
) -> ApplicationComponents:
    password = settings.dsm_password
    if not password:
        raise ConfigurationError(
            "DSM_PASSWORD or DSM_PASSWORD_FILE is required for unattended startup"
        )
    repository = SQLiteTaskRepository(settings.database_path)
    try:
        if legacy_task_path is not None:
            repository.migrate_legacy_json(legacy_task_path)
        client = SynologyClient(
            base_url=settings.dsm_base_url,
            username=settings.dsm_username,
            password=password,
            tls_verify=settings.dsm_tls_verify,
            timeout=settings.dsm_request_timeout_seconds,
            otp_provider=_totp_provider(settings.dsm_totp_secret),
            session=session,
        )
        authorization = AuthorizationPolicy.create(settings.telegram_admin_user_ids)
        task_service = TaskService(repository)
        core = SynobotCore(client, task_service)
        return ApplicationComponents(
            settings, authorization, client, repository, task_service, core
        )
    except Exception:
        repository.close()
        raise
