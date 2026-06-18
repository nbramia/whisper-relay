# whisper-relay — Agent Reference

> **Audience:** All AI coding agents (Claude Code, Cursor, GitHub Copilot, etc.)
> **Status:** Complete
> **Last Updated:** 2026-06-18

whisper-relay is a **voice transport layer** for [LifeOS](https://github.com/nbramia/LifeOS). It turns speech into text via [linux-whisper](https://github.com/nbramia/linux-whisper), submits that text to LifeOS exactly as web chat or Telegram would, then speaks LifeOS's response back to a mobile browser.

**What it is:** a client surface of LifeOS — like `web/index.html` or `api/services/telegram.py`.

**What it is not:** an agent, an orchestrator, or a second copy of LifeOS tools.

---

## Key Concepts

- **Transport layer:** speech → text → LifeOS → text → speech. No reasoning in between.
- **Adapter boundaries:** `STTAdapter` (linux-whisper), `LifeOSClient` (HTTP SSE), `TTSAdapter` (TBD). See [ADR-002](docs/adr/002-upstream-integration-boundaries.md).
- **LifeOS parity:** submit to `POST /api/ask/stream`; on `claude_intent`, call `POST /api/chat/handoff` — same as web chat. LifeOS owns all agent behavior.
- **STT parity:** full linux-whisper polish pipeline, same `config.yaml` as the desktop dictation app.
- **One turn per request:** Phase 1 is hold-to-talk HTTP multipart upload — no WebRTC, no streaming STT.
- **Sensitive data:** voice transcripts and responses are personal. Log `turn_id` and timings at INFO; full text only at DEBUG or in per-turn storage files.

## Documentation

Rules in [docs/AGENTS.md](docs/AGENTS.md) are mandatory. Navigation:

| Question | Document |
|----------|----------|
| Why does this project exist? | [README.md](README.md) |
| Why transport layer, not agent? | [ADR-001](docs/adr/001-voice-transport-layer.md) |
| How do we call linux-whisper and LifeOS? | [ADR-002](docs/adr/002-upstream-integration-boundaries.md) |
| Development principles (source) | [docs/development-principles.md](docs/development-principles.md) |
| Python code conventions | [docs/specs/standards/code-conventions.md](docs/specs/standards/code-conventions.md) |
| Testing standards | [docs/specs/standards/testing-standards.md](docs/specs/standards/testing-standards.md) |
| What to implement next? | [GitHub issues](https://github.com/nbramia/whisper-relay/issues) |

Principles are adapted from personal Development principles notes at `~/Notes 2025/Development principles/` (LifeDB-derived system). Curated copy: [docs/development-principles.md](docs/development-principles.md).

---

## Development Principles

Full elaboration: [docs/development-principles.md](docs/development-principles.md). Summary:

1. **Think before acting** — surface tradeoffs; write ADRs before architectural decisions.
2. **Simplicity first** — minimum code for the request; no speculative abstractions.
3. **Surgical changes** — every changed line traces to the request.
4. **Goal-driven execution** — acceptance criteria are the contract; implement until they're met.
5. **Tests are sacred** — coverage only goes up; see testing standards.
6. **Privacy** — voice data is personal; never log transcripts at INFO; synthetic data in tests/docs.

---

## Boundaries

| Tier | Rule |
|------|------|
| **Always** | Run full test suite before commit; structured logging (`logging`, not `print`); adapter protocols for STT / LifeOS / TTS; HTTP-only LifeOS integration (no `import lifeos`); mock GPU/STT/LifeOS/TTS in default tests; synthetic data in tests and docs |
| **Ask first** | New `pyproject.toml` dependencies; changes to adapter protocol signatures; LifeOS API contract assumptions; TTS backend selection (requires ADR); binding beyond localhost; schema changes to turn storage |
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
| FastAPI service | Not started — [#2](https://github.com/nbramia/whisper-relay/issues/2) |
| Adapters (STT / LifeOS / TTS) | Not started — [#4](https://github.com/nbramia/whisper-relay/issues/4)–[#6](https://github.com/nbramia/whisper-relay/issues/6) |
| Voice turn API | Not started — [#7](https://github.com/nbramia/whisper-relay/issues/7) |
| Mobile web UI | Not started — [#9](https://github.com/nbramia/whisper-relay/issues/9) |
| TTS backend | **Deferred** — ADR pending |

**Stack (planned):** Python 3.12+, FastAPI, uvicorn, httpx, pydantic-settings, ffmpeg (system), linux-whisper (editable dep), LifeOS (HTTP only).

**Default port:** `8888` (8787 in use on target machine).

**Sibling repos (local):**

- `~/Code/linux-whisper` — STT + polish
- `~/Code/LifeOS` — orchestrator (`http://127.0.0.1:8000`)

**Common commands (once implemented):**

```bash
pip install -e ".[dev]"
pip install -e ../linux-whisper
ruff check src tests && ruff format --check src tests
pytest
uvicorn voice_gateway.main:app --host 127.0.0.1 --port 8888
```

---

## Related Documents

- [README.md](README.md) — project overview
- [docs/AGENTS.md](docs/AGENTS.md) — documentation standards
- [docs/adr/001-voice-transport-layer.md](docs/adr/001-voice-transport-layer.md)
- [docs/adr/002-upstream-integration-boundaries.md](docs/adr/002-upstream-integration-boundaries.md)
- [docs/development-principles.md](docs/development-principles.md)
