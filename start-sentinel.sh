#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTROLLER_DIR="$ROOT_DIR/sentinel-controller"
VENV_DIR="$CONTROLLER_DIR/.venv"
REQUIREMENTS_FILE="$CONTROLLER_DIR/requirements.txt"
INSTALL_STAMP="$VENV_DIR/.sentinel-requirements-installed"

HOST="${SENTINEL_HOST:-0.0.0.0}"
PORT="${SENTINEL_PORT:-8088}"
HTTPS_ENABLED="${SENTINEL_HTTPS:-0}"
TLS_DIR="$CONTROLLER_DIR/data/tls"
TLS_CERT_FILE="${SENTINEL_TLS_CERT_FILE:-$TLS_DIR/localhost.crt}"
TLS_KEY_FILE="${SENTINEL_TLS_KEY_FILE:-$TLS_DIR/localhost.key}"
SCHEME="http"
if [[ "$HTTPS_ENABLED" == "1" || "$HTTPS_ENABLED" == "true" ]]; then
  SCHEME="https"
fi
DASHBOARD_URL="${SCHEME}://localhost:${PORT}/dashboard"

if [[ ! -d "$CONTROLLER_DIR" ]]; then
  echo "Could not find Sentinel controller folder:"
  echo "$CONTROLLER_DIR"
  exit 1
fi

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "Python is required to start Sentinel, but it was not found."
  exit 1
fi

cd "$CONTROLLER_DIR"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  echo "Creating Sentinel Python environment..."
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

if [[ ! -f "$INSTALL_STAMP" || "$REQUIREMENTS_FILE" -nt "$INSTALL_STAMP" ]]; then
  echo "Installing Sentinel server dependencies..."
  python -m pip install --upgrade pip
  python -m pip install -r "$REQUIREMENTS_FILE"
  touch "$INSTALL_STAMP"
fi

UVICORN_SSL_ARGS=()
if [[ "$SCHEME" == "https" ]]; then
  mkdir -p "$TLS_DIR"
  if [[ ! -f "$TLS_CERT_FILE" || ! -f "$TLS_KEY_FILE" ]]; then
    if ! command -v openssl >/dev/null 2>&1; then
      echo "OpenSSL is required to create a local HTTPS certificate."
      exit 1
    fi
    echo "Creating local HTTPS certificate for localhost..."
    openssl req -x509 -newkey rsa:2048 -nodes \
      -keyout "$TLS_KEY_FILE" \
      -out "$TLS_CERT_FILE" \
      -days 825 \
      -subj "/CN=localhost" \
      -addext "subjectAltName=DNS:localhost,IP:127.0.0.1,IP:::1" >/dev/null 2>&1
  fi
  UVICORN_SSL_ARGS=(--ssl-certfile "$TLS_CERT_FILE" --ssl-keyfile "$TLS_KEY_FILE")
fi

echo
echo "Starting Sentinel server..."
echo "Dashboard: $DASHBOARD_URL"
echo "API docs:  ${SCHEME}://localhost:${PORT}/docs"
echo
echo "Press Ctrl+C in this window to stop Sentinel."
echo

if command -v open >/dev/null 2>&1; then
  (sleep 2 && open "$DASHBOARD_URL") >/dev/null 2>&1 &
fi

exec python -m uvicorn app.main:app --host "$HOST" --port "$PORT" "${UVICORN_SSL_ARGS[@]}"
