# whisper-relay

A voice transport layer for **LifeOS** — push-to-talk from your phone, spoken answers back.

whisper-relay turns speech into text, hands that text to LifeOS exactly as if you had typed it in the web chat or sent it via Telegram, then speaks LifeOS's reply. It does not run an agent, duplicate LifeOS tools, or make routing decisions. LifeOS behaves the same regardless of whether input came from a keyboard, Telegram, or your voice.

## How it fits together

This project is designed to work alongside two other open-source repos:

| Repo | Role in the voice flow |
|------|------------------------|
| **linux-whisper** | Local speech-to-text. Transcribes and polishes utterances on the Linux box — same pipeline as the desktop dictation app. |
| **LifeOS** | Personal agent harness. Receives the transcript via its existing chat API, runs the orchestrator (tools, memory, planning, agent spawns), and returns text responses. |
| **whisper-relay** (this repo) | Voice transport. Records audio from a mobile browser, normalizes it, calls linux-whisper for STT, submits text to LifeOS, synthesizes responses to speech, and serves audio back to the phone. |

```
phone browser (tap-to-talk)
        │
        ▼
  whisper-relay          ← you are here
   ┌────────────┐
   │ ffmpeg     │  normalize webm / mp4 / wav → 16 kHz mono
   │ linux-     │  STT + polish (desktop parity)
   │  whisper   │
   │ LifeOS     │  POST /api/ask/stream  (same as chat/Telegram)
   │  client    │  POST /api/chat/handoff on engine handoffs
   │ TTS        │  text → audio
   └────────────┘
        │
        ▼
   audio + transcript + response text
```

## Phase 1 scope

**In scope:**

- Tap-to-talk from a phone browser (Chrome or Safari, iOS or Android) over Tailscale
- One utterance per HTTP turn (`POST /api/voice/turn`)
- Spoken tool-status updates during long orchestrator turns
- Multi-turn conversation via LifeOS `conversation_id`
- Engine handoffs (`claude_intent` → `/api/chat/handoff`) — same as web chat

**Out of scope (Phase 1):**

- Continuous listening, streaming STT, WebRTC
- Native mobile app
- Third-party voice platforms (Vapi, Retell, Agora, Twilio, LiveKit, OpenAI Realtime)
- Any agent reasoning, tool definitions, or orchestration logic inside whisper-relay

## Status

Phase 1 is implemented and running: tap-to-talk from a phone browser over Tailscale → STT with desktop-parity polish → LifeOS round-trip → spoken response, verified end-to-end on desktop and iPhone. Browsers that can record audio upload it for the full STT + polish pipeline; the capture path is feature-detected per device. Architecture decisions are in [`docs/adr/`](docs/adr/).

## Quick start

```bash
git clone <repository-url> whisper-relay
cd whisper-relay
pip install -e ".[dev]"
pip install -e ../linux-whisper   # sibling checkout; GPU STT

# System deps (Ubuntu)
sudo apt install ffmpeg espeak-ng

# Kokoro TTS models (see ADR-003)
bash scripts/setup-kokoro.sh

# Copy env template only on a fresh clone (skip if .env already exists):
#   test -f .env || cp .env.example .env
# If .env is a symlink, cp overwrites the link target — edit the Sync copy directly.

# Run (internal port — Tailscale Serve proxies this to the tailnet)
uvicorn voice_gateway.main:app --host 127.0.0.1 --port "${VOICE_GATEWAY_PORT:-8888}"

# Expose on tailnet (run scripts/setup-tailscale.sh once)
bash scripts/setup-tailscale.sh
```

Set `TAILNET_HTTPS_URL` in `.env` to your machine's Tailscale HTTPS URL (from `tailscale status` / MagicDNS).

| URL | Works? | Microphone? |
|-----|--------|-------------|
| `https://<machine>.<tailnet>.ts.net` | Yes | Yes — **use HTTPS on your phone** |
| `http://<machine>.<tailnet>.ts.net:<TAILNET_HTTP_PORT>` | Yes | No (browser blocks mic on HTTP) |
| `http://…:443` or `http://…` when that port is HTTPS | **No** — shows "Client sent an HTTP request to an HTTPS server" | — |

Open your **`TAILNET_HTTPS_URL`** on your phone (note `https`, no port). HTTP on port 443 is not valid — that port speaks TLS only.

For CI or local dev without Kokoro models, set `TTS_BACKEND=null` in `.env`.

## Prerequisites

- Linux workstation on your tailnet (GPU recommended for linux-whisper)
- **linux-whisper** installed and configured (`~/.config/linux-whisper/config.yaml`)
- **LifeOS** running locally (default `http://127.0.0.1:8000`)
- `ffmpeg` for audio normalization
- Tailscale for phone → Linux access
- Kokoro TTS — see [ADR-003](docs/adr/003-kokoro-tts-bm-george.md)

### Autostart on boot (headless)

Set `DEPLOY_*` paths in `.env`, then install user systemd units and enable linger (starts at boot without a graphical login — same pattern as sibling services on a linger-enabled workstation):

```bash
bash scripts/install-autostart.sh
```

This enables `whisper-relay.service` (uvicorn on localhost) and `whisper-relay-tailscale.service` (Tailscale Serve proxy). Check status:

```bash
systemctl --user status whisper-relay whisper-relay-tailscale
journalctl --user -u whisper-relay -f
```

Manual steps only if you prefer:

```bash
bash scripts/install-systemd-user.sh
bash scripts/install-systemd-tailscale.sh
sudo loginctl enable-linger "$USER"   # once per machine
systemctl --user enable --now whisper-relay whisper-relay-tailscale
```

System-wide service alternative (set `DEPLOY_SYSTEMD_USER` in `.env`):

```bash
bash scripts/install-systemd.sh
sudo systemctl enable --now whisper-relay
```

## Documentation

**Contributing / AI agents:** start with [AGENTS.md](AGENTS.md) and [CLAUDE.md](CLAUDE.md).

| Document | Purpose |
|----------|---------|
| [docs/README.md](docs/README.md) | Documentation index |
| [docs/development-principles.md](docs/development-principles.md) | Engineering principles |
| [docs/specs/standards/code-conventions.md](docs/specs/standards/code-conventions.md) | Python and adapter conventions |
| [docs/specs/standards/testing-standards.md](docs/specs/standards/testing-standards.md) | Testing rules |
| [ADR-001](docs/adr/001-voice-transport-layer.md) | Voice transport layer — what whisper-relay is and is not |
| [ADR-002](docs/adr/002-upstream-integration-boundaries.md) | linux-whisper + LifeOS integration boundaries |
| [ADR-003](docs/adr/003-kokoro-tts-bm-george.md) | Kokoro TTS — `bm_george` voice |

## License

MIT
