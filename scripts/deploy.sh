#!/usr/bin/env bash
# Pull the latest code for a production checkout and restart the whisper-relay
# service — the update path for an already-installed systemd deployment.
#
# This is not what installs the unit (see install-systemd*.sh, which only
# generate/install it and are out of this script's scope). It exists to close
# a real gap (issue #42): a checkout whose branch has no upstream configured
# reports `git pull` success without fetching anything, and nothing checked
# that before restarting — a "successful" deploy silently re-served the exact
# same commit that was already running.
#
# Usage: scripts/deploy.sh [--service NAME] [--no-restart]
#   --service NAME   systemd unit to restart on an actual update (default: whisper-relay)
#   --no-restart     pull and report only; never touch the service (used by tests)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SERVICE_NAME="${DEPLOY_SYSTEMD_SERVICE:-whisper-relay}"
DO_RESTART=true

while [[ $# -gt 0 ]]; do
  case "$1" in
    --service)
      SERVICE_NAME="$2"
      shift 2
      ;;
    --no-restart)
      DO_RESTART=false
      shift
      ;;
    *)
      echo "[deploy] ERROR: unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

log() { echo "[deploy] $*"; }
err() { echo "[deploy] ERROR: $*" >&2; }

# --- Step 1: this checkout's branch must track a remote -----------------------
# Without this check, `git pull` on a branch with no upstream either fails with
# an unrelated-looking error or (in older/looser configurations) silently does
# nothing while still exiting 0 — which is exactly the failure this issue
# reports: a pull that "succeeds" without moving HEAD.
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$BRANCH" == "HEAD" ]]; then
  err "checkout is in detached HEAD state — nothing to pull against. Check out a tracking branch first."
  exit 1
fi

if ! UPSTREAM="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null)"; then
  err "branch '$BRANCH' has no upstream configured — 'git pull' would silently report success without fetching anything."
  err "Fix with: git branch --set-upstream-to=origin/$BRANCH $BRANCH"
  exit 1
fi
log "branch '$BRANCH' tracks '$UPSTREAM'"

# --- Step 2: pull, but judge success by commit hash, not exit status -----------
BEFORE_SHA="$(git rev-parse HEAD)"
log "current commit: $BEFORE_SHA"

git fetch origin
git pull --ff-only

AFTER_SHA="$(git rev-parse HEAD)"

if [[ "$BEFORE_SHA" == "$AFTER_SHA" ]]; then
  log "already up to date at $AFTER_SHA — nothing to deploy"
  UPDATED=false
else
  log "deployed update to $AFTER_SHA (was $BEFORE_SHA)"
  UPDATED=true
fi

# --- Step 3: restart only when there's actually something new to serve --------
if [[ "$DO_RESTART" == false ]]; then
  log "--no-restart: skipping service restart"
  exit 0
fi

if [[ "$UPDATED" == false ]]; then
  log "no code change — skipping restart of $SERVICE_NAME"
  exit 0
fi

log "restarting $SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"
log "restart requested for $SERVICE_NAME"
