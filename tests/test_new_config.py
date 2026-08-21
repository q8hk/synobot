from dataclasses import FrozenInstanceError
import warnings

import pytest

from synobot.config import ConfigurationError, Settings


BASE = {
    "TELEGRAM_BOT_TOKEN": "token",
    "TELEGRAM_ADMIN_USER_IDS": "123, 456",
    "TELEGRAM_NOTIFY_USER_IDS": "123",
    "DSM_BASE_URL": "https://nas.local:5001/",
    "DSM_USERNAME": "bot",
}


def test_minimal_config_is_immutable():
    settings = Settings.from_env(BASE)
    assert settings.telegram_admin_user_ids == (123, 456)
    assert settings.telegram_notify_user_ids == (123,)
    assert settings.dsm_base_url == "https://nas.local:5001"
    assert settings.dsm_destination_presets == ("TVShows", "Movies", "Download")
    with pytest.raises(FrozenInstanceError):
        settings.dsm_username = "changed"


def test_secret_files_take_precedence(tmp_path):
    secret = tmp_path / "token"
    secret.write_text("from-file\n")
    env = dict(BASE, TELEGRAM_BOT_TOKEN="inline", TELEGRAM_BOT_TOKEN_FILE=str(secret))
    assert Settings.from_env(env).telegram_bot_token == "from-file"


@pytest.mark.parametrize("name", ["TELEGRAM_BOT_TOKEN", "TELEGRAM_ADMIN_USER_IDS", "TELEGRAM_NOTIFY_USER_IDS", "DSM_BASE_URL", "DSM_USERNAME"])
def test_required_values(name):
    env = dict(BASE)
    del env[name]
    with pytest.raises(ConfigurationError, match="required"):
        Settings.from_env(env)


def test_rejects_code_and_bad_boolean():
    with pytest.raises(ConfigurationError):
        Settings.from_env(dict(BASE, TELEGRAM_ADMIN_USER_IDS="__import__('os')"))
    with pytest.raises(ConfigurationError):
        Settings.from_env(dict(BASE, DSM_TLS_VERIFY="maybe"))


def test_legacy_aliases_and_url_port():
    env = {"TG_BOT_TOKEN": "x", "TG_VALID_USER": "1", "TG_NOTY_ID": "-2",
           "DSM_ID": "bot", "DSM_URL": "https://nas.local", "DS_PORT": "5001",
           "DSM_CERT": "0", "DSM_AUTO_DEL": "1", "TG_LANG": "ko_kr"}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        settings = Settings.from_env(env)
    assert settings.dsm_base_url == "https://nas.local:5001"
    assert settings.dsm_tls_verify is False
    assert settings.dsm_auto_delete is True
    assert settings.telegram_notify_user_ids == (-2,)
    assert "TG_BOT_TOKEN" in settings.deprecated_settings
    assert caught


def test_new_names_win_over_legacy():
    env = dict(BASE, TG_BOT_TOKEN="old", TG_VALID_USER="999", DSM_ID="old")
    settings = Settings.from_env(env)
    assert settings.telegram_bot_token == "token"
    assert settings.telegram_admin_user_ids == (123, 456)
    assert settings.dsm_username == "bot"
    assert not settings.deprecated_settings


def test_paths_intervals_and_optional_secrets():
    env = dict(BASE, DATABASE_PATH="state/test.db", DSM_TORRENT_WATCH_PATH="watch",
               DSM_REQUEST_TIMEOUT_SECONDS="2.5", DSM_POLL_INTERVAL_SECONDS="3",
               DSM_PASSWORD="pw", DSM_TOTP_SECRET="otp", TZ="Asia/Kuwait")
    settings = Settings.from_env(env)
    assert str(settings.database_path) == "state/test.db"
    assert settings.dsm_request_timeout_seconds == 2.5
    assert settings.dsm_password == "pw"
    assert settings.timezone == "Asia/Kuwait"


def test_destination_presets_are_cleaned_deduplicated_and_validated():
    settings = Settings.from_env(dict(BASE, DSM_DESTINATION_PRESETS=" /TVShows/, Movies,TVShows "))
    assert settings.dsm_destination_presets == ("TVShows", "Movies")
    with pytest.raises(ConfigurationError, match="DESTINATION_PRESETS"):
        Settings.from_env(dict(BASE, DSM_DESTINATION_PRESETS=" , "))
