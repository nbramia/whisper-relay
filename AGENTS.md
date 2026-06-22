# whisper-relay — Agent Reference

> **Audience:** All AI coding agents (Claude Code, Cursor, GitHub Copilot, etc.)
> **Status:** Complete
> **Last Updated:** 2026-06-18

whisper-relay is a **voice transport layer** for **LifeOS**. It turns speech into text via **linux-whisper**, submits that text to LifeOS exactly as web chat or Telegram would, then speaks LifeOS's response back to a mobile browser.

**What it is:** a client surface of LifeOS — like `web/index.html` or `api/services/telegram.py`.

**What it is not:** an agent, an orchestrator, or a second copy of LifeOS tools.

---

## Key Concepts

Details live in ADRs — do not duplicate here.

- **Transport layer** → [ADR-001](docs/adr/001-voice-transport-layer.md)
- **linux-whisper + LifeOS integration** → [ADR-002](docs/adr/002-upstream-integration-boundaries.md)
- **TTS** → [ADR-003](docs/adr/003-kokoro-tts-bm-george.md)
- **Invariants & boundaries** → sections below

## Documentation

Rules in [docs/AGENTS.md](docs/AGENTS.md) are mandatory. Navigation:

| Question | Document |
|----------|----------|
| Why does this project exist? | [README.md](README.md) |
| Why transport layer, not agent? | [ADR-001](docs/adr/001-voice-transport-layer.md) |
| How do we call linux-whisper and LifeOS? | [ADR-002](docs/adr/002-upstream-integration-boundaries.md) |
| LifeOS vs Agent backend toggle | [ADR-004](docs/adr/004-dual-text-backends.md) |
| LifeOS-owned client + reverse proxy | [ADR-005](docs/adr/005-lifeos-owned-chat-client.md) (Proposed) |
| Development principles (source) | [docs/development-principles.md](docs/development-principles.md) |
| Python code conventions | [docs/specs/standards/code-conventions.md](docs/specs/standards/code-conventions.md) |
| Testing standards | [docs/specs/standards/testing-standards.md](docs/specs/standards/testing-standards.md) |
| What to implement next? | Repository issue tracker |

Principles are adapted from internal engineering notes. Curated copy: [docs/development-principles.md](docs/development-principles.md).

---

## Development Principles

[docs/development-principles.md](docs/development-principles.md) — generic engineering process for this repo.

---

## Boundaries

| Tier | Rule |
|------|------|
| **Always** | Run full test suite before commit; structured logging (`logging`, not `print`); adapter protocols for STT / LifeOS / TTS; HTTP-only LifeOS integration (no `import lifeos`); mock GPU/STT/LifeOS/TTS in default tests; synthetic data in tests and docs |
| **Ask first** | New `pyproject.toml` dependencies; changes to adapter protocol signatures; LifeOS API contract assumptions; binding beyond localhost; schema changes to turn storage |
| **Never** | Add agent tools or orchestrator logic to whisper-relay; disable linux-whisper polish for gateway transcriptions; import LifeOS as a Python dependency; commit secrets; log real transcripts at INFO; block LifeOS handoffs locally; force-push main; skip hooks (`--no-verify`) |

---

## Critical Invariants

These are structural — violations are bugs, not style nits:

1. **Transport only** — whisper-relay never runs `agent_loop`, never defines tools, never classifies intent.
2. **LifeOS client parity** — text in and SSE handling out must match web chat / Telegram semantics.
3. **STT desktop parity** — linux-whisper polish pipeline on; same config as desktop app.
4. **Adapter seams** — STT, LifeOS, and TTS are swappable behind protocols; turn pipeline wires them only.
5. **Warm STT singleton** — GPU model stays loaded across requests; don't cold-start per turn.
6. **Localhost bind** — service listens on `127.0.0.1`; Tailscale Serve exposes externally.
7. **Voice data privacy** — structured logs use `turn_id`; transcript/response text stays in turn files or DEBUG logs.

---

## Project State

| Component | Status |
|-----------|--------|
| FastAPI service | Implemented |
| Adapters (STT / LifeOS / Agent / TTS) | Implemented |
| Voice turn API | Implemented |
| Mobile web UI | Implemented |

**Stack (planned):** Python 3.12+, FastAPI, uvicorn, httpx, pydantic-settings, ffmpeg (system), linux-whisper (editable dep), LifeOS (HTTP only).

**Default port:** `9788` (override with `VOICE_GATEWAY_PORT` in `.env`). LifeOS reads `VOICE_GATEWAY_URL=http://127.0.0.1:9788` for reverse proxy — see [ADR-005](docs/adr/005-lifeos-owned-chat-client.md).

**Sibling repos (local checkout):**

- `linux-whisper` — STT + polish (editable install from sibling directory)
- `LifeOS` — orchestrator (`http://127.0.0.1:8000`)
- `agents` — OpenClaw voice-adapter for Agent mode (`http://127.0.0.1:8100`, see ADR-004)

**Common commands (once implemented):**

```bash
pip install -e ".[dev]"
pip install -e ../linux-whisper
ruff check src tests && ruff format --check src tests
pytest
uvicorn voice_gateway.main:app --host 127.0.0.1 --port 9788
```

---

## Related Documents

- [README.md](README.md) — project overview
- [docs/AGENTS.md](docs/AGENTS.md) — documentation standards
- [docs/adr/001-voice-transport-layer.md](docs/adr/001-voice-transport-layer.md)
- [docs/adr/002-upstream-integration-boundaries.md](docs/adr/002-upstream-integration-boundaries.md)
- [docs/adr/003-kokoro-tts-bm-george.md](docs/adr/003-kokoro-tts-bm-george.md)
- [docs/development-principles.md](docs/development-principles.md)
