# Deploy

Systemd units are generated from `.env` deploy settings — do not commit machine-specific paths here.

```bash
# Headless autostart on boot (recommended)
bash scripts/install-autostart.sh

# Or step-by-step:
bash scripts/install-systemd-user.sh
bash scripts/install-systemd-tailscale.sh

# System-wide service (set DEPLOY_SYSTEMD_USER in .env)
bash scripts/install-systemd.sh
```

See `.env.example` for `DEPLOY_REPO_DIR`, `DEPLOY_ENV_FILE`, `DEPLOY_UVICORN`, and `DEPLOY_SYSTEMD_USER`.
