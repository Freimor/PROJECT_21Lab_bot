#!/bin/sh
set -e
UPLOAD_DIR="${UPLOAD_DIR:-/app/uploads}"
mkdir -p "$UPLOAD_DIR/products" "$UPLOAD_DIR/quests"
# Named volumes are root-owned on first create; app runs as lab21.
if [ "$(id -u)" = "0" ]; then
  chown -R lab21:lab21 "$UPLOAD_DIR"
  exec runuser -u lab21 -- "$@"
fi
exec "$@"
