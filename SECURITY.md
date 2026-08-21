# Security policy

## Supported versions

Security fixes are provided for the latest stable Synobot release. Older prereleases and the legacy 0.x runtime should be upgraded before reporting operational problems.

## Reporting a vulnerability

Do not open a public issue containing an exploit, bot token, DSM credential, TOTP secret, session cookie, private NAS address, or unredacted log. Use GitHub's private security-advisory reporting for this repository when available. Otherwise contact the repository owner privately through a channel already published on the owner's GitHub profile.

Include the affected Synobot version/image digest, deployment and DSM versions, minimal reproduction, expected and observed behavior, impact, and sanitized logs or proof of concept. Please allow time to confirm and remediate the report before public disclosure.

## Deployment requirements

- Use a dedicated, non-administrator DSM account with only the application permissions needed for Download Station.
- Allow only specific numeric Telegram user IDs. Usernames are not authorization identities.
- Keep the bot in private chats unless a later release explicitly documents group authorization.
- Keep `DSM_TLS_VERIFY=true`; use a trusted certificate or private CA.
- Store the Telegram token, DSM password, and TOTP secret in read-only secret files.
- Restrict access to the Docker socket, Container Manager, logs, Compose files, mounted secrets, and `/data`.
- Pin a released image tag or digest and review release notes before upgrading.
- Back up the SQLite database while Synobot is stopped.

The SQLite database contains task history and notification state but not credentials. It can still reveal filenames and usage patterns and should be protected accordingly.

## Secret handling

Synobot resolves `NAME_FILE` before `NAME` for supported secrets. The application must never log tokens, passwords, TOTP secrets, cookies, or authorization headers. If a secret is accidentally exposed:

1. Stop the container.
2. Revoke and regenerate the Telegram bot token through BotFather.
3. Change the DSM service-account password.
4. Re-enrol DSM TOTP when that secret was exposed.
5. Remove or restrict affected logs and backups.
6. Restart with new secret files and verify access.

## TLS warning

`DSM_TLS_VERIFY=false` disables certificate validation. Encryption without identity verification does not protect against an active interceptor. This switch exists for limited diagnostics and is not a secure permanent configuration.

## Scope boundaries

Synobot controls Download Station; it is not a security boundary for DSM. DSM account permissions, NAS firewall policy, remote-access configuration, Telegram account security, and host/container administration remain the operator's responsibility.
