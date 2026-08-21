# Changelog

This project follows semantic versioning from Synobot 1.0 onward.

## 1.0.0

### Added

- Async Telegram application based on the current `python-telegram-bot` architecture.
- Validated, immutable configuration with secret-file support.
- Typed Synology Download Station client and error hierarchy.
- Transactional SQLite task state and durable notification events.
- Supervised, non-overlapping DSM monitor with outage backoff and recovery reporting.
- Role-aware authorization boundary for Telegram handlers.
- `/health`, `/tasks`, `/stats`, `/dslogin`, and `/add` commands.
- Modern container, Compose deployment guidance, CI, and operational documentation.

### Changed

- New descriptive environment-variable names replace legacy names.
- DSM mutations use POST and all active DSM requests use explicit timeouts.
- Telegram and DSM processing are isolated from the async event loop.
- TLS verification defaults to enabled.
- Production deployments use persistent `/data` storage.

### Security

- Removed unsafe environment parsing and secret-bearing logs.
- Hardened torrent upload filenames and temporary-file cleanup.
- Scoped authorization to numeric Telegram identities and private chats.
- Added graceful shutdown and redacted configuration failures.

### Migration

- Legacy variable aliases remain temporarily available with warnings.
- Legacy `taskdata.json` can be imported idempotently into SQLite.
- See `MIGRATION.md` before upgrading from 0.x.

## 0.19.0

- Added the asynchronous Telegram adapter while retaining the modern core.

## 0.18.0

- Added packaged architecture, typed DSM client, authorization, SQLite repository, and task reconciliation.

## 0.17.0

- Added characterization tests and CI coverage enforcement.

## 0.16.0

- Stabilized configuration, logging, DSM requests, uploads, polling, and shutdown.

## 0.15.0 — 2023-09-29

- Added YouTube link handling and English README content.

Earlier 0.x history remains available in the Git repository.
