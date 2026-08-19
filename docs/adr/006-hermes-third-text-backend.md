# ADR-006: Hermes as a third text backend with context parity

**Status:** Complete
**Last Updated:** 2026-08-19
**Decision:** Accepted (whisper-relay #32)

## Context

[ADR-004](004-dual-text-backends.md) established two text backends — the LifeOS orchestrator and the OpenClaw voice-adapter — and anticipated this change: "Future third backends would add another client + router entry, not inline pipeline logic."

LifeOS's `/chat` client is adopting **Hermes** as its default assistant. The gateway had no way to address it, so voice turns could not follow the client to its new default.

The agent backend was deliberately built context-poor: turns routed to it carry no persona selection, no signal that the reply will be spoken, and no per-turn model choice. voice-adapter owns its own session lifecycle, escalation, and formatting, so that was the right trade for a secondary assistant behind a toggle. It is the wrong trade for the assistant that answers by default — a spoken turn would lose the persona's speech-formatting rules and be read aloud as screen-formatted prose.

The backend selector was also effectively binary: `normalize_backend()` matched `agent` exactly and let everything else fall through to `lifeos`. A typo, or a backend configured in the client but not in the gateway, routed the turn to the wrong assistant and reported success.

## Decision

**whisper-relay routes voice turns to one of three HTTP text backends**, selected per request via `backend=lifeos|agent|hermes`. The gateway default stays `lifeos`; the client selects per request.

| Backend | URL (env) | Role |
|---------|-----------|------|
| LifeOS | `LIFEOS_BASE_URL` | Full orchestrator + `claude_intent` handoffs |
| Agent | `AGENT_BACKEND_URL` | voice-adapter → OpenClaw managed agents |
| Hermes | `HERMES_BACKEND_URL` | Hermes assistant, default in LifeOS `/chat` |

### Per-backend context capabilities

Per-turn context is a function of the backend, resolved once via `capabilities_for()` in `adapters/text_backend.py` — not scattered string comparisons in the pipeline.

| Backend | `persona_id` | `modality` | `model_override` | Handoff parsing |
|---------|--------------|------------|------------------|-----------------|
| LifeOS | ✅ | ✅ `voice` | ✅ | ✅ (persona capability or explicit engine pick) |
| Agent | ❌ | ❌ | ❌ | ❌ |
| Hermes | ✅ | ✅ `voice` | ✅ | ❌ |

- **Hermes has context parity with LifeOS** on persona, modality, and model. The gateway **forwards** all three and resolves none of them — [ADR-001](001-voice-transport-layer.md)'s transport-only invariant holds. `persona_id` defaults to `primary` when the client sends none, exactly as for LifeOS.
- **Handoff parsing stays off for Hermes.** Engine handoff is a LifeOS-orchestrator concept and Hermes has its own delegation posture. This is a deliberate decision for this backend, not a default inherited from the non-LifeOS branch: it stays off regardless of the persona's capabilities or an explicit `claude_code`/`codex` model pick.
- **The agent backend is unchanged.** Its context-poor behavior is deliberate; widening it requires its own ADR.

### Backend normalization

`normalize_backend()` resolves all three known values explicitly (case-insensitive, surrounding whitespace ignored). An unrecognized value still resolves to `lifeos`, preserving behavior for existing clients.

### Settings

`HERMES_BACKEND_URL` (default `http://127.0.0.1:8200`), `HERMES_BACKEND_TIMEOUT_S` (300s, matching the other backends), `HERMES_BACKEND_TOKEN` (optional bearer), `HERMES_BACKEND_ENABLED` (default true) — mirroring the `AGENT_BACKEND_*` quartet.

`HTTPHermesBackendClient` reuses `consume_ask_sse_stream` from `adapters/lifeos.py` rather than reimplementing the parser, so the transcription, synthesis, playback, and cancellation stages are untouched. Cancellation still works by closing the response stream.

### Invariants preserved

1. **Transport only** — no agent tools, escalation rules, or orchestrator session management; `persona_id` is forwarded, never interpreted.
2. **Adapter seam** — STT and TTS unchanged; only the text-backend client swaps.
3. **No new dependencies.**
4. **Voice data privacy** — structured logs use `turn_id`; no transcript text at INFO.

## Consequences

- `/health/backends` reports reachability for all three backends.
- Conversation threads stay separate per backend (`conversation_id` is backend-scoped, as in ADR-004).
- **Spoken status depends on the backend.** Synthesis produces one whole-utterance clip after the backend returns, and `status` events are the only thing that generates audio mid-turn. There is no timer or heartbeat fallback, so a backend emitting no `status` events leaves the listener in silence for the whole turn. That is an expectation on the Hermes adapter, not something this service compensates for.
- The Hermes-side service terminating this contract lives in `nbramia/hermes`; it must speak the same SSE event set (`conversation_id`, `status`, `content`, `error`, `done`).
- A fourth backend follows the same shape: a client, a router entry, and a capabilities row.

## Related Documents

- [001-voice-transport-layer.md](001-voice-transport-layer.md) — transport-only invariant
- [002-upstream-integration-boundaries.md](002-upstream-integration-boundaries.md) — LifeOS HTTP client boundaries
- [004-dual-text-backends.md](004-dual-text-backends.md) — the two-backend decision this extends
- [005-lifeos-owned-chat-client.md](005-lifeos-owned-chat-client.md) — LifeOS owns the client surface
- [nbramia/whisper-relay#32](https://github.com/nbramia/whisper-relay/issues/32) — this change
- [nbramia/whisper-relay#27](https://github.com/nbramia/whisper-relay/issues/27) — modality passthrough
- [nbramia/whisper-relay#24](https://github.com/nbramia/whisper-relay/issues/24) — model_override passthrough
