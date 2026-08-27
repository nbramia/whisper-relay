# Deploy

Systemd units are generated from `.env` deploy settings — do not commit machine-specific paths here.

```bash
# Headless autostart on boot (recommended)
bash scripts/install-autostart.sh

# Or step-by-step:
bash scripts/install-systemd-user.sh

# Tailscale HTTPS serves LifeOS /chat — see LifeOS scripts/setup-tailscale.sh

# System-wide service (set DEPLOY_SYSTEMD_USER in .env)
bash scripts/install-systemd.sh
```

See `.env.example` for `DEPLOY_REPO_DIR`, `DEPLOY_ENV_FILE`, `DEPLOY_UVICORN`, and `DEPLOY_SYSTEMD_USER`.

## Updating an already-installed deployment

`scripts/deploy.sh` pulls the latest code for this checkout and restarts the
service — it never touches the unit file (that's `install-systemd*.sh`, above).

```bash
bash scripts/deploy.sh                      # pulls, restarts whisper-relay if updated
bash scripts/deploy.sh --service whisper-relay-taylor  # for a differently-named unit
```

It fails loudly instead of silently no-opping: a checkout whose branch has no
upstream configured is a hard error (`git pull` can otherwise exit 0 without
fetching anything — issue #42), and it always compares the commit hash before
and after pulling rather than trusting `git pull`'s exit status, reporting
"already up to date" distinctly from "deployed update to `<sha>`". The service
is only restarted when the commit actually changed.
