import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from synobot.authorization import AuthorizationPolicy
from synobot.config import Settings
from synobot.synology.errors import SynologyConnectionError
from synobot.synology.models import Task, TransferStats
from synobot.telegram.handlers import TelegramHandlers


def run(coro):
    return asyncio.run(coro)


def settings():
    return Settings(
        telegram_bot_token="secret-token",
        telegram_admin_user_ids=(1,),
        telegram_notify_user_ids=(1,),
        dsm_base_url="https://nas.local:5001",
        dsm_username="bot",
    )


def update(user_id=1, chat_type="private", text=None, document=None, callback_data=None):
    message = SimpleNamespace(text=text, document=document, reply_text=AsyncMock())
    item = SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(type=chat_type),
        effective_message=message,
    )
    if callback_data is not None:
        item.callback_query = SimpleNamespace(
            data=callback_data,
            answer=AsyncMock(),
            edit_message_reply_markup=AsyncMock(),
        )
    return item


def adapter(client=None):
    client = client or Mock(authenticated=False)
    core = SimpleNamespace(client=client)
    policy = AuthorizationPolicy.create([1], operators=[2], viewers=[3])
    return TelegramHandlers(core, policy, settings()), client


def test_unauthorized_user_is_rejected_before_dsm_access():
    handlers, client = adapter()
    item = update(user_id=99)
    run(handlers.stats(item, SimpleNamespace()))
    client.statistics.assert_not_called()
    item.effective_message.reply_text.assert_awaited_once()


def test_group_chat_is_rejected():
    handlers, client = adapter()
    item = update(chat_type="group")
    run(handlers.health(item, SimpleNamespace()))
    client.statistics.assert_not_called()


def test_stats_runs_sync_client_off_event_loop_and_formats_result():
    handlers, client = adapter()
    client.statistics.return_value = TransferStats(download_speed=2048, upload_speed=1024)
    item = update()
    with patch("synobot.telegram.handlers.asyncio.to_thread", AsyncMock(side_effect=lambda f, *a: f(*a))):
        run(handlers.stats(item, SimpleNamespace()))
    item.effective_message.reply_text.assert_awaited_once_with(
        "Download: 2.0 KiB/s\nUpload: 1.0 KiB/s"
    )


def test_tasks_handles_zero_size_and_all_tasks():
    handlers, client = adapter()
    client.list_tasks.return_value = [
        Task("one", "Empty", 0, "waiting"),
        Task("two", "Half", 100, "downloading", transfer=TransferStats(downloaded_bytes=50)),
    ]
    item = update()
    run(handlers.tasks(item, SimpleNamespace()))
    reply = item.effective_message.reply_text.await_args.args[0]
    assert "Empty — waiting — 0.0%" in reply
    assert "Half — downloading — 50.0%" in reply
    markup = item.effective_message.reply_text.await_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[0][0].callback_data == "task:pause:one"
    assert markup.inline_keyboard[1][0].callback_data == "task:pause:two"


def test_operator_can_pause_and_resume_from_callback():
    handlers, client = adapter()
    for action in ("pause", "resume"):
        item = update(user_id=2, callback_data="task:{}:dbid_1".format(action))
        run(handlers.task_control(item, SimpleNamespace()))
        item.callback_query.answer.assert_awaited_once()
        getattr(client, action).assert_called_once_with("dbid_1")
        item.callback_query.edit_message_reply_markup.assert_awaited_once_with(
            reply_markup=None
        )
        item.effective_message.reply_text.assert_awaited_once_with(
            "Task {}.".format("paused" if action == "pause" else "resumed")
        )


def test_delete_requires_a_second_confirmed_callback():
    handlers, client = adapter()
    prompt = update(user_id=2, callback_data="task:delete:dbid_1")
    run(handlers.task_control(prompt, SimpleNamespace()))
    client.delete.assert_not_called()
    markup = prompt.callback_query.edit_message_reply_markup.await_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[0][0].callback_data == "task:delete-confirm:dbid_1"

    confirmed = update(user_id=2, callback_data="task:delete-confirm:dbid_1")
    run(handlers.task_control(confirmed, SimpleNamespace()))
    client.delete.assert_called_once_with("dbid_1")
    confirmed.effective_message.reply_text.assert_awaited_once_with("Task deleted.")


def test_callback_authorization_precedes_task_mutation():
    handlers, client = adapter()
    item = update(user_id=99, callback_data="task:delete-confirm:dbid_1")
    run(handlers.task_control(item, SimpleNamespace()))
    item.callback_query.answer.assert_awaited_once()
    client.delete.assert_not_called()
    item.effective_message.reply_text.assert_awaited_once_with(
        "You are not authorized to use this bot."
    )


def test_text_routes_only_magnets_and_youtube():
    handlers, client = adapter()
    magnet = update(user_id=2, text="magnet:?xt=urn:btih:abc")
    run(handlers.text(magnet, SimpleNamespace()))
    client.create_url.assert_called_once_with("magnet:?xt=urn:btih:abc")
    magnet.effective_message.reply_text.assert_awaited_once_with(
        "URL submitted to Download Station."
    )

    client.reset_mock()
    unsupported = update(user_id=2, text="https://example.com/file")
    run(handlers.text(unsupported, SimpleNamespace()))
    client.create_url.assert_not_called()


def test_add_requires_one_valid_url_and_confirms_after_success():
    handlers, client = adapter()
    item = update(user_id=2)
    run(handlers.add(item, SimpleNamespace(args=["https://example.com/file.iso"])))
    client.create_url.assert_called_once()
    item.effective_message.reply_text.assert_awaited_once_with(
        "URL submitted to Download Station."
    )


def test_rejected_url_does_not_claim_success():
    handlers, client = adapter()
    client.create_url.side_effect = SynologyConnectionError("contains no secrets")
    item = update(user_id=2)
    run(handlers.add(item, SimpleNamespace(args=["ftp://example.com/file"])))
    item.effective_message.reply_text.assert_awaited_once_with(
        "Download Station rejected the URL."
    )


def test_torrent_uses_generated_temporary_filename_and_cleans_up():
    handlers, client = adapter()
    document = SimpleNamespace(file_id="telegram-id", file_name="../../escape.torrent")
    item = update(user_id=2, document=document)
    downloaded = []

    async def download_to_drive(custom_path):
        downloaded.append(Path(custom_path))
        Path(custom_path).write_bytes(b"torrent")

    telegram_file = SimpleNamespace(download_to_drive=download_to_drive)
    context = SimpleNamespace(bot=SimpleNamespace(get_file=AsyncMock(return_value=telegram_file)))
    run(handlers.torrent(item, context))

    submitted = Path(client.create_file.call_args.args[0])
    assert submitted.name == "upload.torrent"
    assert "escape" not in str(submitted)
    assert not downloaded[0].exists()
    item.effective_message.reply_text.assert_awaited_once_with(
        "Torrent submitted to Download Station."
    )


def test_dslogin_is_admin_only():
    handlers, client = adapter()
    operator = update(user_id=2)
    run(handlers.dslogin(operator, SimpleNamespace()))
    client.login.assert_not_called()


def test_history_reads_durable_events_without_contacting_dsm():
    handlers, client = adapter()
    handlers.core.tasks = SimpleNamespace(
        history=Mock(return_value=[
            SimpleNamespace(task_id="dbid_1", event_type="status_changed", new_status="finished")
        ])
    )
    item = update(user_id=3)
    run(handlers.history(item, SimpleNamespace(args=["5"])))
    handlers.core.tasks.history.assert_called_once_with(5)
    client.list_tasks.assert_not_called()
    assert "dbid_1 — status_changed — finished" in item.effective_message.reply_text.await_args.args[0]


def test_notifications_command_persists_quiet_hours():
    handlers, _ = adapter()
    handlers.core.tasks = SimpleNamespace(set_notification_preference=Mock())
    item = update(user_id=3)
    run(handlers.notifications(
        item, SimpleNamespace(args=["quiet", "22:00", "07:00", "Asia/Kuwait"])
    ))
    handlers.core.tasks.set_notification_preference.assert_called_once_with(
        3,
        enabled=True,
        quiet_start="22:00",
        quiet_end="07:00",
        timezone_name="Asia/Kuwait",
    )
    item.effective_message.reply_text.assert_awaited_once_with(
        "Notification preferences updated."
    )


def test_error_handler_does_not_log_exception_message(caplog):
    handlers, _ = adapter()
    item = update()
    with caplog.at_level("ERROR"):
        run(handlers.error(item, SimpleNamespace(error=RuntimeError("secret-token"))))
    assert "RuntimeError" in caplog.text
    assert "secret-token" not in caplog.text
    item.effective_message.reply_text.assert_awaited_once_with(
        "An unexpected error occurred."
    )
