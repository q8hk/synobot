"""Static contracts for the production container definition."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
COMPOSE = (ROOT / "compose.yaml").read_text(encoding="utf-8")


def test_runtime_uses_modern_python_and_installed_package():
    assert "FROM python:3.12-slim-bookworm AS runtime" in DOCKERFILE
    assert 'CMD ["python", "-m", "synobot"]' in DOCKERFILE
    assert "COPY --from=builder /wheels /wheels" in DOCKERFILE
    assert "main.py" not in DOCKERFILE


def test_runtime_is_unprivileged_and_persistent():
    assert "USER synobot:synobot" in DOCKERFILE
    assert 'VOLUME ["/data"]' in DOCKERFILE
    assert "DATABASE_PATH=/data/synobot.db" in DOCKERFILE
    assert "STOPSIGNAL SIGTERM" in DOCKERFILE


def test_image_defines_application_healthcheck():
    assert 'CMD ["python", "-m", "synobot.healthcheck"]' in DOCKERFILE
    assert "--start-period=30s" in DOCKERFILE


def test_image_contains_no_embedded_runtime_credentials():
    forbidden = ("TG_BOT_TOKEN", "DSM_PW=", "12345678", "your_dsm")
    for value in forbidden:
        assert value not in DOCKERFILE


def test_compose_hardens_runtime_and_uses_secret_files():
    assert "read_only: true" in COMPOSE
    assert "no-new-privileges:true" in COMPOSE
    assert "cap_drop:" in COMPOSE and "- ALL" in COMPOSE
    assert "TELEGRAM_BOT_TOKEN_FILE: /run/secrets/telegram_bot_token" in COMPOSE
    assert "DSM_PASSWORD_FILE: /run/secrets/dsm_password" in COMPOSE
    assert "synobot-data:/data" in COMPOSE
    assert "/tmp/uploads:rw,noexec,nosuid,nodev" in COMPOSE


def test_compose_does_not_supply_fake_identifiers_or_credentials():
    assert "12345678" not in COMPOSE
    assert "your_dsm" not in COMPOSE
    assert "TELEGRAM_BOT_TOKEN:" not in COMPOSE
    assert "DSM_PASSWORD:" not in COMPOSE
