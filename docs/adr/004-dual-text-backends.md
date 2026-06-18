# ADR-004: Dual text backends (LifeOS + OpenClaw voice-adapter)

**Status:** Accepted
**Last Updated:** 2026-06-19
**Decision:** Accepted

## Context

whisper-relay was originally a LifeOS-only client surface ([ADR-001](001-voice-transport-layer.md), [ADR-002](002-upstream-integration-boundaries.md)). The mobile UI now supports a **LifeOS | Agent** toggle: the same STT/TTS pipeline can submit transcripts to either LifeOS or the OpenClaw **voice-adapter** in the [agents](https://github.com/nbramia/agents) repo.

voice-adapter exposes a LifeOS-compatible SSE subset (`POST /api/ask/stream`) and owns session lifecycle, auto-escalation (local Gemma → Claude/GPT), and conversation storage. whisper-relay must not reimplement that logic.

## Decision

**whisper-relay routes voice turns to one of two HTTP text backends**, selected per request via `backend=lifeos|agent` (default `lifeos`).

| Backend | URL (env) | Role |
|---------|-----------|------|
| LifeOS | `LIFEOS_BASE_URL` | Full orchestrator + `claude_intent` handoffs |
| Agent | `AGENT_BACKEND_URL` | voice-adapter → OpenClaw managed agents |

Both backends implement the same client protocol surface:

- `ask(question, *, conversation_id, turn_id, on_status, cancel) -> LifeOSResult`
- `list_conversations()` / `get_conversation(id)` for the Chats sidebar

Implementation:

- `TextBackendRouter` selects the client from the per-request `backend` field.
- `HTTPLifeOSClient` — unchanged LifeOS semantics including handoff.
- `HTTPAgentBackendClient` — same SSE parser, no handoff path; optional `AGENT_BACKEND_TOKEN` bearer auth.
- Mobile UI stores **separate `conversation_id` values** per backend in `sessionStorage`.

### Invariants preserved

1. **Transport only** — no agent tools, escalation rules, or orchestrator session management in whisper-relay.
2. **HTTP-only agents integration** — no Python import of agents/openclaw packages.
3. **Adapter seam** — STT and TTS unchanged; only the text-backend client swaps.
4. **Voice data privacy** — structured logs use `turn_id`; no transcript text at INFO.

### Deployment

- LifeOS: `http://127.0.0.1:8000` (unchanged).
- voice-adapter: `docker compose --profile voice up` in agents repo; default `http://127.0.0.1:8100`.
- Set `AGENT_BACKEND_URL` in whisper-relay `.env` when Agent mode is used.

Disable Agent routing without removing code: `AGENT_BACKEND_ENABLED=false`.

## Consequences

- README and AGENTS.md document both backends and the UI toggle.
- `/health/backends` reports reachability of LifeOS and voice-adapter (no transcript data).
- LifeOS handoffs do not apply in Agent mode; OpenClaw escalation is entirely in voice-adapter.
- Future third backends would add another client + router entry, not inline pipeline logic.

## Related Documents

- [001-voice-transport-layer.md](001-voice-transport-layer.md) — transport-layer invariant
- [002-upstream-integration-boundaries.md](002-upstream-integration-boundaries.md) — LifeOS HTTP client
- [../AGENTS.md](../AGENTS.md) — project agent reference
- [nbramia/agents#64](https://github.com/nbramia/agents/issues/64) — voice-adapter HTTP bridge
- [nbramia/agents#66](https://github.com/nbramia/agents/issues/66) — LifeOS-shaped conversation API
- [nbramia/whisper-relay#16](https://github.com/nbramia/whisper-relay/issues/16) — whisper-relay implementation
