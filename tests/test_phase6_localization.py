import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from synobot.authorization import AuthorizationPolicy
from synobot.config import Settings
from synobot.telegram.handlers import TelegramHandlers
from synobot.telegram.localization import normalize_language, translate


def _run(coro):
    return asyncio.run(coro)


def _settings(language="en"):
    return Settings(
        telegram_bot_token="token",
        telegram_admin_user_ids=(1,),
        telegram_notify_user_ids=(1,),
        dsm_base_url="https://nas.local:5001",
        dsm_username="bot",
        telegram_language=language,
    )


def _update(user_id=2):
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(type="private"),
        effective_message=SimpleNamespace(reply_text=AsyncMock()),
    )


def _handlers(language="en"):
    client = Mock(authenticated=True)
    core = SimpleNamespace(client=client)
    policy = AuthorizationPolicy.create([1], operators=[2])
    return TelegramHandlers(core, policy, _settings(language)), client


def test_arabic_catalogue_normalizes_regional_language_and_formats():
    assert normalize_language("ar_KW") == "ar"
    assert "العربية" in translate("ar-KW", "language_set")
    assert "downloads" in translate("ar", "destination_set", destination="downloads")


def test_language_command_changes_only_requesting_users_language():
    handlers, _ = _handlers()
    arabic_user = _update(2)
    _run(handlers.language(arabic_user, SimpleNamespace(args=["ar"])))
    assert "العربية" in arabic_user.effective_message.reply_text.await_args.args[0]

    english_admin = _update(1)
    _run(handlers.start(english_admin, SimpleNamespace()))
    assert "Use /help" in english_admin.effective_message.reply_text.await_args.args[0]


def test_destination_is_applied_to_url_and_recent_list_without_persistence():
    handlers, client = _handlers()
    item = _update()
    _run(handlers.destination(item, SimpleNamespace(args=["video/incoming"])))
    _run(handlers.add(item, SimpleNamespace(args=["https://example.com/movie.mkv"])))
    client.create_url.assert_called_once_with(
        "https://example.com/movie.mkv", "video/incoming"
    )

    item.effective_message.reply_text.reset_mock()
    _run(handlers.destinations(item, SimpleNamespace()))
    response = item.effective_message.reply_text.await_args.args[0]
    assert "1. video/incoming" in response


def test_destination_clear_restores_default_client_call_signature():
    handlers, client = _handlers()
    item = _update()
    _run(handlers.destination(item, SimpleNamespace(args=["downloads"])))
    _run(handlers.destination(item, SimpleNamespace(args=["clear"])))
    _run(handlers.add(item, SimpleNamespace(args=["magnet:?xt=urn:btih:abc"])))
    client.create_url.assert_called_once_with("magnet:?xt=urn:btih:abc")
