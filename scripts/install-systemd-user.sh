#!/usr/bin/env bash
# Generate ~/.config/systemd/user/whisper-relay.service from .env deploy settings.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${DEPLOY_ENV_FILE:-$ROOT/.env}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

REPO_DIR="${DEPLOY_REPO_DIR:-$ROOT}"
ENV_PATH="${DEPLOY_ENV_FILE:-$ROOT/.env}"
UVICORN_BIN="${DEPLOY_UVICORN:-$(command -v uvicorn)}"
PORT="${VOICE_GATEWAY_PORT:-8888}"
HOST="${VOICE_GATEWAY_HOST:-127.0.0.1}"

pyenv_env=""
if [[ "$UVICORN_BIN" == *"/.pyenv/"* ]]; then
  pyenv_bin="$(dirname "$UVICORN_BIN")"
  pyenv_root="${pyenv_bin%/versions/*}"
  pyenv_env=$(
    cat <<EOF
Environment=PATH=${pyenv_bin}:/usr/local/bin:/usr/bin:/bin
Environment=PYENV_ROOT=${pyenv_root}
Environment=HOME=${HOME}
EOF
  )
fi

DEST="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/whisper-relay.service"
mkdir -p "$(dirname "$DEST")"

cat >"$DEST" <<EOF
[Unit]
Description=Whisper Relay voice gateway
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=600
StartLimitBurst=5

[Service]
Type=simple
WorkingDirectory=${REPO_DIR}
EnvironmentFile=${ENV_PATH}
${pyenv_env}
ExecStart=${UVICORN_BIN} voice_gateway.main:app --host ${HOST} --port ${PORT}
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
EOF

echo "Wrote ${DEST}"
