# whisper-relay

A voice transport layer for [LifeOS](https://github.com/nbramia/LifeOS) — push-to-talk from your phone, spoken answers back.

whisper-relay turns speech into text, hands that text to LifeOS exactly as if you had typed it in the web chat or sent it via Telegram, then speaks LifeOS's reply. It does not run an agent, duplicate LifeOS tools, or make routing decisions. LifeOS behaves the same regardless of whether input came from a keyboard, Telegram, or your voice.

## How it fits together

This project is designed to work alongside two other open-source repos:

| Repo | Role in the voice flow |
|------|------------------------|
| [**linux-whisper**](https://github.com/nbramia/linux-whisper) | Local speech-to-text. Transcribes and polishes utterances on the Linux box — same pipeline as the desktop dictation app. |
| [**LifeOS**](https://github.com/nbramia/LifeOS) | Personal agent harness. Receives the transcript via its existing chat API, runs the orchestrator (tools, memory, planning, agent spawns), and returns text responses. |
| **whisper-relay** (this repo) | Voice transport. Records audio from a mobile browser, normalizes it, calls linux-whisper for STT, submits text to LifeOS, synthesizes responses to speech, and serves audio back to the phone. |

```
phone browser (Chrome, hold-to-talk)
        │
        ▼
  whisper-relay          ← you are here
   ┌────────────┐
   │ ffmpeg     │  normalize webm/opus → 16 kHz mono
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

- Hold-to-talk from Chrome on a phone over Tailscale
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

Phase 1 implementation on branch `feat/voice-gateway-phase1`. Tracked in [GitHub issues](https://github.com/nbramia/whisper-relay/issues). Architecture decisions are in [`docs/adr/`](docs/adr/).

## Quick start

```bash
git clone https://github.com/nbramia/whisper-relay.git
cd whisper-relay
pip install -e ".[dev]"
pip install -e ../linux-whisper   # sibling checkout; GPU STT

# System deps (Ubuntu)
sudo apt install ffmpeg espeak-ng

# Kokoro TTS models (see ADR-003)
bash scripts/setup-kokoro.sh

# Copy env and adjust if needed
cp .env.example .env

# Run (default port 8888)
uvicorn voice_gateway.main:app --host 127.0.0.1 --port 8888

# Expose to tailnet (phone → Linux)
tailscale serve --bg --https=443 http://127.0.0.1:8888
```

Open the served URL on your phone in Chrome, hold the mic button, speak, release. Responses play back automatically.

For CI or local dev without Kokoro models, set `TTS_BACKEND=null` in `.env`.

## Prerequisites

- Linux workstation on your tailnet (GPU recommended for linux-whisper)
- [linux-whisper](https://github.com/nbramia/linux-whisper) installed and configured (`~/.config/linux-whisper/config.yaml`)
- [LifeOS](https://github.com/nbramia/LifeOS) running locally (default `http://127.0.0.1:8000`)
- `ffmpeg` for audio normalization
- Tailscale for phone → Linux access
- Kokoro TTS — see [ADR-003](docs/adr/003-kokoro-tts-bm-george.md)

### systemd (optional)

```bash
sudo cp deploy/whisper-relay.service /etc/systemd/system/
sudo systemctl enable --now whisper-relay
```

```bash
sudo cp deploy/whisper-relay.service /etc/systemd/system/
sudo systemctl enable --now whisper-relay
```

## Documentation

**Contributing / AI agents:** start with [AGENTS.md](AGENTS.md) and [CLAUDE.md](CLAUDE.md).

| Document | Purpose |
|----------|---------|
| [docs/README.md](docs/README.md) | Documentation index |
| [docs/development-principles.md](docs/development-principles.md) | Engineering principles (adapted from personal Development principles notes) |
| [docs/specs/standards/code-conventions.md](docs/specs/standards/code-conventions.md) | Python and adapter conventions |
| [docs/specs/standards/testing-standards.md](docs/specs/standards/testing-standards.md) | Testing rules |
| [ADR-001](docs/adr/001-voice-transport-layer.md) | Voice transport layer — what whisper-relay is and is not |
| [ADR-002](docs/adr/002-upstream-integration-boundaries.md) | linux-whisper + LifeOS integration boundaries |
| [ADR-003](docs/adr/003-kokoro-tts-bm-george.md) | Kokoro TTS — `bm_george` voice |

## License

MIT
