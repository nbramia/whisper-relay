#!/usr/bin/env bash
# Generate ~/.config/systemd/user/whisper-relay-tailscale.service (oneshot after gateway is up).
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

DEST="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/whisper-relay-tailscale.service"
mkdir -p "$(dirname "$DEST")"

cat >"$DEST" <<EOF
[Unit]
Description=Tailscale Serve proxy for whisper-relay
After=network-online.target whisper-relay.service
Wants=whisper-relay.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${REPO_DIR}
EnvironmentFile=${ENV_PATH}
ExecStart=${REPO_DIR}/scripts/setup-tailscale.sh

[Install]
WantedBy=default.target
EOF

echo "Wrote ${DEST}"
