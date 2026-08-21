"""Command-line entry point for ``python -m synobot``."""

from __future__ import annotations

from .app import build_components
from .config import Settings
from .monitoring import AsyncTaskMonitor
from .notifications import TelegramNotificationService
from .telegram.application import build_application


def main() -> None:
    """Load configuration, compose Synobot, and run Telegram polling."""
    settings = Settings.from_env()
    components = build_components(settings)
    application_holder = {}

    async def send_message(chat_id: int, text: str) -> None:
        application = application_holder["application"]
        await application.bot.send_message(chat_id=chat_id, text=text)

    notifications = TelegramNotificationService(
        components.tasks,
        settings.telegram_notify_user_ids,
        send=send_message,
    )

    async def announce_status(text: str) -> None:
        for chat_id in settings.telegram_notify_user_ids:
            await send_message(chat_id, text)

    try:
        monitor = AsyncTaskMonitor(
            components.core,
            interval=settings.dsm_poll_interval_seconds,
            status_callback=announce_status,
            notification_callback=notifications.drain,
        )
        application = build_application(settings, components, monitor=monitor)
        application_holder["application"] = application
    except BaseException:
        components.close()
        raise
    from telegram import Update

    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    finally:
        # PTB normally executes post_shutdown.  Still close if startup/polling
        # aborted before that hook so the DSM session and SQLite handle do not
        # leak.  The shared marker prevents a second close.
        if not application.bot_data.get("synobot_closed"):
            application.bot_data["synobot_closed"] = True
            components.close()


if __name__ == "__main__":
    main()
