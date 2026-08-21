"""Async Telegram handlers backed by the synchronous Synobot core.

The adapter deliberately accepts normal python-telegram-bot Update/Context
objects by protocol (duck typing).  This keeps all network and persistence work
behind ``asyncio.to_thread`` and makes the handlers straightforward to test.
"""

import asyncio
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Optional
from urllib.parse import urlsplit

from ..app import SynobotCore
from ..authorization import AuthorizationPolicy, Role
from ..config import Settings
from ..synology.errors import SynologyError


LOGGER = logging.getLogger(__name__)
_YOUTUBE_HOSTS = frozenset(
    ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be")
)


def _bytes(value: int) -> str:
    amount = float(max(0, value))
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            return "{:.1f} {}".format(amount, unit)
        amount /= 1024
    return "0 B"


class TelegramHandlers:
    """Command and message handlers for the PTB 22 application."""

    def __init__(
        self,
        core: SynobotCore,
        authorization: AuthorizationPolicy,
        settings: Settings,
    ) -> None:
        self.core = core
        self.authorization = authorization
        self.settings = settings

    async def _authorize(self, update: Any, minimum: Role = Role.VIEWER) -> bool:
        user = getattr(update, "effective_user", None)
        chat = getattr(update, "effective_chat", None)
        message = getattr(update, "effective_message", None)
        try:
            if user is None or chat is None:
                raise PermissionError("missing Telegram identity")
            self.authorization.require(int(user.id), minimum, str(chat.type))
            return True
        except (PermissionError, TypeError, ValueError):
            if message is not None:
                await message.reply_text("You are not authorized to use this bot.")
            return False

    @staticmethod
    async def _reply(update: Any, text: str) -> None:
        message = getattr(update, "effective_message", None)
        if message is not None:
            await message.reply_text(text)

    async def start(self, update: Any, context: Any) -> None:
        del context
        if not await self._authorize(update):
            return
        state = "connected" if self.core.client.authenticated else "ready"
        await self._reply(update, "Synobot is {}. Use /help for commands.".format(state))

    async def help(self, update: Any, context: Any) -> None:
        del context
        if not await self._authorize(update):
            return
        await self._reply(
            update,
            "Commands: /health, /tasks, /stats, /dslogin, /add <URL>. "
            "You can also send a magnet link, supported YouTube URL, or .torrent file.",
        )

    async def health(self, update: Any, context: Any) -> None:
        del context
        if not await self._authorize(update):
            return
        try:
            await asyncio.to_thread(self.core.client.statistics)
        except SynologyError:
            await self._reply(update, "Synobot is running, but DSM is unavailable.")
            return
        await self._reply(update, "Synobot and DSM are available.")

    async def tasks(self, update: Any, context: Any) -> None:
        del context
        if not await self._authorize(update):
            return
        try:
            tasks = await asyncio.to_thread(self.core.client.list_tasks, True)
        except SynologyError:
            await self._reply(update, "Could not retrieve Download Station tasks.")
            return
        if not tasks:
            await self._reply(update, "No Download Station tasks.")
            return
        lines = []
        for item in tasks:
            progress = 0.0
            if item.size_bytes > 0:
                progress = min(100.0, item.transfer.downloaded_bytes * 100.0 / item.size_bytes)
            title = item.title or item.task_id
            lines.append("{} — {} — {:.1f}%".format(title, item.status, progress))
        await self._reply(update, "\n".join(lines))

    async def stats(self, update: Any, context: Any) -> None:
        del context
        if not await self._authorize(update):
            return
        try:
            stats = await asyncio.to_thread(self.core.client.statistics)
        except SynologyError:
            await self._reply(update, "Could not retrieve Download Station statistics.")
            return
        await self._reply(
            update,
            "Download: {}/s\nUpload: {}/s".format(
                _bytes(stats.download_speed), _bytes(stats.upload_speed)
            ),
        )

    async def dslogin(self, update: Any, context: Any) -> None:
        del context
        if not await self._authorize(update, Role.ADMIN):
            return
        try:
            await asyncio.to_thread(self.core.client.login)
        except SynologyError:
            await self._reply(update, "DSM login failed.")
            return
        await self._reply(update, "DSM login succeeded.")

    async def add(self, update: Any, context: Any) -> None:
        if not await self._authorize(update, Role.OPERATOR):
            return
        args = getattr(context, "args", None) or []
        if len(args) != 1 or not self._supported_url(args[0], allow_general=True):
            await self._reply(update, "Usage: /add <HTTP, HTTPS, FTP, or magnet URL>")
            return
        await self._create_url(update, args[0])

    async def text(self, update: Any, context: Any) -> None:
        del context
        if not await self._authorize(update, Role.OPERATOR):
            return
        message = getattr(update, "effective_message", None)
        value = str(getattr(message, "text", "") or "").strip()
        if value.startswith("magnet:?") or self._youtube_url(value):
            await self._create_url(update, value)
            return
        await self._reply(
            update,
            "Unsupported message. Send a magnet link, YouTube URL, .torrent file, or /add <URL>.",
        )

    async def torrent(self, update: Any, context: Any) -> None:
        if not await self._authorize(update, Role.OPERATOR):
            return
        message = getattr(update, "effective_message", None)
        document = getattr(message, "document", None)
        original_name = str(getattr(document, "file_name", "") or "")
        if document is None or not original_name.lower().endswith(".torrent"):
            await self._reply(update, "Only .torrent documents are supported.")
            return
        try:
            telegram_file = await context.bot.get_file(document.file_id)
            with TemporaryDirectory(prefix="synobot-") as directory:
                target = Path(directory) / "upload.torrent"
                await telegram_file.download_to_drive(custom_path=target)
                await asyncio.to_thread(self.core.client.create_file, target)
        except (SynologyError, OSError):
            await self._reply(update, "Could not submit the torrent to Download Station.")
            return
        await self._reply(update, "Torrent submitted to Download Station.")

    async def document(self, update: Any, context: Any) -> None:
        """PTB document-message entrypoint."""
        await self.torrent(update, context)

    async def unsupported(self, update: Any, context: Any) -> None:
        del context
        if not await self._authorize(update):
            return
        await self._reply(update, "Unsupported command. Use /help.")

    async def error(self, update: object, context: Any) -> None:
        """Log exception class only; never interpolate updates or secret-bearing data."""
        error: Optional[BaseException] = getattr(context, "error", None)
        name = error.__class__.__name__ if error is not None else "UnknownError"
        LOGGER.error("Unhandled Telegram handler error: %s", name)
        message = getattr(update, "effective_message", None)
        if message is not None:
            try:
                await message.reply_text("An unexpected error occurred.")
            except Exception:
                LOGGER.warning("Unable to deliver Telegram error response")

    async def _create_url(self, update: Any, value: str) -> None:
        try:
            await asyncio.to_thread(self.core.client.create_url, value)
        except (SynologyError, ValueError):
            await self._reply(update, "Download Station rejected the URL.")
            return
        await self._reply(update, "URL submitted to Download Station.")

    @staticmethod
    def _youtube_url(value: str) -> bool:
        try:
            parsed = urlsplit(value)
        except ValueError:
            return False
        return parsed.scheme in ("http", "https") and (parsed.hostname or "").lower() in _YOUTUBE_HOSTS

    @classmethod
    def _supported_url(cls, value: str, allow_general: bool = False) -> bool:
        value = str(value).strip()
        if value.startswith("magnet:?"):
            return True
        try:
            parsed = urlsplit(value)
        except ValueError:
            return False
        if not parsed.hostname:
            return False
        if allow_general:
            return parsed.scheme in ("http", "https", "ftp")
        return cls._youtube_url(value)
