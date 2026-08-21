"""python-telegram-bot application composition and lifecycle management."""

from __future__ import annotations

import inspect
from typing import Any, Optional

from telegram import BotCommand
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from ..app import ApplicationComponents
from ..config import Settings


COMMAND_MENU = (
    ("start", "Start Synobot and check readiness"),
    ("help", "Show the command guide"),
    ("health", "Check Synobot and DSM connectivity"),
    ("tasks", "View and manage active downloads"),
    ("stats", "Show current download and upload speeds"),
    ("add", "Add a URL or magnet download"),
    ("history", "Show recent download activity"),
    ("destination", "View or set the download folder"),
    ("destinations", "Show recently used folders"),
    ("notifications", "Manage download notifications"),
    ("language", "Switch between English and Arabic"),
    ("dslogin", "Reconnect Synobot to DSM"),
)


async def _invoke(target: Any, method: str) -> None:
    """Invoke a synchronous or asynchronous lifecycle method."""
    result = getattr(target, method)()
    # ``AsyncTaskMonitor.start`` intentionally returns its long-running Task as
    # a handle. Await coroutine lifecycle methods, but never await that
    # background Task or Telegram polling will never start.
    if inspect.iscoroutine(result):
        await result


def build_application(
    settings: Settings,
    components: ApplicationComponents,
    *,
    handlers: Optional[Any] = None,
    monitor: Optional[Any] = None,
) -> Application:
    """Build the Telegram adapter without starting polling or network traffic.

    ``handlers`` and ``monitor`` are injectable so the adapter can be tested
    without Telegram or DSM.  The monitor must expose ``start`` and ``stop``.
    """
    if handlers is None:
        from .handlers import TelegramHandlers

        handlers = TelegramHandlers(
            components.core, components.authorization, settings
        )

    async def post_init(application: Application) -> None:
        if application.bot_data.get("synobot_started"):
            return
        await application.bot.set_my_commands(
            [BotCommand(command, description) for command, description in COMMAND_MENU]
        )
        application.bot_data["synobot_started"] = True
        if monitor is not None:
            await _invoke(monitor, "start")

    async def post_shutdown(application: Application) -> None:
        if application.bot_data.get("synobot_closed"):
            return
        application.bot_data["synobot_closed"] = True
        try:
            if monitor is not None:
                await _invoke(monitor, "stop")
        finally:
            components.close()

    application = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    application.bot_data.update(
        {
            "synobot_components": components,
            "synobot_handlers": handlers,
            "synobot_monitor": monitor,
        }
    )

    for command, callback in (
        ("start", handlers.start),
        ("help", handlers.help),
        ("health", handlers.health),
        ("tasks", handlers.tasks),
        ("task", handlers.tasks),
        ("stats", handlers.stats),
        ("stat", handlers.stats),
        ("dslogin", handlers.dslogin),
        ("add", handlers.add),
    ):
        application.add_handler(CommandHandler(command, callback))
    # Optional lookup keeps lightweight injected handler doubles compatible
    # while the concrete TelegramHandlers always exposes the Phase 6 commands.
    for command in ("language", "destination", "destinations", "history", "notifications"):
        callback = getattr(handlers, command, None)
        if callback is not None:
            application.add_handler(CommandHandler(command, callback))
    application.add_handler(MessageHandler(filters.Document.ALL, handlers.document))
    application.add_handler(CallbackQueryHandler(handlers.task_control, pattern=r"^task:"))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.text)
    )
    application.add_error_handler(handlers.error)
    return application


# Descriptive alias retained for callers that prefer an explicit name.
build_telegram_application = build_application


__all__ = ["COMMAND_MENU", "build_application", "build_telegram_application"]
