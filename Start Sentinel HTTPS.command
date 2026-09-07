#!/usr/bin/env bash
DIR="$(cd "$(dirname "$0")" && pwd)"
export SENTINEL_HTTPS=1
export SENTINEL_HOST="${SENTINEL_HOST:-127.0.0.1}"
export SENTINEL_PORT="${SENTINEL_PORT:-8088}"
exec "$DIR/start-sentinel.sh"
