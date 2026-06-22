#!/usr/bin/env bash
# Deprecated — Tailscale HTTPS serves LifeOS /chat (ADR-005), not whisper-relay UI.
set -euo pipefail

cat <<'EOF' >&2
whisper-relay no longer exposes a browser UI on the tailnet.

Use LifeOS instead:
  cd ~/Code/LifeOS
  ./scripts/install-systemd-tailscale.sh
  systemctl --user enable --now lifeos-tailscale.service

Disable the old unit if still enabled:
  systemctl --user disable --now whisper-relay-tailscale.service

Phone bookmark: https://<machine>.<tailnet>.ts.net/chat
EOF
exit 1
