# Deploying Synobot on Synology Container Manager

This guide targets a DS718+ and DSM Container Manager. Labels can vary slightly between DSM releases. Prefer a Compose project because it makes the deployment reproducible and rollback straightforward.

## 1. Prepare DSM

1. Install and start Download Station.
2. Create a dedicated local DSM user such as `synobot`.
3. Deny administrator-group membership and interactive administration privileges not required for the service.
4. Grant only the application permission needed to use Download Station and only the shared-folder access required by your Download Station configuration.
5. Test that account directly in DSM before configuring Synobot.

Synology permission behavior can differ with DSM and Download Station releases. Start with no access, add only what the API operation requires, and document the final grants.

## 2. Prepare Telegram

1. Open a direct conversation with the official [BotFather](https://t.me/BotFather).
2. Create a bot and copy its token into a password manager.
3. Send the bot a private message so Telegram will permit replies.
4. Determine the numeric Telegram user IDs for administrators and notification recipients.
5. Never use a visible Telegram username as an authorization value.

## 3. Prepare storage

Create a project directory in a shared folder accessible to Container Manager, with these subdirectories:

```text
synobot/
  compose.yaml
  .env
  data/
  secrets/
  certificates/       # optional
```

Create these files without a trailing explanatory comment:

- `secrets/telegram_bot_token`
- `secrets/dsm_password`
- `secrets/dsm_totp_secret` only when DSM 2FA is enabled for the service account

Restrict the project and secret directories to the NAS administrators and the container runtime. Do not place secrets in `.env` when file mounts are available.

## 4. Configure Compose

Use the repository's `compose.yaml` (or the smaller example in `README.md`). Replace the image with an exact published release tag. Copy `.env.example` to `.env`, set your numeric IDs, DSM address, and service-account name, then keep `/data` persistent and secrets read-only.

For DSM's usual HTTPS management endpoint, a base URL resembles:

```dotenv
DSM_BASE_URL=https://nas.example.internal:5001
```

Do not append API paths, embed credentials, or specify query parameters.

## 5. Configure trusted TLS

The best options are:

1. a DSM certificate issued by a public CA and matching the hostname used by Synobot; or
2. an internal CA certificate trusted inside the container, with a DSM server certificate matching the configured hostname.

Mount private CA material read-only. The exact way a CA is added to the trust store depends on the published container image. Verify the release documentation before relying on a custom CA mount. Merely mounting a file does not automatically establish trust.

Keep `DSM_TLS_VERIFY=true`. If you temporarily set it to `false` to isolate a certificate problem, do not treat the deployment as production-ready and restore verification after correcting the certificate chain or hostname.

## 6. Create the Container Manager project

1. Open **Container Manager → Project**.
2. Create a project from the prepared directory/Compose file.
3. Review every environment variable and volume mapping.
4. Confirm `/data` is persistent and `/run/secrets` is read-only.
5. Build/start the project.
6. Inspect the container logs without copying them into a public report.

The application must fail closed when required configuration is missing. Correct configuration rather than weakening authorization or TLS to make startup succeed.

## 7. Acceptance test

1. Confirm the container remains running.
2. Send `/start`, `/health`, `/stats`, and `/tasks` from an authorized private chat.
3. Send `/start` from an unlisted account and confirm denial.
4. Submit a small, legal test magnet or `.torrent` and confirm it appears once in Download Station.
5. Restart the container and confirm state persists without duplicate notifications.
6. Temporarily stop Download Station, confirm degraded reporting, restore it, and confirm recovery.
7. Search logs for the literal token/password fragments; none should appear.

## 8. Back up, update, and restore

Before updating, stop the project and copy the complete `data` directory plus Compose and `.env` files to a protected backup. Secret files should be backed up only into an encrypted credential backup.

Change only the pinned image tag, pull/recreate the project, and repeat the acceptance test. Roll back with the previous tag and matching database backup. Full instructions are in `MIGRATION.md`.

## Torrent watch compatibility

`DSM_TORRENT_WATCH_PATH` is retained for legacy configuration migration. The modern Telegram adapter submits `.torrent` files through the DSM API, so do not expose a NAS watch folder unless a release explicitly documents and requires that workflow.
