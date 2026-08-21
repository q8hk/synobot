"""Async Telegram handlers backed by the synchronous Synobot core.

The adapter deliberately accepts normal python-telegram-bot Update/Context
objects by protocol (duck typing).  This keeps all network and persistence work
behind ``asyncio.to_thread`` and makes the handlers straightforward to test.
"""

import asyncio
import hashlib
import logging
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
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
_FOLLOW_UP_TTL_SECONDS = 300


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
        self._languages: dict[int, str] = {}
        self._pending_commands: dict[int, tuple[str, float]] = {}

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

    async def _destination(self, update: Any) -> Optional[str]:
        user_id = self._user_id(update)
        if user_id is None:
            return None
        return await asyncio.to_thread(self.core.tasks.destination_preference, user_id)

    @staticmethod
    def _canonical_destination(value: Any) -> Optional[str]:
        destination = str(value or "").strip().strip("/")
        if destination.lower().endswith("/incomplete"):
            destination = destination[: -len("/incomplete")].rstrip("/")
        if (not destination or len(destination) > 512
                or any(ord(char) < 32 for char in destination)):
            return None
        return destination

    @staticmethod
    def _destination_token(destination: str) -> str:
        return hashlib.sha256(destination.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _destination_label(destination: str) -> str:
        lowered = destination.casefold()
        if "tv" in lowered:
            return "📺 {}".format(destination)
        if "movie" in lowered or "film" in lowered:
            return "🎬 {}".format(destination)
        if "download" in lowered:
            return "📥 {}".format(destination)
        return "📂 {}".format(destination)

    def _set_pending(self, update: Any, command: str) -> None:
        user_id = self._user_id(update)
        if user_id is not None:
            self._pending_commands[user_id] = (
                command, time.monotonic() + _FOLLOW_UP_TTL_SECONDS
            )

    def _take_pending(self, update: Any) -> Optional[str]:
        user_id = self._user_id(update)
        if user_id is None:
            return None
        pending = self._pending_commands.pop(user_id, None)
        if pending is None or pending[1] < time.monotonic():
            return None
        return pending[0]

    def _clear_pending(self, update: Any) -> None:
        user_id = self._user_id(update)
        if user_id is not None:
            self._pending_commands.pop(user_id, None)

    async def _prompt_language(self, update: Any) -> None:
        self._set_pending(update, "language")
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("English", callback_data="cmd:language:en"),
            InlineKeyboardButton("العربية", callback_data="cmd:language:ar"),
        ], [InlineKeyboardButton("Cancel", callback_data="cmd:cancel")]])
        message = getattr(update, "effective_message", None)
        if message is not None:
            await message.reply_text(self._t(update, "language_prompt"), reply_markup=markup)

    async def _prompt_notifications(self, update: Any) -> None:
        self._set_pending(update, "notifications")
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔔 On", callback_data="cmd:notifications:on"),
             InlineKeyboardButton("🔕 Off", callback_data="cmd:notifications:off")],
            [InlineKeyboardButton("🌙 Quiet hours", callback_data="cmd:notifications:quiet"),
             InlineKeyboardButton("↺ Reset", callback_data="cmd:notifications:clear")],
            [InlineKeyboardButton("Cancel", callback_data="cmd:cancel")],
        ])
        message = getattr(update, "effective_message", None)
        if message is not None:
            await message.reply_text(
                self._t(update, "notifications_prompt"), reply_markup=markup
            )

    async def _prompt_add(self, update: Any) -> None:
        self._set_pending(update, "add")
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("Cancel", callback_data="cmd:cancel")
        ]])
        message = getattr(update, "effective_message", None)
        if message is not None:
            await message.reply_text(self._t(update, "add_prompt"), reply_markup=markup)

    async def _destination_choices(self, update: Any) -> list[str]:
        user_id = self._user_id(update)
        if user_id is None:
            return []
        observed: list[str] = []
        try:
            tasks = await asyncio.to_thread(self.core.client.list_tasks, True)
            for task in tasks:
                additional = task.raw.get("additional")
                additional = additional if isinstance(additional, dict) else {}
                detail = additional.get("detail")
                detail = detail if isinstance(detail, dict) else {}
                candidate = self._canonical_destination(
                    detail.get("destination") or task.raw.get("destination")
                )
                if candidate:
                    observed.append(candidate)
        except SynologyError:
            pass
        fallbacks = tuple(
            candidate
            for value in self.settings.dsm_destination_presets
            if (candidate := self._canonical_destination(value))
        )
        return await asyncio.to_thread(
            self.core.tasks.rank_destinations, user_id, observed, fallbacks
        )

    async def _destination_markup(self, update: Any, *, expanded: bool = False):
        choices = await self._destination_choices(update)
        visible = choices[:8 if expanded else 3]
        rows = [[InlineKeyboardButton(
            self._destination_label(destination),
            callback_data="dest:set:{}".format(self._destination_token(destination)),
        )] for destination in visible]
        rows.append([InlineKeyboardButton("⚙️ Download Station default", callback_data="dest:default")])
        if not expanded and len(choices) > 3:
            rows.append([InlineKeyboardButton("📂 More destinations", callback_data="dest:more")])
        return InlineKeyboardMarkup(rows), choices

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
        if not args:
            await self._prompt_language(update)
            return
        requested = str(args[0]).strip().lower() if len(args) == 1 else ""
        if requested not in SUPPORTED_LANGUAGES:
            await self._prompt_language(update)
            return
        self._clear_pending(update)
        user_id = self._user_id(update)
        if user_id is not None:
            self._languages[user_id] = requested
        await self._reply(update, self._t(update, "language_set"))

    async def destination(self, update: Any, context: Any) -> None:
        if not await self._authorize(update, Role.OPERATOR):
            return
        args = getattr(context, "args", None) or []
        if not args:
            self._set_pending(update, "destination")
            current = await self._destination(update)
            key = "destination_current" if current else "destination_default"
            values = {"destination": current} if current else {}
            markup, _ = await self._destination_markup(update)
            message = getattr(update, "effective_message", None)
            if message is not None:
                await message.reply_text(
                    self._t(update, key, **values) + "\n\n"
                    + self._t(update, "destination_incomplete"),
                    reply_markup=markup,
                )
            return
        candidate = " ".join(str(value) for value in args).strip()
        user_id = self._user_id(update)
        if candidate.lower() in ("clear", "default", "-"):
            if user_id is not None:
                await asyncio.to_thread(
                    self.core.tasks.set_destination_preference, user_id, None
                )
            self._clear_pending(update)
            await self._reply(update, self._t(update, "destination_cleared"))
            return
        candidate = self._canonical_destination(candidate)
        if candidate is None:
            self._set_pending(update, "destination")
            markup, _ = await self._destination_markup(update)
            message = getattr(update, "effective_message", None)
            if message is not None:
                await message.reply_text(
                    self._t(update, "destination_invalid") + "\n\n"
                    + self._t(update, "destination_choose"),
                    reply_markup=markup,
                )
            return
        if user_id is not None:
            await asyncio.to_thread(
                self.core.tasks.set_destination_preference, user_id, candidate
            )
        self._clear_pending(update)
        await self._reply(update, self._t(update, "destination_set", destination=candidate))

    async def destinations(self, update: Any, context: Any) -> None:
        del context
        if not await self._authorize(update, Role.OPERATOR):
            return
        markup, choices = await self._destination_markup(update, expanded=True)
        if not choices:
            await self._reply(update, self._t(update, "destinations_none"))
            return
        message = getattr(update, "effective_message", None)
        if message is not None:
            await message.reply_text(self._t(update, "destination_choose"), reply_markup=markup)

    async def destination_control(self, update: Any, context: Any) -> None:
        """Apply a validated destination selected from an inline keyboard."""
        del context
        query = getattr(update, "callback_query", None)
        if query is None:
            return
        await query.answer()
        if not await self._authorize(update, Role.OPERATOR):
            return
        data = str(getattr(query, "data", "") or "")
        user_id = self._user_id(update)
        if user_id is None:
            return
        if data == "dest:default":
            await asyncio.to_thread(
                self.core.tasks.set_destination_preference, user_id, None
            )
            await query.edit_message_reply_markup(reply_markup=None)
            self._clear_pending(update)
            await self._reply(update, self._t(update, "destination_cleared"))
            return
        if data == "dest:more":
            markup, _ = await self._destination_markup(update, expanded=True)
            await query.edit_message_reply_markup(reply_markup=markup)
            return
        if not data.startswith("dest:set:"):
            await self._reply(update, self._t(update, "destination_expired"))
            return
        token = data.removeprefix("dest:set:")
        choices = await self._destination_choices(update)
        destination = next(
            (item for item in choices if self._destination_token(item) == token), None
        )
        if destination is None:
            await query.edit_message_reply_markup(reply_markup=None)
            await self._reply(update, self._t(update, "destination_expired"))
            return
        await asyncio.to_thread(
            self.core.tasks.set_destination_preference, user_id, destination
        )
        self._clear_pending(update)
        await query.edit_message_reply_markup(reply_markup=None)
        await self._reply(
            update, self._t(update, "destination_set", destination=destination)
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
        if user_id is None:
            return
        if not args:
            await self._prompt_notifications(update)
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
            await self._prompt_notifications(update)
            return
        self._clear_pending(update)
        await self._reply(update, self._t(update, "notifications_set"))

    async def command_follow_up(self, update: Any, context: Any) -> None:
        """Resume an incomplete parameterized command from an inline choice."""
        del context
        query = getattr(update, "callback_query", None)
        if query is None:
            return
        await query.answer()
        data = str(getattr(query, "data", "") or "")
        if data == "cmd:cancel":
            self._clear_pending(update)
            await query.edit_message_reply_markup(reply_markup=None)
            await self._reply(update, self._t(update, "follow_up_cancelled"))
            return
        parts = data.split(":", 2)
        if len(parts) != 3 or parts[0] != "cmd":
            return
        command, value = parts[1], parts[2]
        if command == "language":
            await self.language(update, SimpleNamespace(args=[value]))
        elif command == "notifications" and value == "quiet":
            if not await self._authorize(update):
                return
            self._set_pending(update, "notifications_quiet")
            await query.edit_message_reply_markup(reply_markup=None)
            await self._reply(update, self._t(update, "notifications_quiet_prompt"))
            return
        elif command == "notifications":
            await self.notifications(update, SimpleNamespace(args=[value]))
        else:
            return
        await query.edit_message_reply_markup(reply_markup=None)

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
        if not args:
            await self._prompt_add(update)
            return
        if len(args) != 1 or not self._supported_url(args[0], allow_general=True):
            await self._prompt_add(update)
            return
        self._clear_pending(update)
        await self._create_url(update, args[0])

    async def text(self, update: Any, context: Any) -> None:
        pending = self._take_pending(update)
        if pending is not None:
            message = getattr(update, "effective_message", None)
            value = str(getattr(message, "text", "") or "").strip()
            if value.casefold() in ("cancel", "/cancel"):
                await self._reply(update, self._t(update, "follow_up_cancelled"))
                return
            if pending == "destination":
                await self.destination(update, SimpleNamespace(args=[value]))
            elif pending == "language":
                await self.language(update, SimpleNamespace(args=[value]))
            elif pending == "add":
                await self.add(update, SimpleNamespace(args=[value]))
            elif pending == "notifications":
                await self.notifications(update, SimpleNamespace(args=value.split()))
            elif pending == "notifications_quiet":
                await self.notifications(
                    update, SimpleNamespace(args=["quiet", *value.split()])
                )
            return
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
                destination = await self._destination(update)
                if destination:
                    await asyncio.to_thread(self.core.client.create_file, target, destination)
                else:
                    await asyncio.to_thread(self.core.client.create_file, target)
        except (SynologyError, OSError):
            await self._reply(update, "Could not submit the torrent to Download Station.")
            return
        user_id = self._user_id(update)
        if destination and user_id is not None:
            await asyncio.to_thread(
                self.core.tasks.record_destination_use, user_id, destination
            )
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
        destination = await self._destination(update)
        try:
            if destination:
                await asyncio.to_thread(self.core.client.create_url, value, destination)
            else:
                await asyncio.to_thread(self.core.client.create_url, value)
        except (SynologyError, ValueError):
            await self._reply(update, "Download Station rejected the URL.")
            return
        user_id = self._user_id(update)
        if destination and user_id is not None:
            await asyncio.to_thread(
                self.core.tasks.record_destination_use, user_id, destination
            )
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
