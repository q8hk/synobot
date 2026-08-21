# Deploying Synobot on Raspberry Pi

Production runs on the Raspberry Pi from `/home/q8hk/synobot`. A repository-specific
self-hosted GitHub Actions runner executes `scripts/synobot-deploy.sh` after every
push to `master`.

The deployment script checks out the exact workflow commit, builds the ARM64 image
on the Pi, pushes it to `registry.abdullahserver.local`, recreates the Compose
service, and waits for the container health check. Deployments are serialized with
`flock`, and logs are retained under `logs/`.

Runtime configuration is deliberately host-local:

- `.env` contains non-secret settings and registry coordinates.
- `secrets/telegram_bot_token` contains the Telegram bot token.
- `secrets/dsm_password` contains the DSM service-account password.
- The Docker volume `synobot-data` contains the SQLite database and the preserved
  legacy `taskdata.json`.

None of the host-local files should be committed. Restrict `.env` to mode `0600`, the
`secrets` directory to `0700`, and individual secret files to `0600`.

## Manual deployment

From the Pi:

```bash
cd /home/q8hk/synobot
bash scripts/synobot-deploy.sh origin/master
```

Use a commit SHA instead of `origin/master` to reproduce or roll back an exact
release. Before rolling back across database changes, stop the service and back up
`/data/synobot.db` from the `synobot-data` volume.

## Verification

```bash
cd /home/q8hk/synobot
docker compose ps
docker compose logs --tail=100 synobot
docker inspect --format '{{.State.Health.Status}}' synobot-synobot-1
```

The deployment is successful only when the container reports `healthy`. The bot
must also be checked with `/health` and `/tasks` in Telegram after a migration.
