"""Supervised asynchronous polling of the synchronous Synobot core."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from .app import SynobotCore


StatusCallback = Callable[[str], Awaitable[None]]
NotificationCallback = Callable[[], Awaitable[object]]
Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class MonitorHealth:
    running: bool
    dsm_connected: bool
    last_success: Optional[datetime]
    last_error: Optional[str]


class AsyncTaskMonitor:
    """Poll DSM serially without blocking Telegram's event loop.

    An outage and its eventual recovery are each announced once.  Notification
    callback failures never stop polling or alter DSM connectivity state.
    """

    def __init__(
        self,
        core: SynobotCore,
        *,
        interval: float = 10.0,
        max_backoff: float = 300.0,
        status_callback: Optional[StatusCallback] = None,
        notification_callback: Optional[NotificationCallback] = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        if interval <= 0 or max_backoff <= 0:
            raise ValueError("monitor intervals must be greater than zero")
        self._core = core
        self._interval = interval
        self._max_backoff = max(max_backoff, interval)
        self._status_callback = status_callback
        self._notification_callback = notification_callback
        self._sleep = sleep
        self._task: Optional["asyncio.Task[None]"] = None
        self._poll_lock = asyncio.Lock()
        self._last_success: Optional[datetime] = None
        self._last_error: Optional[str] = None
        self._connected = False
        self._has_polled = False

    @property
    def health(self) -> MonitorHealth:
        return MonitorHealth(
            running=self._task is not None and not self._task.done(),
            dsm_connected=self._connected,
            last_success=self._last_success,
            last_error=self._last_error,
        )

    def start(self) -> "asyncio.Task[None]":
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="synobot-task-monitor")
        return self._task

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def poll_once(self) -> bool:
        """Perform one non-overlapping poll; return whether it succeeded."""
        async with self._poll_lock:
            was_connected = self._connected
            try:
                await asyncio.to_thread(self._core.synchronize_tasks)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._connected = False
                self._last_error = "%s: %s" % (exc.__class__.__name__, exc)
                if not self._has_polled or was_connected:
                    await self._announce("DSM connection lost")
                self._has_polled = True
                return False
            self._connected = True
            self._last_error = None
            self._last_success = datetime.now(timezone.utc)
            if self._notification_callback is not None:
                try:
                    await self._notification_callback()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # Delivery stays pending and is retried after a later poll.
                    pass
            if self._has_polled and not was_connected:
                await self._announce("DSM connection recovered")
            self._has_polled = True
            return True

    async def _announce(self, message: str) -> None:
        if self._status_callback is None:
            return
        try:
            await self._status_callback(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Connectivity reporting must not terminate the monitor.
            return

    async def _run(self) -> None:
        delay = self._interval
        while True:
            success = await self.poll_once()
            delay = self._interval if success else min(delay * 2, self._max_backoff)
            await self._sleep(delay)
