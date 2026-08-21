"""A small, typed client for the Synology Download Station Web API."""

import json
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Union

import requests

from .errors import (
    SynologyApiError,
    SynologyAuthenticationError,
    SynologyConnectionError,
    SynologyError,
    SynologyOtpError,
    SynologyPermissionError,
    SynologyRateLimitError,
    SynologySessionExpiredError,
    SynologyTimeoutError,
    SynologyTlsError,
)
from .models import Task, TransferStats


OtpProvider = Callable[[], str]
TaskIds = Union[str, Iterable[str]]


class SynologyClient:
    """Synchronous Download Station client with explicit session ownership."""

    AUTH_PATH = "/webapi/auth.cgi"
    TASK_PATH = "/webapi/DownloadStation/task.cgi"
    STATISTIC_PATH = "/webapi/DownloadStation/statistic.cgi"
    SESSION_ERROR_CODES = frozenset((105, 106, 107, 119))

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        tls_verify: Union[bool, str] = True,
        timeout: Union[float, tuple] = 20,
        otp_provider: Optional[OtpProvider] = None,
        session: Optional[Any] = None,
    ) -> None:
        if not base_url or not username:
            raise ValueError("base_url and username are required")
        if not password:
            raise ValueError("password is required")
        self.base_url = base_url.rstrip("/")
        self.username = username
        self._password = password
        self.tls_verify = tls_verify
        self.timeout = timeout
        self.otp_provider = otp_provider
        self.session = session or requests.Session()
        self._authenticated = False

    @property
    def authenticated(self) -> bool:
        return self._authenticated

    def login(self) -> None:
        data: Dict[str, Any] = {
            "api": "SYNO.API.Auth",
            "version": 3,
            "method": "login",
            "account": self.username,
            "passwd": self._password,
            "session": "DownloadStation",
            "format": "cookie",
        }
        if self.otp_provider is not None:
            otp = self.otp_provider()
            if otp:
                data["otp_code"] = otp
        payload = self._send(self.AUTH_PATH, data, authenticated=False)
        self._ensure_success(payload, operation="login", authentication=True)
        self._authenticated = True

    def logout(self) -> None:
        if not self._authenticated:
            return
        data = {
            "api": "SYNO.API.Auth",
            "version": 3,
            "method": "logout",
            "session": "DownloadStation",
        }
        try:
            payload = self._send(self.AUTH_PATH, data, authenticated=False)
            self._ensure_success(payload, operation="logout")
        finally:
            self._authenticated = False
            cookies = getattr(self.session, "cookies", None)
            if cookies is not None and hasattr(cookies, "clear"):
                cookies.clear()

    def close(self) -> None:
        try:
            self.logout()
        finally:
            close = getattr(self.session, "close", None)
            if close is not None:
                close()

    def __enter__(self) -> "SynologyClient":
        self.login()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def list_tasks(self, details: bool = False) -> List[Task]:
        data: Dict[str, Any] = {
            "api": "SYNO.DownloadStation.Task",
            "version": 3,
            "method": "list",
        }
        if details:
            data["additional"] = "detail,file,transfer"
        payload = self._request(self.TASK_PATH, data, safe=True)
        response_data = self._response_data(payload)
        tasks = response_data.get("tasks", [])
        if not isinstance(tasks, list):
            raise SynologyApiError("list tasks returned a malformed tasks value")
        parsed: List[Task] = []
        for item in tasks:
            try:
                parsed.append(Task.from_mapping(item))
            except ValueError as error:
                raise SynologyApiError(str(error)) from error
        return parsed

    def task_details(self, task_ids: Optional[TaskIds] = None) -> List[Task]:
        data: Dict[str, Any] = {
            "api": "SYNO.DownloadStation.Task",
            "version": 3,
            "method": "list",
            "additional": "detail,file,transfer",
        }
        if task_ids is not None:
            data["id"] = self._task_ids(task_ids)
        payload = self._request(self.TASK_PATH, data, safe=True)
        tasks = self._response_data(payload).get("tasks", [])
        if not isinstance(tasks, list):
            raise SynologyApiError("task details returned a malformed tasks value")
        try:
            return [Task.from_mapping(item) for item in tasks]
        except ValueError as error:
            raise SynologyApiError(str(error)) from error

    def statistics(self) -> TransferStats:
        payload = self._request(
            self.STATISTIC_PATH,
            {"api": "SYNO.DownloadStation.Statistic", "version": 1, "method": "getinfo"},
            safe=True,
        )
        data = self._response_data(payload)
        return TransferStats(
            download_speed=self._nonnegative_int(data.get("speed_download")),
            upload_speed=self._nonnegative_int(data.get("speed_upload")),
        )

    def create_url(self, uri: str, destination: Optional[str] = None) -> None:
        if not uri or not uri.strip():
            raise ValueError("uri must not be empty")
        data: Dict[str, Any] = self._task_operation("create")
        data["uri"] = uri
        if destination:
            data["destination"] = destination
        self._request(self.TASK_PATH, data, safe=False)

    def create_file(self, file_path: Union[str, Path], destination: Optional[str] = None) -> None:
        path = Path(file_path)
        data: Dict[str, Any] = self._task_operation("create")
        if destination:
            data["destination"] = destination
        try:
            with path.open("rb") as torrent:
                self._request(self.TASK_PATH, data, safe=False, files={"file": torrent})
        except OSError as error:
            raise SynologyApiError("unable to read torrent file: {}".format(path)) from error

    def pause(self, task_ids: TaskIds) -> None:
        self._mutate_tasks("pause", task_ids)

    def resume(self, task_ids: TaskIds) -> None:
        self._mutate_tasks("resume", task_ids)

    def delete(self, task_ids: TaskIds, force_complete: bool = False) -> None:
        data = self._task_operation("delete")
        data["id"] = self._task_ids(task_ids)
        data["force_complete"] = bool(force_complete)
        self._request(self.TASK_PATH, data, safe=False)

    def _mutate_tasks(self, method: str, task_ids: TaskIds) -> None:
        data = self._task_operation(method)
        data["id"] = self._task_ids(task_ids)
        self._request(self.TASK_PATH, data, safe=False)

    @staticmethod
    def _task_operation(method: str) -> Dict[str, Any]:
        return {"api": "SYNO.DownloadStation.Task", "version": 3, "method": method}

    @staticmethod
    def _task_ids(task_ids: TaskIds) -> str:
        if isinstance(task_ids, str):
            result = task_ids.strip()
        else:
            result = ",".join(str(value).strip() for value in task_ids if str(value).strip())
        if not result:
            raise ValueError("at least one task id is required")
        return result

    def _request(
        self,
        path: str,
        data: Mapping[str, Any],
        safe: bool,
        files: Optional[Mapping[str, Any]] = None,
    ) -> Mapping[str, Any]:
        if not self._authenticated:
            self.login()
        payload = self._send(path, data, files=files)
        try:
            self._ensure_success(payload, operation=str(data.get("method", "request")))
        except SynologySessionExpiredError:
            self._authenticated = False
            if not safe:
                raise
            self.login()
            payload = self._send(path, data, files=files)
            self._ensure_success(payload, operation=str(data.get("method", "request")))
        return payload

    def _send(
        self,
        path: str,
        data: Mapping[str, Any],
        authenticated: bool = True,
        files: Optional[Mapping[str, Any]] = None,
    ) -> Mapping[str, Any]:
        del authenticated  # Session cookies are managed by the injected session.
        try:
            response = self.session.post(
                self.base_url + path,
                data=dict(data),
                files=files,
                verify=self.tls_verify,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.Timeout as error:
            raise SynologyTimeoutError("DSM request timed out") from error
        except requests.exceptions.SSLError as error:
            raise SynologyTlsError("DSM TLS verification failed") from error
        except requests.ConnectionError as error:
            raise SynologyConnectionError("unable to connect to DSM") from error
        except requests.RequestException as error:
            raise SynologyConnectionError("DSM HTTP request failed") from error
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError) as error:
            raise SynologyApiError("DSM returned invalid JSON") from error
        if not isinstance(payload, dict):
            raise SynologyApiError("DSM returned a non-object response")
        return payload

    def _ensure_success(
        self, payload: Mapping[str, Any], operation: str, authentication: bool = False
    ) -> None:
        if payload.get("success") is True:
            return
        error = payload.get("error")
        error = error if isinstance(error, dict) else {}
        try:
            code = int(error.get("code"))
        except (TypeError, ValueError):
            code = None
        message = "DSM {} failed{}".format(
            operation, " with error {}".format(code) if code is not None else ""
        )
        exception = self._error_type(code, authentication)
        raise exception(message, code=code)

    @classmethod
    def _error_type(cls, code: Optional[int], authentication: bool = False):
        if code in cls.SESSION_ERROR_CODES:
            return SynologySessionExpiredError
        if authentication:
            if code in (403, 404):
                return SynologyOtpError
            if code in (400, 401, 402, 406, 407):
                return SynologyAuthenticationError
        if code == 402:
            return SynologyPermissionError
        if code in (117, 429):
            return SynologyRateLimitError
        return SynologyApiError

    @staticmethod
    def _response_data(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        data = payload.get("data")
        if not isinstance(data, dict):
            raise SynologyApiError("DSM response is missing an object data field")
        return data

    @staticmethod
    def _nonnegative_int(value: Any) -> int:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0
