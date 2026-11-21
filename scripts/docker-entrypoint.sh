#!/bin/sh
set -e
UPLOAD_DIR="${UPLOAD_DIR:-/app/uploads}"
PROJECT_FILES_DIR="${PROJECT_FILES_DIR:-/app/project_files}"
mkdir -p "$UPLOAD_DIR/products" "$UPLOAD_DIR/quests" "$PROJECT_FILES_DIR"
# Named volumes are root-owned on first create; app runs as lab21.
if [ "$(id -u)" = "0" ]; then
  chown -R lab21:lab21 "$UPLOAD_DIR" "$PROJECT_FILES_DIR"
  exec runuser -u lab21 -- "$@"
fi
exec "$@"
