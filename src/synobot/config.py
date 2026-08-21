"""Typed, side-effect-free application configuration."""

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit
import warnings


class ConfigurationError(ValueError):
    """Raised when application configuration is missing or invalid."""


_LEGACY_ALIASES = {
    "TELEGRAM_BOT_TOKEN": ("TG_BOT_TOKEN",),
    "TELEGRAM_ADMIN_USER_IDS": ("TG_VALID_USER",),
    "TELEGRAM_NOTIFY_USER_IDS": ("TG_NOTY_ID",),
    "TELEGRAM_DSM_PASSWORD_USER_ID": ("TG_DSM_PW_ID",),
    "DSM_USERNAME": ("DSM_ID",),
    "DSM_PASSWORD": ("DSM_PW",),
    "DSM_TOTP_SECRET": ("DSM_OTP_SECRET",),
    "DSM_TLS_VERIFY": ("DSM_CERT",),
    "DSM_TORRENT_WATCH_PATH": ("DSM_WATCH",),
    "DSM_AUTO_DELETE": ("DSM_AUTO_DEL",),
    "TELEGRAM_LANGUAGE": ("TG_LANG",),
}


def _text(env: Mapping[str, str], name: str, legacy: Tuple[str, ...] = ()):
    if name in env:
        return str(env[name]).strip(), None
    for alias in legacy:
        if alias in env:
            return str(env[alias]).strip(), alias
    return None, None


def _required(value: Optional[str], name: str) -> str:
    if not value:
        raise ConfigurationError("%s is required and must not be empty" % name)
    return value


def _ids(value: Optional[str], name: str, *, allow_negative: bool = False) -> Tuple[int, ...]:
    value = _required(value, name)
    result = []
    for raw in value.split(","):
        item = raw.strip()
        numeric = item[1:] if allow_negative and item.startswith("-") else item
        if not item or not numeric.isdecimal():
            raise ConfigurationError("%s must be a comma-separated list of integer IDs" % name)
        number = int(item)
        if number == 0 or (number < 0 and not allow_negative):
            raise ConfigurationError("%s contains an invalid ID: %s" % (name, item))
        if number not in result:
            result.append(number)
    return tuple(result)


def _boolean(value: Optional[str], name: str, default: bool) -> bool:
    if value is None or value == "":
        return default
    normalized = value.lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off"):
        return False
    raise ConfigurationError("%s must be one of: true, false, 1, 0, yes, no, on, off" % name)


def _positive_number(value: Optional[str], name: str, default, cast):
    if value is None or value == "":
        return default
    try:
        parsed = cast(value)
    except (TypeError, ValueError):
        raise ConfigurationError("%s must be a number" % name)
    if parsed <= 0:
        raise ConfigurationError("%s must be greater than zero" % name)
    return parsed


def _secret(env: Mapping[str, str], name: str, legacy: Tuple[str, ...] = (), required=False):
    """Resolve NAME_FILE before NAME, without exposing secret values in errors."""
    file_name = name + "_FILE"
    if file_name in env:
        path_value = str(env[file_name]).strip()
        if not path_value:
            raise ConfigurationError("%s must point to a readable file" % file_name)
        try:
            value = Path(path_value).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as exc:
            raise ConfigurationError("could not read %s: %s" % (file_name, exc.__class__.__name__))
        if not value:
            raise ConfigurationError("%s points to an empty file" % file_name)
        return value, None
    value, used = _text(env, name, legacy)
    if required:
        value = _required(value, name + " or " + file_name)
    return value or None, used


def _base_url(value: str, name: str) -> str:
    try:
        parts = urlsplit(value)
        parts.port  # force validation
    except ValueError:
        raise ConfigurationError("%s must be a valid HTTP(S) URL" % name)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ConfigurationError("%s must be an absolute HTTP(S) URL" % name)
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ConfigurationError("%s must not contain credentials, a query, or a fragment" % name)
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_admin_user_ids: Tuple[int, ...]
    telegram_notify_user_ids: Tuple[int, ...]
    dsm_base_url: str
    dsm_username: str
    dsm_tls_verify: bool = True
    dsm_request_timeout_seconds: float = 20.0
    dsm_poll_interval_seconds: float = 10.0
    database_path: Path = Path("/data/synobot.db")
    torrent_watch_path: Optional[Path] = None
    dsm_auto_delete: bool = False
    telegram_language: str = "en"
    timezone: str = "UTC"
    dsm_password: Optional[str] = None
    dsm_totp_secret: Optional[str] = None
    telegram_dsm_password_user_id: Optional[int] = None
    dsm_destination_presets: Tuple[str, ...] = ("TVShows", "Movies", "Download")
    deprecated_settings: Tuple[str, ...] = ()

    @classmethod
    def from_env(cls, mapping: Optional[Mapping[str, str]] = None) -> "Settings":
        env = os.environ if mapping is None else mapping
        deprecated = []

        def get(name: str):
            value, used = _text(env, name, _LEGACY_ALIASES.get(name, ()))
            if used:
                deprecated.append(used)
            return value

        token, token_legacy = _secret(env, "TELEGRAM_BOT_TOKEN", ("TG_BOT_TOKEN",), required=True)
        if token_legacy:
            deprecated.append(token_legacy)
        password, password_legacy = _secret(env, "DSM_PASSWORD", ("DSM_PW",))
        if password_legacy:
            deprecated.append(password_legacy)
        totp, totp_legacy = _secret(env, "DSM_TOTP_SECRET", ("DSM_OTP_SECRET",))
        if totp_legacy:
            deprecated.append(totp_legacy)

        admins = _ids(get("TELEGRAM_ADMIN_USER_IDS"), "TELEGRAM_ADMIN_USER_IDS")
        notifiers = _ids(
            get("TELEGRAM_NOTIFY_USER_IDS"),
            "TELEGRAM_NOTIFY_USER_IDS",
            allow_negative=True,
        )

        password_user_raw = get("TELEGRAM_DSM_PASSWORD_USER_ID")
        password_user = None
        if password_user_raw:
            password_user = _ids(password_user_raw, "TELEGRAM_DSM_PASSWORD_USER_ID")[0]

        base_raw, _ = _text(env, "DSM_BASE_URL")
        if base_raw is None:
            old_url, _ = _text(env, "DSM_URL")
            if old_url is not None:
                deprecated.append("DSM_URL")
                port_raw, _ = _text(env, "DS_PORT")
                if port_raw:
                    deprecated.append("DS_PORT")
                    try:
                        port = int(port_raw)
                    except ValueError:
                        raise ConfigurationError("DS_PORT must be an integer between 1 and 65535")
                    if not 1 <= port <= 65535:
                        raise ConfigurationError("DS_PORT must be an integer between 1 and 65535")
                    try:
                        parsed = urlsplit(old_url)
                        existing_port = parsed.port
                    except ValueError:
                        raise ConfigurationError("DSM_URL must be a valid HTTP(S) URL")
                    if existing_port is None:
                        host = parsed.hostname or ""
                        if ":" in host:
                            host = "[" + host + "]"
                        old_url = urlunsplit((parsed.scheme, "%s:%d" % (host, port), parsed.path, "", ""))
                base_raw = old_url
        dsm_url = _base_url(_required(base_raw, "DSM_BASE_URL"), "DSM_BASE_URL")

        db_raw, _ = _text(env, "DATABASE_PATH")
        watch_raw = get("DSM_TORRENT_WATCH_PATH")
        language = get("TELEGRAM_LANGUAGE") or "en"
        timezone, _ = _text(env, "TZ")
        timezone = timezone or "UTC"
        presets_raw, _ = _text(env, "DSM_DESTINATION_PRESETS")
        presets = tuple(dict.fromkeys(
            item.strip().strip("/")
            for item in (presets_raw or "TVShows,Movies,Download").split(",")
            if item.strip().strip("/")
        ))
        if not presets or any(
            len(item) > 512 or any(ord(char) < 32 for char in item)
            for item in presets
        ):
            raise ConfigurationError("DSM_DESTINATION_PRESETS contains an invalid path")
        if not language or any(c.isspace() for c in language):
            raise ConfigurationError("TELEGRAM_LANGUAGE must be a non-empty language identifier")
        if any(c.isspace() for c in timezone):
            raise ConfigurationError("TZ must be a timezone name without whitespace")

        settings = cls(
            telegram_bot_token=token,
            telegram_admin_user_ids=admins,
            telegram_notify_user_ids=notifiers,
            dsm_base_url=dsm_url,
            dsm_username=_required(get("DSM_USERNAME"), "DSM_USERNAME"),
            dsm_tls_verify=_boolean(get("DSM_TLS_VERIFY"), "DSM_TLS_VERIFY", True),
            dsm_request_timeout_seconds=_positive_number(
                get("DSM_REQUEST_TIMEOUT_SECONDS"), "DSM_REQUEST_TIMEOUT_SECONDS", 20.0, float),
            dsm_poll_interval_seconds=_positive_number(
                get("DSM_POLL_INTERVAL_SECONDS"), "DSM_POLL_INTERVAL_SECONDS", 10.0, float),
            database_path=Path(db_raw or "/data/synobot.db"),
            torrent_watch_path=Path(watch_raw) if watch_raw else None,
            dsm_auto_delete=_boolean(get("DSM_AUTO_DELETE"), "DSM_AUTO_DELETE", False),
            telegram_language=language,
            timezone=timezone,
            dsm_password=password,
            dsm_totp_secret=totp,
            telegram_dsm_password_user_id=password_user,
            dsm_destination_presets=presets,
            deprecated_settings=tuple(dict.fromkeys(deprecated)),
        )
        for legacy in settings.deprecated_settings:
            warnings.warn(
                "%s is deprecated; use the corresponding Synobot 1.x setting" % legacy,
                DeprecationWarning,
                stacklevel=2,
            )
        return settings
