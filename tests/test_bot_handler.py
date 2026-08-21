"""Characterization tests for the legacy Telegram adapter.

The production project pins an old python-telegram-bot beta.  These tests do
not need that package: the handler API surface used at import time is stubbed
before ``bothandler`` is imported.
"""
import importlib
import os
import sys
import types
import unittest
from unittest.mock import Mock, patch


def _install_telegram_stubs():
    telegram = types.ModuleType("telegram")
    ext = types.ModuleType("telegram.ext")
    error = types.ModuleType("telegram.error")

    class Filters:
        text = object()
        document = object()

    ext.Updater = Mock
    ext.CommandHandler = Mock
    ext.MessageHandler = Mock
    ext.Filters = Filters
    for name in (
        "TelegramError", "Unauthorized", "BadRequest", "TimedOut",
        "ChatMigrated", "NetworkError",
    ):
        setattr(error, name, type(name, (Exception,), {}))
    sys.modules["telegram"] = telegram
    sys.modules["telegram.ext"] = ext
    sys.modules["telegram.error"] = error


_install_telegram_stubs()

# Keep this test module runnable in the repository's intentionally minimal
# development environment, where requests/pyotp may not be installed.
synods_stub = types.ModuleType("synods")
synods_stub.SynoDownloadStation = type(
    "SynoDownloadStation", (), {"instance": classmethod(lambda cls: cls())}
)
otp_stub = types.ModuleType("OtpHandler")
otp_stub.OtpHandler = type("OtpHandler", (), {"instance": classmethod(lambda cls: cls())})
sys.modules["synods"] = synods_stub
sys.modules["OtpHandler"] = otp_stub
bothandler = importlib.import_module("bothandler")


class FakeLanguage:
    def GetBotHandlerLang(self, key):
        values = {
            "dsm_try_login": "trying login",
            "dsm_not_login": "not logged in",
            "dsm_task_list": "task list",
            "dsm_statistic": "statistics",
            "input_login_pw": "enter password",
            "noti_delete_pw": "password deleted",
            "noti_delete_otp": "otp deleted",
            "noti_magnet_link": "magnet accepted",
            "noti_youtube_link": "youtube accepted",
            "noti_not_support_cmd": "unsupported",
            "noti_torrent_file": "torrent accepted: %s",
            "noti_torrent_file_fail": "torrent failed: %s",
            "noti_not_torrent_file": "not torrent: %s",
        }
        return values[key]


def make_update(user_id=7, text=""):
    message = Mock()
    message.from_user.id = user_id
    message.text = text
    return types.SimpleNamespace(message=message)


class TelegramHandlerTests(unittest.TestCase):
    def setUp(self):
        self.handler = bothandler.BotHandler()
        self.handler.valid_users = [7]
        self.handler.lang = FakeLanguage()
        self.handler.ds = Mock()
        self.handler.ds.auth_cookie = object()
        self.handler.cfg = Mock()
        self.handler.cfg.GetDsmPwId.return_value = 7
        self.handler.BotUpdater = types.SimpleNamespace(bot=Mock())
        self.handler.cur_mode = ""
        self.handler.otp_code = ""
        self.handler.otp_input = False

    def test_valid_and_invalid_user_authorization(self):
        self.assertTrue(self.handler.CheckValidUser(7))
        self.assertFalse(self.handler.CheckValidUser(99))

    def test_start_and_help_reply_for_valid_user(self):
        update = make_update()
        self.handler.start(update, None)
        update.message.reply_text.assert_called_once_with("Hi!")
        update.message.reset_mock()
        self.handler.help(update, None)
        update.message.reply_text.assert_called_once_with(self.handler.synobot_cmd_list)

    def test_commands_are_silent_for_invalid_user(self):
        for method in (self.handler.start, self.handler.help, self.handler.dslogin,
                       self.handler.TaskList, self.handler.Statistic):
            update = make_update(user_id=99)
            method(update, None)
            update.message.reply_text.assert_not_called()

    def test_dslogin_announces_and_starts_login(self):
        update = make_update()
        self.handler.StartDsmLogin = Mock()
        self.handler.dslogin(update, None)
        update.message.reply_text.assert_called_once_with("trying login")
        self.handler.StartDsmLogin.assert_called_once_with()

    def test_task_and_stat_require_dsm_login(self):
        self.handler.ds.auth_cookie = None
        for method in (self.handler.TaskList, self.handler.Statistic):
            update = make_update()
            method(update, None)
            update.message.reply_text.assert_called_once_with("not logged in")
        self.handler.ds.GetTaskDetail.assert_not_called()
        self.handler.ds.GetStatistic.assert_not_called()

    def test_task_and_stat_route_when_logged_in(self):
        update = make_update()
        self.handler.TaskList(update, None)
        update.message.reply_text.assert_called_once_with("task list")
        self.handler.ds.GetTaskDetail.assert_called_once_with()
        update = make_update()
        self.handler.Statistic(update, None)
        update.message.reply_text.assert_called_once_with("statistics")
        self.handler.ds.GetStatistic.assert_called_once_with()

    def test_magnet_and_supported_youtube_urls_route_to_dsm(self):
        cases = (
            ("magnet:?xt=urn:btih:abc", "magnet accepted"),
            ("https://www.youtube.com/watch?v=abc", "youtube accepted"),
            ("https://youtu.be/abc", "youtube accepted"),
        )
        for url, response in cases:
            with self.subTest(url=url):
                self.handler.ds.CreateTaskForUrl.reset_mock()
                update = make_update(text=url)
                self.handler.msg_handler(update, None)
                self.handler.ds.CreateTaskForUrl.assert_called_once_with(url)
                update.message.reply_text.assert_called_once_with(response)

    def test_unsupported_text_returns_notice_and_help(self):
        update = make_update(text="hello")
        self.handler.msg_handler(update, None)
        self.assertEqual(
            [c.args[0] for c in update.message.reply_text.call_args_list],
            ["unsupported", self.handler.synobot_cmd_list],
        )
        self.handler.ds.CreateTaskForUrl.assert_not_called()

    def test_interactive_username_is_stored_then_requests_password(self):
        self.handler.cur_mode = "input_id"
        update = make_update(text="nas-user")
        self.handler.current_mode_handle(update, None)
        self.handler.cfg.SetDsmId.assert_called_once_with("nas-user")
        self.assertEqual(self.handler.ds.dsm_id, "nas-user")
        self.assertEqual(self.handler.cur_mode, "input_pw")
        update.message.reply_text.assert_called_once_with("enter password")

    def test_password_is_stored_deleted_and_login_retried(self):
        self.handler.cur_mode = "input_pw"
        self.handler.StartDsmLogin = Mock()
        update = make_update(text="super-secret")
        self.handler.current_mode_handle(update, None)
        self.handler.cfg.SetDsmPW.assert_called_once_with("super-secret")
        update.message.delete.assert_called_once_with()
        update.message.reply_text.assert_called_once_with("password deleted")
        self.handler.StartDsmLogin.assert_called_once_with()
        self.assertEqual(self.handler.cur_mode, "")

    def test_otp_is_deleted_and_login_retried(self):
        self.handler.cur_mode = "input_otp"
        self.handler.StartDsmLogin = Mock()
        update = make_update(text="123456")
        self.handler.current_mode_handle(update, None)
        self.assertEqual(self.handler.ds.dsm_otp, "123456")
        self.assertEqual(self.handler.otp_code, "123456")
        self.assertTrue(self.handler.otp_input)
        update.message.delete.assert_called_once_with()
        update.message.reply_text.assert_called_once_with("otp deleted")
        self.handler.StartDsmLogin.assert_called_once_with()

    def test_invalid_user_cannot_advance_interactive_login(self):
        self.handler.cur_mode = "input_pw"
        update = make_update(user_id=99, text="attacker-secret")
        self.handler.msg_handler(update, None)
        self.handler.cfg.SetDsmPW.assert_not_called()
        update.message.delete.assert_not_called()

    def test_torrent_uses_generated_private_path_and_cleans_it(self):
        observed = {}

        def consume(path):
            observed["path"] = path
            observed["exists_during_call"] = os.path.exists(path)
            return True

        telegram_file = Mock()
        telegram_file.download.side_effect = lambda custom_path, timeout: open(custom_path, "wb").close()
        document = Mock(file_name="../../escape.torrent", mime_type="application/x-bittorrent")
        document.get_file.return_value = telegram_file
        update = make_update()
        update.message.document = document
        self.handler.ds.CreateTaskForFileToWatchDir.side_effect = consume

        self.handler.file_handler(update, None)

        path = observed["path"]
        self.assertTrue(observed["exists_during_call"])
        self.assertEqual(os.path.basename(path), "upload.torrent")
        self.assertNotIn("escape", path)
        self.assertFalse(os.path.exists(path))
        document.get_file.assert_called_once_with(timeout=5)
        telegram_file.download.assert_called_once_with(custom_path=path, timeout=5)
        self.handler.BotUpdater.bot.sendMessage.assert_called_once_with(
            7, "torrent accepted: ../../escape.torrent"
        )

    def test_non_torrent_is_rejected_without_download(self):
        document = Mock(file_name="notes.txt", mime_type="text/plain")
        update = make_update()
        update.message.document = document
        self.handler.file_handler(update, None)
        document.get_file.assert_not_called()
        self.handler.ds.CreateTaskForFileToWatchDir.assert_not_called()
        self.handler.BotUpdater.bot.sendMessage.assert_called_once_with(7, "not torrent: notes.txt")

    def test_error_callback_logs_update_and_exception(self):
        context = types.SimpleNamespace(error=RuntimeError("boom"))
        with patch.object(bothandler.log, "error") as log_error:
            self.handler.error("update-object", context)
        self.assertEqual(log_error.call_count, 2)
        self.assertEqual(log_error.call_args_list[0].args[0], 'Update "%s" caused error "%s"')


if __name__ == "__main__":
    unittest.main()
