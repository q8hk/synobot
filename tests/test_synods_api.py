"""Characterization tests for the legacy Synology Download Station adapter.

The production module imports Telegram and requests at module import time.  Phase 2
deliberately keeps the old dependency set unchanged, so this suite installs small
module doubles before loading ``synods.py``.
"""
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "dsm"


class ConnectionErrorDouble(Exception):
    pass


class TimeoutDouble(Exception):
    pass


def response(payload, status=200):
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return types.SimpleNamespace(status_code=status, content=body)


def load_synods():
    requests = types.ModuleType("requests")
    requests.get = Mock()
    requests.post = Mock()
    requests.ConnectionError = ConnectionErrorDouble
    requests.exceptions = types.SimpleNamespace(Timeout=TimeoutDouble)

    telegram = types.ModuleType("telegram")
    telegram.ParseMode = types.SimpleNamespace(MARKDOWN="markdown", HTML="html")
    urllib3 = types.ModuleType("urllib3")
    urllib3.exceptions = types.SimpleNamespace(InsecureRequestWarning=Warning)
    urllib3.disable_warnings = Mock()

    task_manager = Mock()
    taskmgr = types.ModuleType("taskmgr")
    taskmgr.TaskMgr = Mock(return_value=types.SimpleNamespace(instance=lambda: task_manager))

    config = Mock()
    config.GetDSDownloadUrl.return_value = "https://nas:5001"
    config.IsUseCert.return_value = True
    config.IsTaskAutoDel.return_value = False
    bot_config = types.ModuleType("BotConfig")
    bot_config.BotConfig = Mock(return_value=types.SimpleNamespace(instance=lambda: config))

    lang = Mock()
    lang.GetBotHandlerLang.return_value = "%s %s"
    lang.GetSynoTaskErrorLang.side_effect = lambda code: "error-" + code
    lang.GetSynoAuthErrorLang.side_effect = lambda code: "auth-" + code
    language = types.ModuleType("synobotLang")
    language.synobotLang = Mock(return_value=types.SimpleNamespace(instance=lambda: lang))

    bothandler = types.ModuleType("bothandler")
    handler = types.SimpleNamespace(bot=Mock(), StartDsmLogin=Mock())
    bothandler.BotHandler = Mock(return_value=types.SimpleNamespace(instance=lambda: handler))
    common = types.ModuleType("CommonUtil")
    common.hbytes = lambda value: str(value)
    otp = types.ModuleType("OtpHandler")
    single = types.ModuleType("single")
    single.SingletonInstane = object
    logs = types.ModuleType("LogManager")
    logs.log = Mock()

    doubles = {
        "requests": requests, "telegram": telegram, "urllib3": urllib3,
        "taskmgr": taskmgr, "BotConfig": bot_config, "synobotLang": language,
        "bothandler": bothandler, "CommonUtil": common, "OtpHandler": otp,
        "single": single, "LogManager": logs,
    }
    old = {name: sys.modules.get(name) for name in doubles}
    sys.modules.update(doubles)
    try:
        spec = importlib.util.spec_from_file_location("synods_characterized", ROOT / "synods.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        for name, value in old.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value
    return module, requests, config, lang, task_manager, bothandler


class SynologyApiCharacterizationTests(unittest.TestCase):
    def setUp(self):
        self.mod, self.requests, self.cfg, self.lang, self.manager, self.bothandler = load_synods()
        self.ds = self.mod.SynoDownloadStation.__new__(self.mod.SynoDownloadStation)
        self.ds.cfg = self.cfg
        self.ds.lang = self.lang
        self.ds.theTaskMgr = self.manager
        self.ds.auth_cookie = {"id": "session"}
        self.ds.dsm_login_flag = False
        self.ds.SendNotifyMessage = Mock()

    def fixture(self, name):
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    def test_login_success_builds_expected_request(self):
        expected = response({"success": True})
        self.requests.get.return_value = expected
        ok, actual = self.ds.DsmLogin("alice", "secret", "123456")
        self.assertTrue(ok)
        self.assertIs(actual, expected)
        _, kwargs = self.requests.get.call_args
        self.assertEqual(kwargs["params"]["method"], "login")
        self.assertEqual(kwargs["params"]["otp_code"], "123456")
        self.assertEqual(kwargs["timeout"], 30)
        self.assertTrue(kwargs["verify"])

    def test_login_connection_and_timeout_have_distinct_results(self):
        self.requests.get.side_effect = ConnectionErrorDouble()
        self.assertEqual(self.ds.DsmLogin("a", "b"), (False, "Connection error"))
        self.requests.get.side_effect = TimeoutDouble()
        self.assertEqual(self.ds.DsmLogin("a", "b"), (False, "Connection timeout"))

    def test_task_list_requires_session(self):
        self.ds.auth_cookie = None
        self.assertFalse(self.ds.GetTaskList())
        self.requests.get.assert_not_called()

    def test_task_list_records_nonzero_tasks_and_removal_set(self):
        payload = self.fixture("task_list_success.json")
        self.requests.get.return_value = response(payload)
        self.assertTrue(self.ds.GetTaskList())
        self.manager.InsertOrUpdateTask.assert_called_once_with(
            "dbid_1", "alpha.iso", 1024, "tester", "downloading"
        )
        self.manager.CheckRemoveTest.assert_called_once_with(["dbid_1", "dbid_2"])

    def test_task_api_failure_clears_session_and_starts_login(self):
        self.requests.get.return_value = response(self.fixture("api_session_error.json"))
        self.assertFalse(self.ds.GetTaskList())
        self.assertIsNone(self.ds.auth_cookie)
        handler = self.bothandler.BotHandler.return_value.instance()
        handler.StartDsmLogin.assert_called_once_with(False)

    def test_non_200_and_malformed_json_return_or_raise_as_legacy_behavior(self):
        self.requests.get.return_value = response({}, status=503)
        self.assertFalse(self.ds.GetTaskList())
        self.requests.get.return_value = response(b"not-json")
        with self.assertRaises(json.JSONDecodeError):
            self.ds.GetTaskList()

    def test_task_details_emit_every_mixed_task(self):
        self.requests.get.return_value = response(self.fixture("task_details_mixed.json"))
        self.ds.SendTaskList = Mock()
        self.assertTrue(self.ds.GetTaskDetail())
        self.assertEqual(self.ds.SendTaskList.call_count, 3)
        self.ds.SendTaskList.assert_any_call("zero", 0, "waiting", "metadata pending", 0, 0, 0, 0)
        self.ds.SendTaskList.assert_any_call("bare", 100, "paused", "no additional", 0, 0, 0, 0)
        self.ds.SendTaskList.assert_any_call("full", 1000, "downloading", "complete.iso", 400, 10, 20, 2)

    def test_task_details_api_failure_clears_session(self):
        self.requests.get.return_value = response(self.fixture("api_session_error.json"))
        self.assertFalse(self.ds.GetTaskDetail())
        self.assertIsNone(self.ds.auth_cookie)

    def test_statistics_emit_speeds(self):
        self.requests.get.return_value = response({
            "success": True, "data": {"speed_download": 1234, "speed_upload": 56}
        })
        self.ds.SendStatistic = Mock()
        self.assertTrue(self.ds.GetStatistic())
        self.ds.SendStatistic.assert_called_once_with(1234, 56)

    def test_statistics_without_data_is_still_successful(self):
        self.requests.get.return_value = response({"success": True})
        self.ds.SendStatistic = Mock()
        self.assertTrue(self.ds.GetStatistic())
        self.ds.SendStatistic.assert_not_called()

    def test_url_create_and_delete_use_post(self):
        self.requests.post.return_value = response({"success": True})
        self.assertTrue(self.ds.CreateTaskForUrl("magnet:?xt=urn:btih:abc"))
        create_call = self.requests.post.call_args
        self.assertEqual(create_call.kwargs["data"]["method"], "create")
        self.assertEqual(create_call.kwargs["data"]["uri"], "magnet:?xt=urn:btih:abc")
        self.assertTrue(self.ds.DeleteTask("dbid_1"))
        delete_call = self.requests.post.call_args
        self.assertEqual(delete_call.kwargs["data"], {
            "api": "SYNO.DownloadStation.Task", "version": "3",
            "method": "delete", "id": "dbid_1",
        })
        self.requests.get.assert_not_called()

    def test_create_url_connection_failure_returns_false(self):
        self.requests.post.side_effect = ConnectionErrorDouble()
        self.assertFalse(self.ds.CreateTaskForUrl("https://example.invalid/file"))

    def test_file_submission_deletes_source_only_after_api_success(self):
        self.requests.post.return_value = response({"success": True})
        with tempfile.TemporaryDirectory() as directory:
            torrent = Path(directory) / "sample.torrent"
            torrent.write_bytes(b"torrent")
            self.assertTrue(self.ds.CreateTaskForFile(str(torrent)))
            self.assertFalse(torrent.exists())
            uploaded = self.requests.post.call_args.kwargs["files"]["file"]
            self.assertTrue(uploaded.closed)

    def test_file_submission_preserves_source_after_api_failure(self):
        self.requests.post.return_value = response({"success": False, "error": {"code": 400}})
        with tempfile.TemporaryDirectory() as directory:
            torrent = Path(directory) / "sample.torrent"
            torrent.write_bytes(b"torrent")
            self.assertFalse(self.ds.CreateTaskForFile(str(torrent)))
            self.assertTrue(torrent.exists())
            uploaded = self.requests.post.call_args.kwargs["files"]["file"]
            self.assertTrue(uploaded.closed)

    def test_unknown_or_malformed_api_responses_fail_closed(self):
        self.assertFalse(self.ds.ChkAPIResponse({"unexpected": True}, "test"))
        self.assertFalse(self.ds.ChkTaskResponse(None, "test"))
        self.assertFalse(self.ds.ChkTaskResponse(
            {"success": False, "error": {"code": 9999}}, "test", msg_silent=True
        ))

    def test_auto_delete_selects_only_terminal_tasks(self):
        self.ds.DeleteTask = Mock(return_value=True)
        self.ds.TaskAutoDelete({"data": {"tasks": [
            {"id": "one", "title": "done", "status": "finished"},
            {"id": "two", "title": "seed", "status": "seeding"},
            {"id": "three", "title": "host", "status": "filehosting_waiting"},
            {"id": "four", "title": "active", "status": "downloading"},
        ]}})
        self.ds.DeleteTask.assert_called_once_with("one,two,three")

    def test_auto_delete_is_noop_without_terminal_tasks(self):
        self.ds.DeleteTask = Mock()
        self.ds.TaskAutoDelete({"data": {"tasks": [
            {"id": "one", "title": "active", "status": "downloading"}
        ]}})
        self.ds.DeleteTask.assert_not_called()

    def test_task_list_invokes_auto_delete_when_configured(self):
        payload = self.fixture("task_list_success.json")
        self.requests.get.return_value = response(payload)
        self.cfg.IsTaskAutoDel.return_value = True
        self.ds.TaskAutoDelete = Mock()
        self.assertTrue(self.ds.GetTaskList())
        self.ds.TaskAutoDelete.assert_called_once_with(payload)

    def test_watch_directory_moves_torrent(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as watch_dir:
            torrent = Path(source_dir) / "sample.torrent"
            torrent.write_bytes(b"torrent")
            self.cfg.GetTorWatch.return_value = watch_dir
            self.assertTrue(self.ds.CreateTaskForFileToWatchDir(str(torrent)))
            self.assertFalse(torrent.exists())
            self.assertEqual((Path(watch_dir) / torrent.name).read_bytes(), b"torrent")

    def test_watch_directory_reports_missing_setting_and_move_failure(self):
        self.lang.GetBotHandlerLang.side_effect = None
        self.lang.GetBotHandlerLang.return_value = "watch error"
        self.cfg.GetTorWatch.return_value = ""
        self.assertFalse(self.ds.CreateTaskForFileToWatchDir("sample.torrent"))
        self.ds.SendNotifyMessage.assert_called_once_with("watch error")

        self.ds.SendNotifyMessage.reset_mock()
        self.cfg.GetTorWatch.return_value = "/directory/that/does/not/exist"
        self.assertFalse(self.ds.CreateTaskForFileToWatchDir("missing.torrent"))
        self.ds.SendNotifyMessage.assert_called_once_with("watch error")

    def test_send_notify_message_supports_plain_markdown_and_html(self):
        self.ds.SendNotifyMessage = self.mod.SynoDownloadStation.SendNotifyMessage.__get__(self.ds)
        self.cfg.GetNotifyList.return_value = [101, 202]
        handler = self.bothandler.BotHandler.return_value.instance()
        self.ds.SendNotifyMessage("plain")
        self.ds.SendNotifyMessage("mark", ParseMode="mark")
        self.ds.SendNotifyMessage("html", ParseMode="html")
        for chat_id in (101, 202):
            handler.bot.sendMessage.assert_any_call(chat_id, "plain")
            handler.bot.sendMessage.assert_any_call(chat_id, "mark", parse_mode="markdown")
            handler.bot.sendMessage.assert_any_call(chat_id, "html", parse_mode="html")

    def test_task_notification_callback_formats_and_sends(self):
        self.lang.GetBotHandlerLang.side_effect = None
        self.lang.GetBotHandlerLang.return_value = "%s|%s|%s|%s"
        self.ds.StatusTranslate = Mock(return_value="translated")
        self.ds.TaskNotiCallback("id", "title", 2048, "owner", "finished")
        self.ds.SendNotifyMessage.assert_called_once_with("translated|title|2048|owner")

    def test_task_list_and_statistics_format_and_send(self):
        self.lang.GetBotHandlerLang.side_effect = None
        self.lang.GetBotHandlerLang.return_value = "%s|%s|%s|%s|%s|%s|%s|%s"
        self.ds.StatusTranslate = Mock(return_value="active")
        self.ds.SendTaskList("id", 100, "downloading", "title", 50, 5, 10, 1)
        self.ds.SendNotifyMessage.assert_called_once_with("id|title|100|active|50|5|10|1")

        self.ds.SendNotifyMessage.reset_mock()
        self.lang.GetBotHandlerLang.return_value = "%s|%s"
        self.ds.SendStatistic(1000, 20)
        self.ds.SendNotifyMessage.assert_called_once_with("1000|20")

    def test_notification_callbacks_are_silent_without_bot(self):
        handler = self.bothandler.BotHandler.return_value.instance()
        handler.bot = None
        self.ds.TaskNotiCallback("id", "title", 1, "owner", "finished")
        self.ds.SendTaskList("id", 1, "finished", "title", 1, 0, 0, 0)
        self.ds.SendStatistic(1, 0)
        self.ds.SendNotifyMessage.assert_not_called()

    def test_status_and_error_translation_delegates_with_fallback(self):
        self.lang.GetSynoDsLang.return_value = "Downloading"
        self.assertEqual(self.ds.StatusTranslate("downloading"), "Downloading")
        self.lang.GetSynoDsLang.side_effect = KeyError("unknown")
        self.assertEqual(self.ds.StatusTranslate("brand_new_state"), "brand_new_state")
        self.assertEqual(self.ds.GetErrorAuthCode(400), "auth-400")
        self.assertEqual(self.ds.GetErrorTaskCode(401), "error-401")

    def test_remaining_get_request_transport_and_http_failures(self):
        for method_name in ("GetTaskList", "GetTaskDetail", "GetStatistic"):
            with self.subTest(method=method_name, failure="connection"):
                self.requests.get.reset_mock()
                self.requests.get.side_effect = ConnectionErrorDouble()
                self.assertFalse(getattr(self.ds, method_name)())
            with self.subTest(method=method_name, failure="http"):
                self.requests.get.side_effect = None
                self.requests.get.return_value = response({}, status=500)
                self.assertFalse(getattr(self.ds, method_name)())

    def test_remaining_post_request_transport_and_http_failures(self):
        operations = [
            lambda: self.ds.CreateTaskForUrl("magnet:?xt=urn:btih:x"),
            lambda: self.ds.DeleteTask("id"),
        ]
        for operation in operations:
            with self.subTest(operation=operation, failure="connection"):
                self.requests.post.side_effect = ConnectionErrorDouble()
                self.assertFalse(operation())
            with self.subTest(operation=operation, failure="http"):
                self.requests.post.side_effect = None
                self.requests.post.return_value = response({}, status=500)
                self.assertFalse(operation())

    def test_file_create_transport_and_http_failures_preserve_source(self):
        for failure in (ConnectionErrorDouble(), response({}, status=500)):
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as directory:
                torrent = Path(directory) / "sample.torrent"
                torrent.write_bytes(b"torrent")
                if isinstance(failure, Exception):
                    self.requests.post.side_effect = failure
                else:
                    self.requests.post.side_effect = None
                    self.requests.post.return_value = failure
                self.assertFalse(self.ds.CreateTaskForFile(str(torrent)))
                self.assertTrue(torrent.exists())


if __name__ == "__main__":
    unittest.main()
