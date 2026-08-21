# Troubleshooting Synobot

Start with three facts: the exact image tag/digest, the first startup error, and whether DSM is reachable from the container. Redact all secrets, cookies, private addresses, and personal task names before sharing evidence.

## Health meanings

Synobot exposes two related signals:

- `/health` checks that the Telegram application is running and attempts a DSM statistics call. It reports DSM unavailable when that call fails.
- The internal monitor tracks whether polling is running, whether its last DSM poll connected, its last success time, and the last error class/message. During an outage it backs off and announces loss and later recovery once.

A running container can therefore be operational for Telegram but degraded because DSM is unavailable. A container that repeatedly exits has a startup, configuration, filesystem, or application failure—not merely a DSM health failure.

## Container exits at startup

Inspect:

```shell
docker compose ps
docker compose logs --tail=200 synobot
```

Common causes:

- a missing required setting;
- an ID list containing a username, zero, or non-numeric text;
- an unreadable/empty secret file;
- a malformed `DSM_BASE_URL`;
- no unattended DSM password;
- an unwritable database directory.

Configuration errors name the setting but should not print its value. Fix the input rather than adding a placeholder secret.

## Telegram bot does not reply

1. Confirm the container is running and the Telegram token file is non-empty.
2. Confirm you messaged the bot privately and used a numeric user ID in `TELEGRAM_ADMIN_USER_IDS`.
3. Confirm another copy of the bot is not polling with the same token.
4. Check outbound network/DNS access to Telegram from the NAS.
5. Review logs for an error class without publishing the update or token.

“You are not authorized” normally means the numeric user ID is absent or the command came from a group chat. Notification recipient IDs do not grant command access.

## DSM unavailable or login failed

Check, in order:

1. `DSM_BASE_URL` includes the correct scheme, hostname, and port.
2. Download Station is installed and running.
3. The dedicated account can sign in and is allowed to use Download Station.
4. The password secret contains only the password.
5. If 2FA is enabled, the TOTP secret is correct and NAS/container clocks are synchronized.
6. DSM firewall/reverse-proxy rules permit the container connection.
7. The certificate matches the hostname and its chain is trusted.

Synobot retries an expired authenticated session for safe requests. It deliberately does not blindly retry task creation because doing so could submit the same download twice.

## TLS certificate errors

- Use the DNS name present in the certificate, not an IP address unless the certificate includes that IP.
- Include intermediate certificates on DSM.
- Install the private root/intermediate CA into the container trust store using the method documented for the release image.
- Confirm NAS and container time are correct.

`DSM_TLS_VERIFY=false` may distinguish a trust problem from a network problem, but it exposes credentials to interception and is not a permanent fix.

## `/tasks` is empty or incomplete

Compare with Download Station while signed in as the same dedicated account. DSM may only expose tasks visible to that account. A task with missing size/transfer detail can display limited progress, but it should not prevent later tasks from being processed.

## URL or torrent rejected

- `/add` requires exactly one HTTP, HTTPS, FTP, or magnet URL.
- Plain text accepts magnet and supported YouTube URLs; use `/add` for general URLs.
- Documents must have a `.torrent` filename.
- Download Station ultimately decides protocol/provider support and can reject an otherwise valid URL.
- Verify the DSM account's Download Station permissions and destination configuration.

Torrent uploads use a generated temporary filename and are removed after submission; the Telegram-supplied name is not used as a filesystem path.

## Repeated or missing notifications

Confirm `TELEGRAM_NOTIFY_USER_IDS` contains the intended recipients and they have started a conversation with the bot. The SQLite repository tracks events and delivery state, so `/data` must persist across recreation. Repeated notifications after every restart usually indicate an ephemeral/mis-mounted database or repeated legacy imports.

Do not delete the database merely to clear a notification symptom; preserve it for diagnosis first.

## Database errors

1. Stop the container.
2. Verify the host `data` directory exists and is writable by the container user.
3. Preserve a copy of the database and logs.
4. Check available disk space and filesystem health.
5. Restore the last known-good backup when corruption is confirmed.

Do not copy a live SQLite file as the only backup and do not point an older release at a database upgraded by a newer release unless downgrade compatibility is documented.

## Legacy migration did not occur

Confirm the original `taskdata.json` is valid JSON, readable at the expected legacy path, and not already marked as imported in the database. Migration is intentionally idempotent. Keep the source backup and follow `MIGRATION.md`; never repeatedly rename or modify it to force imports.

## Graceful shutdown

`docker compose stop` should allow the Telegram application to stop the monitor and close DSM/database resources. If the container must be killed after the configured Docker timeout, preserve thread/task dumps and logs and report the exact release version.

## Safe diagnostic bundle

Useful sanitized evidence includes:

- exact Synobot version and image digest;
- DSM and Download Station versions;
- container state and exit code;
- error class and surrounding redacted log lines;
- whether `/health`, `/stats`, and `/tasks` work;
- whether failure began after a configuration, certificate, DSM, or image change.

Never include the Telegram token, DSM password, TOTP secret, cookies, authorization headers, full private URLs, or unredacted task names.
