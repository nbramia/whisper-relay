#!/usr/bin/env bash
# Install whisper-relay for headless autostart on boot (systemd user services + linger).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

"${ROOT}/scripts/install-systemd-user.sh"
"${ROOT}/scripts/install-systemd-tailscale.sh"

if [[ "$(loginctl show-user "${USER}" -p Linger --value 2>/dev/null || true)" != "yes" ]]; then
  echo "Enabling systemd linger for ${USER} (starts user services at boot without login)..."
  sudo loginctl enable-linger "${USER}"
fi

systemctl --user daemon-reload
systemctl --user enable --now whisper-relay.service
systemctl --user enable --now whisper-relay-tailscale.service

echo ""
echo "Autostart enabled."
echo "  systemctl --user status whisper-relay"
echo "  systemctl --user status whisper-relay-tailscale"
echo "  journalctl --user -u whisper-relay -f"
