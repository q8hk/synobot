import pathlib
import sys
import tempfile
import unittest

import requests


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from synobot.synology import (  # noqa: E402
    SynologyApiError,
    SynologyAuthenticationError,
    SynologyClient,
    SynologySessionExpiredError,
    SynologyTimeoutError,
    Task,
)


class FakeCookies:
    def __init__(self):
        self.cleared = False

    def clear(self):
        self.cleared = True


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("http error")

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.cookies = FakeCookies()
        self.closed = False

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return FakeResponse(response)

    def close(self):
        self.closed = True


def client(responses, **kwargs):
    session = FakeSession(responses)
    instance = SynologyClient(
        "https://nas:5001/", "synobot", "secret", session=session, timeout=9, **kwargs
    )
    return instance, session


class ModelTests(unittest.TestCase):
    def test_task_defensively_parses_transfer_values(self):
        task = Task.from_mapping(
            {
                "id": "dbid_1",
                "title": "Ubuntu",
                "size": "50",
                "status": "downloading",
                "additional": {"transfer": {"size_downloaded": "12", "speed_download": None}},
            }
        )
        self.assertEqual(task.task_id, "dbid_1")
        self.assertEqual(task.size_bytes, 50)
        self.assertEqual(task.transfer.downloaded_bytes, 12)
        self.assertEqual(task.transfer.download_speed, 0)

    def test_task_requires_an_id(self):
        with self.assertRaises(ValueError):
            Task.from_mapping({"title": "bad"})


class ClientTests(unittest.TestCase):
    def test_login_uses_post_configuration_and_fresh_otp(self):
        codes = iter(("123456", "654321"))
        api, session = client([{"success": True}, {"success": True}], otp_provider=lambda: next(codes))
        api.login()
        api._authenticated = False
        api.login()
        first = session.calls[0][1]
        second = session.calls[1][1]
        self.assertEqual(first["data"]["otp_code"], "123456")
        self.assertEqual(second["data"]["otp_code"], "654321")
        self.assertEqual(first["timeout"], 9)
        self.assertTrue(first["verify"])
        self.assertNotIn("secret", session.calls[0][0])

    def test_login_maps_authentication_error(self):
        api, _ = client([{"success": False, "error": {"code": 400}}])
        with self.assertRaises(SynologyAuthenticationError) as caught:
            api.login()
        self.assertEqual(caught.exception.code, 400)

    def test_list_tasks_logs_in_and_parses_details(self):
        api, session = client(
            [
                {"success": True},
                {
                    "success": True,
                    "data": {
                        "tasks": [
                            {
                                "id": "one",
                                "title": "A",
                                "size": 100,
                                "status": "downloading",
                                "additional": {"transfer": {"speed_download": 44}},
                            }
                        ]
                    },
                },
            ]
        )
        tasks = api.list_tasks(details=True)
        self.assertEqual(tasks[0].transfer.download_speed, 44)
        self.assertEqual(session.calls[1][1]["data"]["additional"], "detail,file,transfer")

    def test_safe_request_reauthenticates_once_after_expiration(self):
        api, session = client(
            [
                {"success": True},
                {"success": False, "error": {"code": 106}},
                {"success": True},
                {"success": True, "data": {"tasks": []}},
            ]
        )
        self.assertEqual(api.list_tasks(), [])
        self.assertEqual([call[1]["data"]["method"] for call in session.calls], ["login", "list", "login", "list"])

    def test_create_is_not_retried_after_session_expiration(self):
        api, session = client(
            [{"success": True}, {"success": False, "error": {"code": 106}}]
        )
        with self.assertRaises(SynologySessionExpiredError):
            api.create_url("magnet:?xt=urn:btih:abc")
        self.assertEqual(len(session.calls), 2)

    def test_mutations_use_post_and_expected_parameters(self):
        api, session = client([{"success": True}] * 5)
        api.login()
        api.pause(["one", "two"])
        api.resume("one")
        api.delete("one", force_complete=True)
        methods = [call[1]["data"]["method"] for call in session.calls]
        self.assertEqual(methods, ["login", "pause", "resume", "delete"])
        self.assertEqual(session.calls[1][1]["data"]["id"], "one,two")
        self.assertTrue(session.calls[3][1]["data"]["force_complete"])

    def test_create_file_closes_file_and_does_not_delete_it(self):
        api, session = client([{"success": True}, {"success": True}])
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "safe.torrent"
            path.write_bytes(b"torrent")
            api.create_file(path, destination="downloads")
            uploaded = session.calls[1][1]["files"]["file"]
            self.assertTrue(uploaded.closed)
            self.assertTrue(path.exists())
            self.assertEqual(session.calls[1][1]["data"]["destination"], "downloads")

    def test_statistics_tolerates_invalid_numeric_values(self):
        api, _ = client(
            [{"success": True}, {"success": True, "data": {"speed_download": "100", "speed_upload": None}}]
        )
        stats = api.statistics()
        self.assertEqual(stats.download_speed, 100)
        self.assertEqual(stats.upload_speed, 0)

    def test_malformed_payload_raises_typed_error(self):
        api, _ = client([{"success": True}, {"success": True, "data": {"tasks": "bad"}}])
        with self.assertRaises(SynologyApiError):
            api.list_tasks()

    def test_legacy_session_expiration_code_is_reauthenticated(self):
        api, session = client([
            {"success": True},
            {"success": False, "error": {"code": 105}},
            {"success": True},
            {"success": True, "data": {"tasks": []}},
        ])
        self.assertEqual(api.list_tasks(), [])
        self.assertEqual(len(session.calls), 4)

    def test_timeout_is_wrapped(self):
        api, _ = client([requests.Timeout("slow")])
        with self.assertRaises(SynologyTimeoutError):
            api.login()

    def test_logout_clears_local_session_even_when_dsm_fails(self):
        api, session = client([{"success": True}, {"success": False, "error": {"code": 500}}])
        api.login()
        with self.assertRaises(SynologyApiError):
            api.logout()
        self.assertFalse(api.authenticated)
        self.assertTrue(session.cookies.cleared)


if __name__ == "__main__":
    unittest.main()
