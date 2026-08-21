# Synobot

Synobot is a private Telegram interface for Synology Download Station. It can submit magnet, HTTP/HTTPS/FTP, YouTube, and `.torrent` tasks; list current tasks and transfer rates; notify selected Telegram recipients about durable task events; and recover its DSM session after expiration.

Synobot 1.x uses an asynchronous Telegram adapter, a typed Synology API client, a supervised task monitor, and a transactional SQLite repository. Blocking DSM and database work runs outside Telegram's event loop. Authorization is checked for every command and submitted item.

## Requirements

- A Synology NAS with Download Station installed and enabled
- Container Manager (or another Docker/Compose installation)
- A Telegram bot token from BotFather
- A dedicated DSM account allowed to use Download Station
- HTTPS with a trusted certificate or a custom CA certificate strongly recommended

The primary production deployment target is `linux/arm64` on Raspberry Pi. The bot
continues to connect to Download Station on the Synology NAS over the DSM API; it
does not need to run on the NAS itself.

## Commands

| Command or input | Required role | Action |
|---|---:|---|
| `/start` | Viewer | Show bot readiness |
| `/help` | Viewer | Show available commands |
| `/health` | Viewer | Check the bot and DSM connection |
| `/tasks` | Viewer | List tasks with pause, resume, and confirmed-delete controls |
| `/history [limit]` | Viewer | Show durable recent task transitions |
| `/stats` | Viewer | Show current download and upload rates |
| `/notifications on\|off\|clear` | Viewer | Enable, mute, or reset personal notifications |
| `/notifications quiet <start> <end> <timezone>` | Viewer | Set personal quiet hours, for example `22:00 07:00 Asia/Kuwait` |
| `/dslogin` | Administrator | Refresh the DSM login |
| `/add <URL>` | Operator | Submit an HTTP, HTTPS, FTP, or magnet URL |
| `/destination [folder\|clear]` | Operator | Choose a ranked DSM destination or set a folder manually |
| `/destinations` | Operator | Show more destinations derived from DSM history |
| `/language <en\|ar>` | Viewer | Select English or Arabic responses |
| Magnet or supported YouTube URL | Operator | Submit the URL |
| `.torrent` document | Operator | Submit a torrent file safely |

Unknown users and group chats are denied by default. The current 1.0 configuration grants configured users administrator access; finer-grained user-role configuration is planned for a later release.

Parameterized commands are conversational. If `/add`, `/destination`, `/language`,
or `/notifications` is sent without its required value, Synobot explains what is
missing and offers relevant buttons. A text message sent within five minutes is
treated as the missing argument to that command; users can also cancel the prompt.

## Quick start with Compose

1. Create a Telegram bot with [BotFather](https://t.me/BotFather) and retain its token securely.
2. Send the new bot a direct message. Determine your numeric Telegram user ID using a method you trust; this is a user ID, not a username.
3. Create a dedicated DSM account with access to Download Station only. Do not use a DSM administrator account.
4. Create local `data`, `secrets`, and optionally `certificates` directories.
5. Put the Telegram token and DSM password in separate files. Restrict their permissions to the account running Docker.
6. Copy `.env.example` to `.env` and replace all example values.
7. Create `compose.yaml`:

```yaml
services:
  synobot:
    image: ghcr.io/q8hk/synobot:1.1.0
    container_name: synobot
    restart: unless-stopped
    environment:
      TELEGRAM_BOT_TOKEN_FILE: /run/secrets/telegram_bot_token
      TELEGRAM_ADMIN_USER_IDS: ${TELEGRAM_ADMIN_USER_IDS}
      TELEGRAM_NOTIFY_USER_IDS: ${TELEGRAM_NOTIFY_USER_IDS}
      DSM_BASE_URL: ${DSM_BASE_URL}
      DSM_USERNAME: ${DSM_USERNAME}
      DSM_PASSWORD_FILE: /run/secrets/dsm_password
      DSM_TLS_VERIFY: "true"
      DSM_POLL_INTERVAL_SECONDS: "10"
      DSM_REQUEST_TIMEOUT_SECONDS: "20"
      DATABASE_PATH: /data/synobot.db
      TELEGRAM_LANGUAGE: en
      TZ: Asia/Kuwait
    volumes:
      - ./data:/data
      - ./secrets:/run/secrets:ro
      # Mount a private CA only when your DSM certificate requires it.
      # - ./certificates:/certificates:ro
```

8. Pull and start the pinned release:

```shell
docker compose pull
docker compose up -d
docker compose logs --tail=100 synobot
```

Use an exact release tag in production. Confirm that the tag exists in the project's published images before deployment. See [the Synology deployment guide](docs/DEPLOY_SYNOLOGY.md) for Container Manager instructions.

## Configuration

Secret settings support a `_FILE` variant. When both are present, `_FILE` takes precedence.

| Setting | Required | Default | Description |
|---|---:|---:|---|
| `TELEGRAM_BOT_TOKEN_FILE` or `TELEGRAM_BOT_TOKEN` | Yes | — | Telegram token file or value |
| `TELEGRAM_ADMIN_USER_IDS` | Yes | — | Comma-separated positive Telegram user IDs |
| `TELEGRAM_NOTIFY_USER_IDS` | Yes | — | Comma-separated Telegram recipient IDs; negative group IDs are accepted for notifications |
| `DSM_BASE_URL` | Yes | — | Absolute DSM base URL, including port when non-default |
| `DSM_USERNAME` | Yes | — | Dedicated DSM service-account username |
| `DSM_PASSWORD_FILE` or `DSM_PASSWORD` | Runtime | — | DSM password; unattended startup requires one |
| `DSM_TOTP_SECRET_FILE` or `DSM_TOTP_SECRET` | No | — | Base32 TOTP secret for a DSM account using 2FA |
| `DSM_TLS_VERIFY` | No | `true` | Verify DSM's TLS certificate |
| `DSM_REQUEST_TIMEOUT_SECONDS` | No | `20` | Positive HTTP timeout in seconds |
| `DSM_POLL_INTERVAL_SECONDS` | No | `10` | Positive normal polling interval in seconds |
| `DSM_DESTINATION_PRESETS` | No | `TVShows,Movies,Download` | Comma-separated fallback destinations used by the Telegram chooser |
| `DATABASE_PATH` | No | `/data/synobot.db` | SQLite database path |
| `DSM_TORRENT_WATCH_PATH` | No | — | Compatibility path for a mounted Download Station watch folder |
| `DSM_AUTO_DELETE` | No | `false` | Compatibility toggle retained during migration |
| `TELEGRAM_LANGUAGE` | No | `en` | Language identifier |
| `TELEGRAM_DSM_PASSWORD_USER_ID` | No | — | Compatibility setting for interactive password flow |
| `TZ` | No | `UTC` | TZ database timezone name |

Boolean values accept `true/false`, `1/0`, `yes/no`, and `on/off`. ID lists must contain integers separated by commas. Invalid configuration stops startup with a redacted error.

### TLS

Keep `DSM_TLS_VERIFY=true`. Use a publicly trusted DSM certificate or arrange for the container to trust your private CA. A CA file must be mounted read-only and installed or referenced according to the container release's documented trust mechanism. Never place a DSM password in the URL.

Setting verification to `false` permits interception of DSM credentials and task data. Use it only as a short-lived diagnostic on a trusted network while correcting certificates.

## Data and backups

The SQLite database at `DATABASE_PATH` contains observed tasks, transitions, notification delivery state, and migration markers. It does not store DSM or Telegram credentials.

It also stores each Telegram user's destination preference and successful-folder
history. `/destination` ranks folders from live DSM task history, durable personal
usage, and `DSM_DESTINATION_PRESETS`. Temporary DSM paths ending in `/incomplete`
are presented as their parent destination. The chooser shows the three strongest
matches without exposing internal usage counters; `/destinations` shows additional
choices. Manual paths remain available with `/destination <folder>`.

Stop Synobot before taking a simple filesystem copy of the database:

```shell
docker compose stop synobot
cp data/synobot.db data/synobot.db.backup
docker compose start synobot
```

On first start, Synobot can import a legacy `taskdata.json` when it is available at the expected application location. Import is idempotent. Preserve the original file until the migration and notifications have been verified. See [MIGRATION.md](MIGRATION.md).

## Updating

1. Read [CHANGELOG.md](CHANGELOG.md) and back up `/data`.
2. Change the image to a specific newer tag.
3. Run `docker compose pull && docker compose up -d`.
4. Inspect startup logs and run `/health` and `/tasks`.
5. If validation fails, restore the previous tag and database backup as described in [MIGRATION.md](MIGRATION.md).

## Development

```shell
python -m venv .venv
. .venv/bin/activate
pip install -e . -r requirements-dev.txt
pytest
```

The supported entry point is `python -m synobot`. Never use live Telegram or DSM credentials in tests.

## Security and support

- Security policy: [SECURITY.md](SECURITY.md)
- Migration and rollback: [MIGRATION.md](MIGRATION.md)
- Raspberry Pi deployment: [docs/DEPLOY_RPI.md](docs/DEPLOY_RPI.md)
- Legacy Synology deployment: [docs/DEPLOY_SYNOLOGY.md](docs/DEPLOY_SYNOLOGY.md)
- Troubleshooting: [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)
