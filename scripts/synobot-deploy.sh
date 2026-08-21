#!/usr/bin/env bash

set -euo pipefail
IFS=$'\n\t'

readonly DEPLOY_SHA="${1:-origin/master}"
readonly REPO_DIR="${SYNOBOT_REPO_DIR:-/home/q8hk/synobot}"
readonly DEPLOY_BRANCH="${SYNOBOT_DEPLOY_BRANCH:-master}"
readonly ENV_FILE="${SYNOBOT_ENV_FILE:-.env}"
readonly LOCK_FILE="${SYNOBOT_DEPLOY_LOCK:-/tmp/synobot-deploy.lock}"
readonly LOG_DIR="${SYNOBOT_LOG_DIR:-$REPO_DIR/logs}"
readonly TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
LOG_FILE=""

log() {
  printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$LOG_FILE"
}

die() {
  log "ERROR: $*"
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

main() {
  require_cmd docker
  require_cmd flock
  require_cmd git
  mkdir -p "$LOG_DIR"
  LOG_FILE="$LOG_DIR/deploy-$TIMESTAMP.log"
  touch "$LOG_FILE"

  exec 9>"$LOCK_FILE"
  flock -n 9 || die "Another Synobot deployment is already running"
  [[ -d "$REPO_DIR/.git" ]] || die "Repository checkout not found at $REPO_DIR"
  [[ -f "$REPO_DIR/$ENV_FILE" ]] || die "Missing $REPO_DIR/$ENV_FILE"
  [[ -f "$REPO_DIR/secrets/telegram_bot_token" ]] || die "Missing Telegram token secret"
  [[ -f "$REPO_DIR/secrets/dsm_password" ]] || die "Missing DSM password secret"

  cd "$REPO_DIR"
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
  : "${REGISTRY:?Missing REGISTRY in $ENV_FILE}"
  : "${IMAGE_NAME:?Missing IMAGE_NAME in $ENV_FILE}"
  : "${TELEGRAM_ADMIN_USER_IDS:?Missing TELEGRAM_ADMIN_USER_IDS in $ENV_FILE}"
  : "${DSM_BASE_URL:?Missing DSM_BASE_URL in $ENV_FILE}"

  log "Fetching origin/$DEPLOY_BRANCH"
  git fetch --prune origin "$DEPLOY_BRANCH"
  git checkout -f "$DEPLOY_BRANCH"
  git reset --hard "$DEPLOY_SHA"

  local revision image
  revision="$(git rev-parse HEAD)"
  image="$REGISTRY/$IMAGE_NAME:${TAG:-latest}"
  log "Building ARM64 image $image from $revision"
  DOCKER_BUILDKIT=1 docker build \
    --build-arg "VERSION=${TAG:-latest}" \
    --build-arg "REVISION=$revision" \
    -t "$image" .

  if [[ -n "${REGISTRY_USERNAME:-}" && -n "${REGISTRY_PASSWORD:-}" ]]; then
    printf '%s' "$REGISTRY_PASSWORD" | docker login "$REGISTRY" \
      --username "$REGISTRY_USERNAME" --password-stdin >/dev/null
  fi
  log "Pushing $image"
  docker push "$image"

  if [[ -f "$REPO_DIR/taskdata.json" ]]; then
    log "Importing preserved legacy task state into the persistent volume"
    docker compose -f compose.yaml create synobot
    local migration_container
    migration_container="$(docker compose -f compose.yaml ps -aq synobot)"
    [[ -n "$migration_container" ]] || die "Could not create migration container"
    docker cp "$REPO_DIR/taskdata.json" "$migration_container:/data/taskdata.json"
    docker run --rm --user 0:0 --volume synobot_synobot-data:/data "$image" \
      chown 10001:10001 /data/taskdata.json
    mv "$REPO_DIR/taskdata.json" "$REPO_DIR/taskdata.json.imported"
  fi

  log "Updating Synobot"
  docker compose -f compose.yaml pull
  docker compose -f compose.yaml up -d --pull=always --force-recreate

  local container_id status
  container_id="$(docker compose -f compose.yaml ps -q synobot)"
  [[ -n "$container_id" ]] || die "Synobot container was not created"
  for _ in $(seq 1 18); do
    status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id")"
    [[ "$status" == healthy ]] && break
    [[ "$status" == exited || "$status" == dead ]] && die "Synobot stopped during startup"
    sleep 5
  done
  [[ "$status" == healthy ]] || die "Synobot did not become healthy (status: $status)"
  docker compose -f compose.yaml ps | tee -a "$LOG_FILE"
  log "Deployment completed successfully"
}

main "$@"
