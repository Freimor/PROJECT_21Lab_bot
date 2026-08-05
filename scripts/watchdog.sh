#!/bin/sh
set -eu

CONTROL_DIR="${CONTROL_DIR:-/control}"
REPO_DIR="${REPO_DIR:-/deploy}"
REPO_URL="${REPO_URL:-https://github.com/Freimor/PROJECT_21Lab_bot.git}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
GITHUB_BRANCH="${GITHUB_BRANCH:-main}"
POLL_SECONDS="${WATCHDOG_POLL_SECONDS:-5}"
COMPOSE_PROJECT="${COMPOSE_PROJECT_NAME:-lab21}"

mkdir -p "$CONTROL_DIR" "$REPO_DIR"

log() {
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

authenticated_url() {
  if [ -z "${GITHUB_TOKEN:-}" ]; then
    printf '%s' "$REPO_URL"
    return 0
  fi
  printf '%s' "$REPO_URL" | sed "s#https://#https://x-access-token:${GITHUB_TOKEN}@#"
}

ensure_repo() {
  if [ -d "$REPO_DIR/.git" ]; then
    return 0
  fi
  log "cloning $REPO_URL into $REPO_DIR"
  tmp_dir="$(mktemp -d)"
  git clone --branch "$GITHUB_BRANCH" "$(authenticated_url)" "$tmp_dir/repo"
  # Keep bind-mounted secrets like .env that may already exist in REPO_DIR.
  find "$tmp_dir/repo" -mindepth 1 -maxdepth 1 -exec cp -a {} "$REPO_DIR/" \;
  rm -rf "$tmp_dir"
}

apply_updates() {
  ensure_repo
  cd "$REPO_DIR"
  git remote set-url origin "$(authenticated_url)"
  git fetch --prune origin "$GITHUB_BRANCH"
  local_sha="$(git rev-parse HEAD)"
  remote_sha="$(git rev-parse "origin/${GITHUB_BRANCH}")"
  if [ "$local_sha" = "$remote_sha" ]; then
    log "already up to date at $local_sha"
    UPDATED=0
  else
    log "updating $local_sha -> $remote_sha"
    git checkout -B "$GITHUB_BRANCH" "origin/${GITHUB_BRANCH}"
    UPDATED=1
  fi
  CURRENT_SHA="$(git rev-parse HEAD)"
  export CURRENT_SHA UPDATED
}

rebuild_bot() {
  cd "$REPO_DIR"
  if [ ! -f "$COMPOSE_FILE" ]; then
    log "compose file missing: $REPO_DIR/$COMPOSE_FILE"
    return 1
  fi
  docker compose -p "$COMPOSE_PROJECT" -f "$COMPOSE_FILE" build \
    --build-arg "GIT_SHA=${CURRENT_SHA:-unknown}" bot
  docker compose -p "$COMPOSE_PROJECT" -f "$COMPOSE_FILE" up -d --no-deps bot
}

write_result() {
  request_file="$1"
  status="$2"
  detail="$3"
  python3 - "$request_file" "$status" "$detail" "${CURRENT_SHA:-unknown}" "${UPDATED:-0}" <<'PY'
import json, sys, pathlib
from datetime import UTC, datetime

request_path = pathlib.Path(sys.argv[1])
status = sys.argv[2]
detail = sys.argv[3]
current_sha = sys.argv[4]
updated = sys.argv[5] == "1"
payload = {}
if request_path.exists():
    payload = json.loads(request_path.read_text(encoding="utf-8"))
payload.update(
    {
        "status": status,
        "detail": detail,
        "finished_at": datetime.now(UTC).isoformat(),
        "applied_sha": current_sha,
        "updated": updated,
    }
)
result = request_path.parent / "restart.result"
result.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
PY
}

process_request() {
  request="$CONTROL_DIR/restart.requested"
  if [ ! -f "$request" ]; then
    return 0
  fi

  log "restart requested"
  UPDATED=0
  CURRENT_SHA="unknown"
  if apply_updates; then
    if rebuild_bot; then
      write_result "$request" "ok" "bot rebuilt and restarted"
      rm -f "$request"
      log "restart completed successfully"
      return 0
    fi
    write_result "$request" "error" "docker rebuild/restart failed"
  else
    write_result "$request" "error" "git update failed"
  fi
  rm -f "$request"
  log "restart finished with errors"
}

log "watchdog started (branch=$GITHUB_BRANCH poll=${POLL_SECONDS}s)"
while true; do
  process_request || true
  sleep "$POLL_SECONDS"
done
