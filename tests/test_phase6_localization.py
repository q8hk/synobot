import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from synobot.authorization import AuthorizationPolicy
from synobot.config import Settings
from synobot.telegram.handlers import TelegramHandlers
from synobot.synology.models import Task
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
    tasks = Mock()
    tasks.destination_preference.return_value = None
    tasks.rank_destinations.side_effect = lambda user_id, observed, fallbacks: list(
        dict.fromkeys([*observed, *fallbacks])
    )
    core = SimpleNamespace(client=client, tasks=tasks)
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


def test_destination_is_persisted_and_applied_to_url():
    handlers, client = _handlers()
    item = _update()
    _run(handlers.destination(item, SimpleNamespace(args=["video/incoming"])))
    handlers.core.tasks.destination_preference.return_value = "video/incoming"
    _run(handlers.add(item, SimpleNamespace(args=["https://example.com/movie.mkv"])))
    client.create_url.assert_called_once_with(
        "https://example.com/movie.mkv", "video/incoming"
    )

    handlers.core.tasks.set_destination_preference.assert_called_once_with(
        2, "video/incoming"
    )
    handlers.core.tasks.record_destination_use.assert_called_once_with(
        2, "video/incoming"
    )


def test_destination_clear_restores_default_client_call_signature():
    handlers, client = _handlers()
    item = _update()
    _run(handlers.destination(item, SimpleNamespace(args=["downloads"])))
    _run(handlers.destination(item, SimpleNamespace(args=["clear"])))
    handlers.core.tasks.destination_preference.return_value = None
    _run(handlers.add(item, SimpleNamespace(args=["magnet:?xt=urn:btih:abc"])))
    client.create_url.assert_called_once_with("magnet:?xt=urn:btih:abc")


def test_destination_chooser_uses_ranked_buttons_without_counters():
    handlers, client = _handlers()
    handlers.core.tasks.rank_destinations.return_value = [
        "TVShows", "Movies", "Download", "Download/YouTube"
    ]
    client.list_tasks.return_value = [
        Task(
            "one",
            raw={"additional": {"detail": {"destination": "TVShows/incomplete"}}},
        )
    ]
    item = _update()

    _run(handlers.destination(item, SimpleNamespace(args=[])))

    reply = item.effective_message.reply_text.await_args
    buttons = reply.kwargs["reply_markup"].inline_keyboard
    assert [row[0].text for row in buttons[:3]] == [
        "📺 TVShows", "🎬 Movies", "📥 Download"
    ]
    assert all("used" not in row[0].text.casefold() for row in buttons)
    observed = handlers.core.tasks.rank_destinations.call_args.args[1]
    assert observed == ["TVShows"]


def test_destination_callback_persists_valid_choice_and_rejects_stale_choice():
    handlers, client = _handlers()
    client.list_tasks.return_value = []
    handlers.core.tasks.rank_destinations.side_effect = None
    handlers.core.tasks.rank_destinations.return_value = ["Movies", "TVShows", "Download"]
    token = handlers._destination_token("Movies")
    selected = _update()
    selected.callback_query = SimpleNamespace(
        data="dest:set:{}".format(token),
        answer=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
    )

    _run(handlers.destination_control(selected, SimpleNamespace()))

    handlers.core.tasks.set_destination_preference.assert_called_with(2, "Movies")
    assert "Movies" in selected.effective_message.reply_text.await_args.args[0]

    handlers.core.tasks.set_destination_preference.reset_mock()
    handlers.core.tasks.rank_destinations.return_value = ["TVShows"]
    stale = _update()
    stale.callback_query = SimpleNamespace(
        data="dest:set:{}".format(token),
        answer=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
    )
    _run(handlers.destination_control(stale, SimpleNamespace()))
    handlers.core.tasks.set_destination_preference.assert_not_called()
    assert "no longer available" in stale.effective_message.reply_text.await_args.args[0]


def test_destination_callback_data_stays_within_telegram_limit():
    destination = "nested/" + "a" * 500
    callback = "dest:set:{}".format(TelegramHandlers._destination_token(destination))
    assert len(callback.encode("utf-8")) <= 64
