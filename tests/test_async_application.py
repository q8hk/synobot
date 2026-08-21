"""Composition tests for the PTB application adapter (no network traffic)."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from synobot.telegram import application as adapter


class FakeBuilder:
    last = None

    def __init__(self):
        self.value = SimpleNamespace(
            bot=SimpleNamespace(set_my_commands=AsyncMock()),
            bot_data={},
            handlers=[],
            error_handlers=[],
        )
        FakeBuilder.last = self

    def token(self, value):
        self.token_value = value
        return self

    def post_init(self, callback):
        self.init_callback = callback
        return self

    def post_shutdown(self, callback):
        self.shutdown_callback = callback
        return self

    def build(self):
        self.value.add_handler = self.value.handlers.append
        self.value.add_error_handler = self.value.error_handlers.append
        return self.value


class FakeCommandHandler:
    def __init__(self, command, callback):
        self.command = command
        self.callback = callback


class FakeMessageHandler:
    def __init__(self, message_filter, callback):
        self.message_filter = message_filter
        self.callback = callback


class FakeCallbackQueryHandler:
    def __init__(self, callback, pattern=None):
        self.callback = callback
        self.pattern = pattern


class FakeFilter:
    def __and__(self, other):
        return ("and", self, other)

    def __invert__(self):
        return ("not", self)


@pytest.fixture
def ptb(monkeypatch):
    monkeypatch.setattr(adapter, "ApplicationBuilder", FakeBuilder)
    monkeypatch.setattr(adapter, "CommandHandler", FakeCommandHandler)
    monkeypatch.setattr(adapter, "MessageHandler", FakeMessageHandler)
    monkeypatch.setattr(adapter, "CallbackQueryHandler", FakeCallbackQueryHandler)
    monkeypatch.setattr(
        adapter,
        "filters",
        SimpleNamespace(
            Document=SimpleNamespace(ALL=FakeFilter()),
            TEXT=FakeFilter(),
            COMMAND=FakeFilter(),
        ),
    )


def fake_handlers():
    names = (
        "start", "help", "health", "tasks", "stats", "dslogin", "add", "text",
        "document", "task_control", "destination_control", "error",
    )
    return SimpleNamespace(**{name: AsyncMock(name=name) for name in names})


def test_build_registers_routes_and_keeps_components(ptb):
    settings = SimpleNamespace(telegram_bot_token="secret")
    components = Mock()
    handlers = fake_handlers()

    app = adapter.build_application(settings, components, handlers=handlers)

    assert FakeBuilder.last.token_value == "secret"
    assert [item.command for item in app.handlers[:9]] == [
        "start", "help", "health", "tasks", "task", "stats", "stat", "dslogin", "add"
    ]
    assert len(app.handlers) == 13
    assert app.handlers[10].pattern == r"^task:"
    assert app.handlers[11].pattern == r"^dest:"
    assert app.error_handlers == [handlers.error]
    assert app.bot_data["synobot_components"] is components
    assert app.bot_data["synobot_handlers"] is handlers


@pytest.mark.asyncio
async def test_lifecycle_starts_stops_and_closes_exactly_once(ptb):
    settings = SimpleNamespace(telegram_bot_token="secret")
    components = Mock()
    monitor = SimpleNamespace(start=AsyncMock(), stop=AsyncMock())
    app = adapter.build_application(
        settings, components, handlers=fake_handlers(), monitor=monitor
    )

    await FakeBuilder.last.init_callback(app)
    await FakeBuilder.last.init_callback(app)
    await FakeBuilder.last.shutdown_callback(app)
    await FakeBuilder.last.shutdown_callback(app)

    monitor.start.assert_awaited_once_with()
    app.bot.set_my_commands.assert_awaited_once()
    menu = app.bot.set_my_commands.await_args.args[0]
    assert [(item.command, item.description) for item in menu] == list(adapter.COMMAND_MENU)
    monitor.stop.assert_awaited_once_with()
    components.close.assert_called_once_with()


@pytest.mark.asyncio
async def test_startup_does_not_await_long_running_monitor_task(ptb):
    settings = SimpleNamespace(telegram_bot_token="secret")
    components = Mock()
    release = asyncio.Event()

    async def background_monitor():
        await release.wait()

    task = asyncio.create_task(background_monitor())
    monitor = SimpleNamespace(start=Mock(return_value=task), stop=AsyncMock())
    app = adapter.build_application(
        settings, components, handlers=fake_handlers(), monitor=monitor
    )

    await asyncio.wait_for(FakeBuilder.last.init_callback(app), timeout=0.1)

    assert not task.done()
    monitor.start.assert_called_once_with()
    release.set()
    await task


@pytest.mark.asyncio
async def test_shutdown_closes_components_when_monitor_stop_fails(ptb):
    settings = SimpleNamespace(telegram_bot_token="secret")
    components = Mock()
    monitor = SimpleNamespace(start=Mock(), stop=AsyncMock(side_effect=RuntimeError("boom")))
    app = adapter.build_application(
        settings, components, handlers=fake_handlers(), monitor=monitor
    )

    with pytest.raises(RuntimeError, match="boom"):
        await FakeBuilder.last.shutdown_callback(app)
    components.close.assert_called_once_with()


def test_cli_composes_monitor_and_runs_polling(monkeypatch):
    import telegram
    from synobot import __main__ as cli

    settings = SimpleNamespace(
        dsm_poll_interval_seconds=17.0,
        telegram_notify_user_ids=(123,),
        database_path=Path("/tmp/synobot-test.db"),
    )
    components = SimpleNamespace(core=object(), tasks=object(), close=Mock())
    application = SimpleNamespace(bot_data={}, run_polling=Mock())
    monitor = object()
    monkeypatch.setattr(cli.Settings, "from_env", Mock(return_value=settings))
    monkeypatch.setattr(cli, "build_components", Mock(return_value=components))
    monitor_factory = Mock(return_value=monitor)
    monkeypatch.setattr(cli, "AsyncTaskMonitor", monitor_factory)
    notification_service = SimpleNamespace(drain=AsyncMock())
    notification_factory = Mock(return_value=notification_service)
    monkeypatch.setattr(cli, "TelegramNotificationService", notification_factory)
    build = Mock(return_value=application)
    monkeypatch.setattr(cli, "build_application", build)
    monkeypatch.setattr(
        telegram, "Update", SimpleNamespace(ALL_TYPES=("message",)), raising=False
    )

    cli.main()

    notification_factory.assert_called_once()
    monitor_factory.assert_called_once()
    assert monitor_factory.call_args.kwargs["interval"] == 17.0
    assert monitor_factory.call_args.kwargs["notification_callback"] is notification_service.drain
    build.assert_called_once_with(settings, components, monitor=monitor)
    application.run_polling.assert_called_once_with(allowed_updates=("message",))
    components.close.assert_called_once_with()
