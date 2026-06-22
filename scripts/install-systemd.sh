#!/usr/bin/env bash
# Generate /etc/systemd/system/whisper-relay.service from .env deploy settings (requires sudo).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${DEPLOY_ENV_FILE:-$ROOT/.env}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

: "${DEPLOY_SYSTEMD_USER:?Set DEPLOY_SYSTEMD_USER in .env}"

REPO_DIR="${DEPLOY_REPO_DIR:-$ROOT}"
ENV_PATH="${DEPLOY_ENV_FILE:-$ROOT/.env}"
UVICORN_BIN="${DEPLOY_UVICORN:-$(command -v uvicorn)}"
PORT="${VOICE_GATEWAY_PORT:-9788}"
HOST="${VOICE_GATEWAY_HOST:-127.0.0.1}"

DEST="/etc/systemd/system/whisper-relay.service"

sudo tee "$DEST" >/dev/null <<EOF
[Unit]
Description=Whisper Relay voice gateway
After=network.target

[Service]
Type=simple
User=${DEPLOY_SYSTEMD_USER}
WorkingDirectory=${REPO_DIR}
EnvironmentFile=${ENV_PATH}
ExecStart=${UVICORN_BIN} voice_gateway.main:app --host ${HOST} --port ${PORT}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "Wrote ${DEST}"
echo "Run: sudo systemctl daemon-reload && sudo systemctl enable --now whisper-relay"
