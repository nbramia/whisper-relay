#!/usr/bin/env bash
# Pull the latest code for a production checkout and restart the whisper-relay
# service(s) — the update path for an already-installed systemd deployment.
#
# This is not what installs the unit(s) (see install-systemd*.sh, which only
# generate/install them and are out of this script's scope). It exists to
# close two real gaps:
#   - issue #42: a checkout whose branch has no upstream configured reports
#     `git pull` success without fetching anything, and nothing checked that
#     before restarting — a "successful" deploy silently re-served the exact
#     same commit that was already running.
#   - issue #47: both production instances run as `systemctl --user` units
#     sharing one checkout, but this script only knew `sudo systemctl
#     restart` (unit-not-found against a user unit, while prompting for a
#     password it didn't need, inside a script that aborts on error) and only
#     restarted one unit — a pull updates the shared editable install under
#     both, leaving the other instance running stale in-memory code until its
#     next unrelated restart.
#
# Usage: scripts/deploy.sh [--service NAME]... [--user|--system] [--no-restart]
#   --service NAME   systemd unit to restart on an actual update (repeatable;
#                    default: $DEPLOY_SYSTEMD_SERVICE — space-separated for
#                    more than one — or "whisper-relay" if that's also unset)
#   --user           restart every --service via `systemctl --user` (no sudo)
#   --system         restart every --service via `sudo systemctl`
#   --no-restart     pull and report only; never touch any service (used by tests)
#
# Without --user/--system, each service's scope is auto-detected: a unit
# `systemctl --user cat NAME` can see is restarted with `systemctl --user`;
# anything else falls back to `sudo systemctl`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SERVICES=()
SCOPE="auto"
DO_RESTART=true

while [[ $# -gt 0 ]]; do
  case "$1" in
    --service)
      # Reject a missing value AND a flag-looking one ("--service --user"
      # would otherwise silently take "--user" as a literal unit name,
      # leaving --user's own effect never applied).
      if [[ $# -lt 2 || "$2" == --* ]]; then
        echo "[deploy] ERROR: --service requires a unit name argument" >&2
        exit 2
      fi
      SERVICES+=("$2")
      shift 2
      ;;
    --user)
      SCOPE="user"
      shift
      ;;
    --system)
      SCOPE="system"
      shift
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

if [[ ${#SERVICES[@]} -eq 0 ]]; then
  # Intentional word-splitting: DEPLOY_SYSTEMD_SERVICE may name more than one
  # unit, space-separated.
  # shellcheck disable=SC2206
  SERVICES=(${DEPLOY_SYSTEMD_SERVICE:-whisper-relay})
fi

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

# The configured remote for this branch, not a hardcoded "origin" (#47) — a
# checkout tracking a differently-named remote would otherwise fetch nothing
# from it and fall back to whatever "origin" happens to be.
REMOTE="$(git config --get "branch.$BRANCH.remote")"

# --- Step 2: pull, but judge success by commit hash, not exit status -----------
BEFORE_SHA="$(git rev-parse HEAD)"
log "current commit: $BEFORE_SHA"

git fetch "$REMOTE"
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
  log "no code change — skipping restart of ${SERVICES[*]}"
  exit 0
fi

restart_one() {
  local service="$1" scope="$SCOPE"
  if [[ "$scope" == "auto" ]]; then
    if systemctl --user cat "$service" >/dev/null 2>&1; then
      scope="user"
    else
      scope="system"
    fi
  fi
  if [[ "$scope" == "user" ]]; then
    log "restarting $service (systemctl --user)"
    systemctl --user restart "$service"
  else
    log "restarting $service (sudo systemctl)"
    sudo systemctl restart "$service"
  fi
  log "restart requested for $service"
}

for service in "${SERVICES[@]}"; do
  restart_one "$service"
done
