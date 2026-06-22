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

- `ask(question, *, conversation_id, turn_id, on_status, cancel, persona_id?, model_override?, parse_handoff?) -> LifeOSResult`
- `list_conversations(*, persona_id?)` / `get_conversation(id)` for the Chats sidebar
- LifeOS only: `list_personas()` for persona discovery

`model_override` is forwarded to LifeOS `/api/ask/stream` when set (omitted for `auto`/empty). Unknown values are passed through; LifeOS falls back server-side.

**Explicit engine handoff:** when `model_override` is `claude_code` or `codex`, whisper-relay sets `parse_handoff=True` even if the persona lacks the `handoff` capability — the user explicitly chose an engine path. Inferred handoffs (orchestrator-emitted `claude_intent` without an engine pick) still follow persona `capabilities`.

Implementation:

- `TextBackendRouter` selects the client from the per-request `backend` field.
- `HTTPLifeOSClient` — unchanged LifeOS semantics including handoff.
- `HTTPAgentBackendClient` — same SSE parser, no handoff path; optional `AGENT_BACKEND_TOKEN` bearer auth.
- Mobile UI stores **separate `conversation_id` values** per backend in `sessionStorage`.
- **LifeOS mode only:** persona and conversation listing live in LifeOS `/chat`; voice turns send `persona_id` and `model_override` through the gateway. Engine handoffs follow persona `capabilities` unless the user explicitly picks `claude_code`/`codex` ([issue #24](https://github.com/nbramia/whisper-relay/issues/24)).

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
- [nbramia/LifeOS#351](https://github.com/nbramia/LifeOS/issues/351) — HTTP persona discovery + `persona_id`
- [nbramia/whisper-relay#19](https://github.com/nbramia/whisper-relay/issues/19) — voice UI persona selector
