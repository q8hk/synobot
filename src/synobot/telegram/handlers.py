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

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..app import SynobotCore
from ..authorization import AuthorizationPolicy, Role
from ..config import Settings
from ..synology.errors import SynologyError
from .localization import SUPPORTED_LANGUAGES, normalize_language, translate


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
        # Conversation preferences deliberately remain adapter state: no DSM or
        # repository migration is needed, and a restart safely restores defaults.
        self._languages: dict[int, str] = {}
        self._destinations: dict[int, str] = {}
        self._recent_destinations: list[str] = []

    @staticmethod
    def _user_id(update: Any) -> Optional[int]:
        user = getattr(update, "effective_user", None)
        try:
            return int(user.id) if user is not None else None
        except (TypeError, ValueError):
            return None

    def _language(self, update: Any) -> str:
        user_id = self._user_id(update)
        configured = normalize_language(self.settings.telegram_language)
        return self._languages.get(user_id, configured) if user_id is not None else configured

    def _t(self, update: Any, key: str, **values: Any) -> str:
        return translate(self._language(update), key, **values)

    def _destination(self, update: Any) -> Optional[str]:
        user_id = self._user_id(update)
        return self._destinations.get(user_id) if user_id is not None else None

    def _remember_destination(self, destination: str) -> None:
        if destination in self._recent_destinations:
            self._recent_destinations.remove(destination)
        self._recent_destinations.insert(0, destination)
        del self._recent_destinations[5:]

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
                await message.reply_text(self._t(update, "not_authorized"))
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
        state = self._t(update, "connected" if self.core.client.authenticated else "ready")
        await self._reply(update, self._t(update, "start", state=state))

    async def help(self, update: Any, context: Any) -> None:
        del context
        if not await self._authorize(update):
            return
        await self._reply(update, self._t(update, "help"))

    async def language(self, update: Any, context: Any) -> None:
        if not await self._authorize(update):
            return
        args = getattr(context, "args", None) or []
        requested = str(args[0]).strip().lower() if len(args) == 1 else ""
        if requested not in SUPPORTED_LANGUAGES:
            await self._reply(update, self._t(update, "language_usage"))
            return
        user_id = self._user_id(update)
        if user_id is not None:
            self._languages[user_id] = requested
        await self._reply(update, self._t(update, "language_set"))

    async def destination(self, update: Any, context: Any) -> None:
        if not await self._authorize(update, Role.OPERATOR):
            return
        args = getattr(context, "args", None) or []
        current = self._destination(update)
        if not args:
            key = "destination_current" if current else "destination_default"
            values = {"destination": current} if current else {}
            await self._reply(update, self._t(update, key, **values))
            return
        if len(args) != 1:
            await self._reply(update, self._t(update, "destination_usage"))
            return
        candidate = str(args[0]).strip()
        user_id = self._user_id(update)
        if candidate.lower() in ("clear", "default", "-"):
            if user_id is not None:
                self._destinations.pop(user_id, None)
            await self._reply(update, self._t(update, "destination_cleared"))
            return
        if not candidate or len(candidate) > 512 or any(ord(char) < 32 for char in candidate):
            await self._reply(update, self._t(update, "destination_invalid"))
            return
        if user_id is not None:
            self._destinations[user_id] = candidate
        self._remember_destination(candidate)
        await self._reply(update, self._t(update, "destination_set", destination=candidate))

    async def destinations(self, update: Any, context: Any) -> None:
        del context
        if not await self._authorize(update, Role.OPERATOR):
            return
        if not self._recent_destinations:
            await self._reply(update, self._t(update, "destinations_none"))
            return
        lines = "\n".join("{}. {}".format(index, value) for index, value in enumerate(self._recent_destinations, 1))
        await self._reply(update, self._t(update, "destinations_recent", destinations=lines))

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
        buttons = []
        for item in tasks:
            progress = 0.0
            if item.size_bytes > 0:
                progress = min(100.0, item.transfer.downloaded_bytes * 100.0 / item.size_bytes)
            title = item.title or item.task_id
            lines.append("{} — {} — {:.1f}%".format(title, item.status, progress))
            action = "resume" if item.status == "paused" else "pause"
            # Telegram caps callback data at 64 UTF-8 bytes. Tasks whose DSM id
            # cannot be represented safely remain visible but are not mutable
            # from the chat UI.
            if len("task:delete-confirm:{}".format(item.task_id).encode("utf-8")) <= 64:
                buttons.append(
                    [
                        InlineKeyboardButton(
                            action.title(), callback_data="task:{}:{}".format(action, item.task_id)
                        ),
                        InlineKeyboardButton(
                            "Delete", callback_data="task:delete:{}".format(item.task_id)
                        ),
                    ]
                )
        message = getattr(update, "effective_message", None)
        if message is not None:
            markup = InlineKeyboardMarkup(buttons) if buttons else None
            await message.reply_text("\n".join(lines), reply_markup=markup)

    async def history(self, update: Any, context: Any) -> None:
        """Show recent durable lifecycle events without contacting DSM."""
        if not await self._authorize(update):
            return
        args = getattr(context, "args", None) or []
        try:
            limit = int(args[0]) if args else 10
        except (TypeError, ValueError):
            limit = 10
        limit = max(1, min(limit, 20))
        events = await asyncio.to_thread(self.core.tasks.history, limit)
        if not events:
            await self._reply(update, self._t(update, "history_none"))
            return
        lines = []
        for event in events:
            transition = event.new_status or event.event_type
            lines.append("{} — {} — {}".format(event.task_id, event.event_type, transition))
        await self._reply(update, self._t(update, "history", events="\n".join(lines)))

    async def notifications(self, update: Any, context: Any) -> None:
        """Configure durable notification delivery policy for the caller."""
        if not await self._authorize(update):
            return
        user_id = self._user_id(update)
        args = [str(value) for value in (getattr(context, "args", None) or [])]
        if user_id is None or not args:
            await self._reply(update, self._t(update, "notifications_usage"))
            return
        action = args[0].lower()
        try:
            if action in ("on", "off") and len(args) == 1:
                await asyncio.to_thread(
                    self.core.tasks.set_notification_preference,
                    user_id,
                    enabled=action == "on",
                )
            elif action == "clear" and len(args) == 1:
                await asyncio.to_thread(
                    self.core.tasks.set_notification_preference, user_id, enabled=True
                )
            elif action == "quiet" and len(args) == 4:
                await asyncio.to_thread(
                    self.core.tasks.set_notification_preference,
                    user_id,
                    enabled=True,
                    quiet_start=args[1],
                    quiet_end=args[2],
                    timezone_name=args[3],
                )
            else:
                raise ValueError("invalid notification preference command")
        except ValueError:
            await self._reply(update, self._t(update, "notifications_usage"))
            return
        await self._reply(update, self._t(update, "notifications_set"))

    async def task_control(self, update: Any, context: Any) -> None:
        """Handle authorized, narrowly-scoped task mutation callbacks."""
        del context
        query = getattr(update, "callback_query", None)
        if query is None:
            return
        await query.answer()
        if not await self._authorize(update, Role.OPERATOR):
            return
        parts = str(getattr(query, "data", "") or "").split(":", 2)
        if len(parts) != 3 or parts[0] != "task" or not parts[2]:
            await self._reply(update, "This task action is invalid or expired.")
            return
        action, task_id = parts[1], parts[2]
        if action == "delete":
            markup = InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton(
                        "Confirm delete", callback_data="task:delete-confirm:{}".format(task_id)
                    ),
                    InlineKeyboardButton("Cancel", callback_data="task:cancel:{}".format(task_id)),
                ]]
            )
            await query.edit_message_reply_markup(reply_markup=markup)
            return
        if action == "cancel":
            await query.edit_message_reply_markup(reply_markup=None)
            await self._reply(update, "Task deletion cancelled.")
            return
        mutations = {
            "pause": self.core.client.pause,
            "resume": self.core.client.resume,
            "delete-confirm": self.core.client.delete,
        }
        mutation = mutations.get(action)
        if mutation is None:
            await self._reply(update, "This task action is invalid or expired.")
            return
        try:
            await asyncio.to_thread(mutation, task_id)
        except (SynologyError, ValueError):
            await self._reply(update, "Download Station could not update that task.")
            return
        await query.edit_message_reply_markup(reply_markup=None)
        past_tense = {"pause": "paused", "resume": "resumed", "delete-confirm": "deleted"}
        await self._reply(update, "Task {}.".format(past_tense[action]))

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
                destination = self._destination(update)
                if destination:
                    await asyncio.to_thread(self.core.client.create_file, target, destination)
                    self._remember_destination(destination)
                else:
                    await asyncio.to_thread(self.core.client.create_file, target)
        except (SynologyError, OSError):
            await self._reply(update, "Could not submit the torrent to Download Station.")
            return
        if destination:
            response = self._t(update, "torrent_submitted", destination=destination)
        else:
            response = self._t(update, "torrent_submitted_default")
        await self._reply(update, response)

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
        destination = self._destination(update)
        try:
            if destination:
                await asyncio.to_thread(self.core.client.create_url, value, destination)
                self._remember_destination(destination)
            else:
                await asyncio.to_thread(self.core.client.create_url, value)
        except (SynologyError, ValueError):
            await self._reply(update, "Download Station rejected the URL.")
            return
        if destination:
            response = self._t(update, "url_submitted", destination=destination)
        else:
            response = self._t(update, "url_submitted_default")
        await self._reply(update, response)

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
