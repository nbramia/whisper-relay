# ADR-007: Explicit turn cancellation instead of stream abandonment

**Status:** Complete
**Last Updated:** 2026-08-21
**Decision:** Accepted (whisper-relay #32 → #37, LifeOS #611/#616)

## Context

This gateway cancelled a LifeOS turn by **abandoning the SSE stream**: `consume_ask_sse_stream` closed the response and raised `LifeOSCancelled` when the cancel event was set. Barge-in ("stop — never mind") and hangup looked identical from LifeOS's side, and both stopped the work, because a turn's lifetime was owned by its HTTP connection.

LifeOS #611 moved turn lifetime to the server: a client that disconnects mid-response no longer kills the turn, which runs to completion and persists. That fixes turns being silently lost when a tab closes — every surface except this one.

For voice, the same change inverts the meaning of our cancel gesture. Abandoning the stream would stop the *listening* but not the *turn*: every barge-in would run to completion and bill for a reply the user interrupted on purpose, while this service still reported `cancelled` to its client. Voice is the only surface where interrupting mid-answer is a normal, frequent interaction rather than an accident, so this is the common path, not an edge case.

LifeOS gated `modality == "voice"` out of detachment to hold the line until this side could state intent explicitly. The gate is safe indefinitely, but while it holds, voice keeps losing turns on hangup — the very loss #611 fixes elsewhere.

## Decision

**Cancellation is stated, not inferred.** On cancel, whisper-relay calls LifeOS's explicit cancel endpoint; abandoning the stream stays as-is and remains harmless.

### The key is our own turn id

`run_turn_stream` already generates `turn_id = str(uuid4())` before any backend call, uses it as the `TurnRegistry` key, passes it to `ask()`, and exposes it as the path parameter of `POST /api/voice/turn/{turn_id}/cancel`. That same value is sent to LifeOS as `client_turn_id` and used to cancel:

| Call | Shape |
|------|-------|
| `POST {LIFEOS_BASE_URL}/api/ask/stream` | request body gains `client_turn_id` |
| `POST {LIFEOS_BASE_URL}/api/chat/cancel` | `{"client_turn_id": "<turn_id>"}` → `{ok, cancelled}` |

No new identifier, nothing to correlate, and a fresh UUID4 per turn so LifeOS's key-reuse semantics never apply.

**Why not key on `conversation_id`.** The first shape proposed for this used the conversation id. This service does not have one on a first turn: the request carries `conversation_id: None` and the real id arrives in an SSE frame. A barge-in before that frame lands would have had no key — and "start talking, immediately rephrase" is the most common voice interruption there is. LifeOS shipped `client_turn_id` and a second endpoint for exactly this reason; the conversation-keyed route still exists and this service does not use it.

**Why `cancelled: false` is success.** An unknown `client_turn_id` is indistinguishable from a turn that already finished, so the endpoint returns no 404 and `cancelled: false` means "nothing was in flight". That is a normal outcome of a race, not an error to surface.

### It fires from the route, not the read loop

The cancel flag is only checked between SSE lines, so a backend that goes quiet delays detection. The signal originates in `TurnRegistry.cancel()`, so the POST is issued from the cancel route — a turn with no reader attached is still cancelled promptly. LifeOS confirms cancelling while a reader is still attached is supported, with a subsequent disconnect as a clean no-op rather than a second finalize.

### It is best effort, and never changes the local answer

The local cancel has already succeeded by the time the POST runs. An unreachable backend, a 422, or a malformed response is logged (`turn_id` only) and swallowed: nothing here may turn a clean cancel into an error for the caller.

### LifeOS only

`explicit_cancel` joins `BackendCapabilities` ([ADR-006](006-hermes-third-text-backend.md)) — true for LifeOS, false for agent and hermes, which own their own cancel semantics. `TurnRegistry` records a turn's backend alongside its cancel event so the route can route the call; the shared SSE parser stays backend-agnostic. `client_turn_id` is a LifeOS field and is not sent to the other two, so context parity between LifeOS and hermes covers persona, modality, and model but deliberately stops short of the cancel key.

### Invariants preserved

1. **Transport only** — stating "stop this turn" is transport, not orchestration.
2. **HTTP-only LifeOS integration** — one more endpoint on the same client.
3. **Voice data privacy** — cancel logs carry `turn_id` and backend, never transcript text.
4. **No new dependencies.**

## Consequences

- Once a release carrying this is deployed, LifeOS can lift the `modality == "voice"` gate. Voice then gets correct barge-in **and** a turn that survives a hangup — today it has the first only, at the cost of the second.
- The gate must not be lifted before that deploy, or every barge-in silently bills to completion.
- A backend added later gets explicit cancel by declaring the capability and exposing `cancel_turn`, not by touching the pipeline.
- Cross-repo verification is against the shipped adapter, not against an issue: this endpoint's shape already changed once during design.

## Related Documents

- [002-upstream-integration-boundaries.md](002-upstream-integration-boundaries.md) — LifeOS HTTP surface this extends
- [001-voice-transport-layer.md](001-voice-transport-layer.md) — transport-only invariant
- [006-hermes-third-text-backend.md](006-hermes-third-text-backend.md) — the capability seam this reuses
- [nbramia/whisper-relay#37](https://github.com/nbramia/whisper-relay/issues/37) — this change
- [nbramia/LifeOS#611](https://github.com/nbramia/LifeOS/issues/611) — server-owned turn lifetime; adds `client_turn_id` and `/api/chat/cancel`
- [nbramia/LifeOS#616](https://github.com/nbramia/LifeOS/issues/616) — the voice gate and the conditions for lifting it
