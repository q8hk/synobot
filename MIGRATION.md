# Migrating to Synobot 1.0

Synobot 1.0 replaces the legacy global runtime with validated configuration, an asynchronous Telegram adapter, a typed DSM client, and SQLite persistence. Perform the migration with a pinned image and a rollback copy.

## Before upgrading

1. Record the currently deployed image tag or digest.
2. Stop the old container.
3. Back up its environment/Compose definition, `taskdata.json`, and persistent data.
4. Create a new writable `/data` directory.
5. Convert credentials to read-only secret files.
6. Replace legacy settings using the table below.

Never test a migration by overwriting the only copy of existing state.

## Configuration mapping

| Legacy | Synobot 1.0 |
|---|---|
| `TG_BOT_TOKEN` | `TELEGRAM_BOT_TOKEN` or `TELEGRAM_BOT_TOKEN_FILE` |
| `TG_VALID_USER` | `TELEGRAM_ADMIN_USER_IDS` |
| `TG_NOTY_ID` | `TELEGRAM_NOTIFY_USER_IDS` |
| `TG_DSM_PW_ID` | `TELEGRAM_DSM_PASSWORD_USER_ID` |
| `DSM_ID` | `DSM_USERNAME` |
| `DSM_PW` | `DSM_PASSWORD` or `DSM_PASSWORD_FILE` |
| `DSM_OTP_SECRET` | `DSM_TOTP_SECRET` or `DSM_TOTP_SECRET_FILE` |
| `DSM_URL` + `DS_PORT` | `DSM_BASE_URL` including the port |
| `DSM_CERT` | `DSM_TLS_VERIFY` (`1` meant verify; `0` meant disable) |
| `DSM_WATCH` | `DSM_TORRENT_WATCH_PATH` |
| `DSM_AUTO_DEL` | `DSM_AUTO_DELETE` |
| `TG_LANG` | `TELEGRAM_LANGUAGE` |

Compatibility aliases are transitional and emit deprecation warnings. `SYNO_LANG` and `DOCKER_LOG` are legacy-runtime settings and are not part of the modern configuration model.

## Legacy task import

The repository migration accepts a valid legacy `taskdata.json`, imports recognized task records into SQLite, and records a migration marker so the same source is not imported repeatedly.

1. Preserve the original JSON file outside the container.
2. Make a copy available to the application at its documented legacy path during first startup.
3. Mount `/data` persistently and set `DATABASE_PATH=/data/synobot.db`.
4. Start Synobot and inspect logs for configuration or migration errors.
5. Confirm `/health`, `/tasks`, and expected notifications.
6. Retain the JSON backup until the release has run successfully through a normal task lifecycle.

Malformed or inaccessible JSON must be corrected or omitted; do not edit the only backup.

## Verification checklist

- Container remains running after startup.
- Logs contain no secret values.
- `/health` reports DSM available.
- `/tasks` matches Download Station.
- A low-risk test submission appears once in DSM.
- Restarting the container does not repeat already delivered events.
- The database exists on the persistent host volume.

## Updates within 1.x

1. Stop Synobot and back up `/data`.
2. Read `CHANGELOG.md` for migration notes.
3. Pull an exact new release tag.
4. Start it and complete the verification checklist.
5. Retain the previous image and backup until validation is complete.

## Rollback

1. Stop the failed/new container.
2. Preserve its logs and database for diagnosis.
3. Restore the previous Compose/environment definition.
4. Restore the database backup compatible with that version.
5. Start the exact previous image tag or digest.
6. Verify Telegram authorization and DSM connectivity.

Do not point an older release at a database already modified by a newer release unless that downgrade is explicitly documented as compatible. Rolling back to legacy 0.x requires its original `taskdata.json`; 0.x cannot use the 1.x SQLite database.
