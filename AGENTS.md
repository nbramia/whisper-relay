# whisper-relay — Agent Reference

> **Audience:** All AI coding agents (Claude Code, Cursor, GitHub Copilot, etc.)
> **Status:** Complete
> **Last Updated:** 2026-06-18

whisper-relay is a **voice transport API** for **LifeOS**, **Hermes**, and optional **OpenClaw Agent** mode. LifeOS responsive `/chat` is the client surface ([ADR-005](docs/adr/005-lifeos-owned-chat-client.md)); this repo exposes the voice turn API behind LifeOS's reverse proxy.

**What it is:** voice transport behind LifeOS — like `api/routes/voice.py` proxied to localhost.

**What it is not:** an agent, an orchestrator, a chat UI, or a second copy of LifeOS tools.

---

## Key Concepts

Details live in ADRs — do not duplicate here.

- **Transport layer** → [ADR-001](docs/adr/001-voice-transport-layer.md)
- **linux-whisper + LifeOS integration** → [ADR-002](docs/adr/002-upstream-integration-boundaries.md)
- **TTS** → [ADR-003](docs/adr/003-kokoro-tts-bm-george.md)
- **Third backend (Hermes) + context capabilities** → [ADR-006](docs/adr/006-hermes-third-text-backend.md)
- **Turn cancellation** → [ADR-007](docs/adr/007-explicit-turn-cancellation.md)
- **Turn lifetime (detached from the client connection)** → [ADR-010](docs/adr/010-server-owned-voice-turns.md)
- **Per-tenant backend routing** → [ADR-008](docs/adr/008-per-tenant-backend-routing.md)
- **Invariants & boundaries** → sections below

## Documentation

Rules in [docs/AGENTS.md](docs/AGENTS.md) are mandatory. Navigation:

| Question | Document |
|----------|----------|
| Why does this project exist? | [README.md](README.md) |
| Why transport layer, not agent? | [ADR-001](docs/adr/001-voice-transport-layer.md) |
| How do we call linux-whisper and LifeOS? | [ADR-002](docs/adr/002-upstream-integration-boundaries.md) |
| LifeOS vs Agent backend toggle | [ADR-004](docs/adr/004-dual-text-backends.md) |
| Hermes backend + per-backend context capabilities | [ADR-006](docs/adr/006-hermes-third-text-backend.md) |
| How is a turn cancelled (barge-in, hangup)? | [ADR-007](docs/adr/007-explicit-turn-cancellation.md) |
| How does one process serve more than one person? | [ADR-008](docs/adr/008-per-tenant-backend-routing.md) |
| LifeOS-owned client + reverse proxy | [ADR-005](docs/adr/005-lifeos-owned-chat-client.md) (Accepted) |
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
| Adapters (STT / LifeOS / Agent / Hermes / TTS) | Implemented |
| Voice turn API | Implemented |
| Client UI | **LifeOS `/chat`** (whisper-relay `static/` removed — #21) |

**Stack (planned):** Python 3.12+, FastAPI, uvicorn, httpx, pydantic-settings, ffmpeg (system), linux-whisper (editable dep), LifeOS (HTTP only).

**Backends:** `backend=lifeos|agent|hermes` per request (default `lifeos`). Persona, `modality=voice`, and `model_override` are forwarded to LifeOS and Hermes; the agent backend stays context-poor by design ([ADR-006](docs/adr/006-hermes-third-text-backend.md)).

**Default port:** `9788` (override with `VOICE_GATEWAY_PORT` in `.env`). LifeOS reads `VOICE_GATEWAY_URL=http://127.0.0.1:9788` for reverse proxy — see [ADR-005](docs/adr/005-lifeos-owned-chat-client.md).

**Sibling repos (local checkout):**

- `linux-whisper` — STT + polish (editable install from sibling directory)
- `LifeOS` — orchestrator (`http://127.0.0.1:8000`)
- `agents` — OpenClaw voice-adapter for Agent mode (`http://127.0.0.1:8100`, see ADR-004)
- `hermes` — Hermes assistant for Hermes mode (`http://127.0.0.1:8790` — the adapter's own default port, see ADR-006)

**Common commands (once implemented):**

```bash
pip install -e ".[dev]"
pip install -e ../linux-whisper
ruff check src tests && ruff format --check src tests
pytest
uvicorn voice_gateway.main:app --host 127.0.0.1 --port 9788
```

## Workflow

- Use plan mode for non-trivial tasks (3+ files, adapter boundary changes, unclear requirements).
- Read [ADR-001](docs/adr/001-voice-transport-layer.md), [ADR-002](docs/adr/002-upstream-integration-boundaries.md), and [ADR-004](docs/adr/004-dual-text-backends.md) before adapter or pipeline work.
- After modifying docs, verify compliance with [docs/AGENTS.md](docs/AGENTS.md).
- When creating new modules under `src/voice_gateway/`, check if an `AGENTS.md` is warranted (3+ files or distinct rules).

## Skills

Global skills and commands:

| Skill | Purpose |
|-------|---------|
| `/draft-issue` | Create GitHub issues with machine-testable acceptance criteria |
| `/implement` | Build with subagents, adversarial review, verification |
| `ship <pr>` | Wait for checks, merge, clean up, watch the deploy |

## Escalation Rules

Stop and ask a human before proceeding if any of these apply:

| Trigger | Why |
|---------|-----|
| Adding agent tools, intent classification, or orchestrator logic | Violates transport-layer invariant ([ADR-001](docs/adr/001-voice-transport-layer.md)) |
| Disabling linux-whisper polish or gateway-specific STT overrides | Breaks desktop parity ([ADR-002](docs/adr/002-upstream-integration-boundaries.md)) |
| Importing LifeOS or linux-whisper internals beyond public adapter surfaces | Breaks deploy boundary; couple repos |
| Changing `STTAdapter`, `LifeOSClient`, or `TTSAdapter` protocol signatures | Affects all backends simultaneously |
| Adding a dependency to `pyproject.toml` | GPU/shared-lib conflicts are real (see linux-whisper ROCm isolation) |
| Selecting or changing TTS voice/backend | Requires ADR — see [ADR-003](docs/adr/003-kokoro-tts-bm-george.md) |
| Blocking `claude_intent` / handoffs locally instead of calling `/api/chat/handoff` | Breaks LifeOS client parity (LifeOS mode only; Agent mode uses voice-adapter escalation per [ADR-004](docs/adr/004-dual-text-backends.md)) |
| Logging transcript or response text at INFO in production paths | Voice data is personal |
| Acceptance criteria are ambiguous or untestable | Wastes implementation effort |

## Latency Awareness

Voice turns are user-perceived end-to-end. When touching the pipeline, be aware of typical budgets (GPU path):

| Stage | Target |
|-------|--------|
| ffmpeg normalize | < 100ms |
| STT + polish (linux-whisper) | ~300–500ms |
| LifeOS orchestrator | 2–30s (tool-dependent) |
| TTS (Kokoro `bm_george`, per clip) | TBD — benchmark on target hardware |

Don't add synchronous work on the hot path without justification. CPU-bound stages belong in `asyncio.to_thread()`.

## Common Mistakes

1. **Building an agent in whisper-relay** → submit text to LifeOS; LifeOS reasons. See [ADR-001](docs/adr/001-voice-transport-layer.md).
2. **Raw STT without polish** → use full `PolishPipeline` with desktop config. See [ADR-002](docs/adr/002-upstream-integration-boundaries.md).
3. **Importing `lifeos` Python package** → HTTP client only (`/api/ask/stream`, `/api/chat/handoff`).
4. **Spoken fallback on `claude_intent` instead of handoff** → call `/api/chat/handoff` like `LifeOS/web/index.html`.
5. **Cold-starting STT per request** → keep warm singleton engine across turns.
6. **Modifying an accepted ADR** → ADRs are append-only; write a new superseding ADR.
7. **Putting task lists in ADRs or specs** → tasks live in GitHub issues.
8. **Tests that require GPU, LifeOS running, or real TTS** → mock adapters; mark `@pytest.mark.integration`.
9. **Logging full transcripts at INFO** → log `turn_id` + timings; text at DEBUG or in turn storage only.
10. **Deleting or weakening a failing test to unblock** → your code is wrong until proven otherwise ([testing standards](docs/specs/standards/testing-standards.md)).

## Quick Reference

```bash
pip install -e ".[dev]"
pip install -e ../linux-whisper
ruff check src tests
pytest
uvicorn voice_gateway.main:app --host 127.0.0.1 --port 9788
```

LifeOS must be running separately: `http://127.0.0.1:8000/health/full`

---

## Related Documents

- [README.md](README.md) — project overview
- [docs/AGENTS.md](docs/AGENTS.md) — documentation standards
- [docs/adr/001-voice-transport-layer.md](docs/adr/001-voice-transport-layer.md)
- [docs/adr/002-upstream-integration-boundaries.md](docs/adr/002-upstream-integration-boundaries.md)
- [docs/adr/003-kokoro-tts-bm-george.md](docs/adr/003-kokoro-tts-bm-george.md)
- [docs/adr/006-hermes-third-text-backend.md](docs/adr/006-hermes-third-text-backend.md)
- [docs/adr/007-explicit-turn-cancellation.md](docs/adr/007-explicit-turn-cancellation.md)
- [docs/adr/008-per-tenant-backend-routing.md](docs/adr/008-per-tenant-backend-routing.md)
- [docs/adr/010-server-owned-voice-turns.md](docs/adr/010-server-owned-voice-turns.md)
- [docs/development-principles.md](docs/development-principles.md)
