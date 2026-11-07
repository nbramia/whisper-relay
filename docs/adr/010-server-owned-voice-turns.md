# ADR-010: Server-owned voice turns

**Status:** Complete
**Last Updated:** 2026-11-07
**Decision:** Accepted

## Context

A voice message must reach LifeOS even when the user closes the page right after sending it. LifeOS already owns chat turn lifetime on the server ([ADR-007](007-explicit-turn-cancellation.md)); the gateway's own pipeline (normalize audio, STT, text backend, TTS, meta) must do the same, or a mobile disconnect kills the turn before the message is delivered.

## Decision

**A turn is a server-owned asyncio task; the SSE response only reads from it.**

- `POST /api/voice/turn/stream` hands `TurnPipeline.run_turn_stream` to `DetachedTurnRunner.start`, which iterates it in its own task and writes each event into a bounded buffer (`DetachedTurn`). The `StreamingResponse` iterates `DetachedTurn.reader()`.
- Closing the reader (a client disconnect) detaches without cancelling the task. The turn runs STT, the text backend (which persists the conversation), TTS, and `write_meta`, so `GET /api/voice/audio/{turn_id}` serves the clip afterwards.
- The producer never blocks on the buffer. When it is full, the oldest non-terminal frame is dropped, so `done`/`error`/`cancelled` and the end-of-stream marker always land, whether the reader is late, gone, or stalled.
- SSE event shapes and ordering for a connected client are unchanged.

### Cancellation

Barge-in and hangup still use `POST /api/voice/turn/{turn_id}/cancel` and the `TurnRegistry` event, which the pipeline and the backend call observe whether or not a reader is attached. Supersede and barge-in semantics are unchanged.

### Bounds

- **Lifetime:** a turn is cancelled after `VOICE_GATEWAY_DECODE_TIMEOUT_S + VOICE_GATEWAY_STT_TIMEOUT_S + max(LIFEOS_TIMEOUT_S, AGENT_BACKEND_TIMEOUT_S, HERMES_BACKEND_TIMEOUT_S)`, the sum of the per-stage caps. A connected reader receives an `error` event with status 504.
- **Teardown:** when a turn's generator is closed, any in-flight text backend call is cancelled and awaited (bounded) too.
- **Shutdown:** the app lifespan cancels and awaits every running turn.

## Consequences

- A turn that outlives its client leaves its result in turn storage and in the LifeOS conversation; the client picks it up from the conversation history.
- Unexpected pipeline exceptions surface to a connected client as an `error` event with status 500 instead of an aborted stream.

## Related Documents

- [007-explicit-turn-cancellation.md](007-explicit-turn-cancellation.md) — explicit cancel, which this builds on
- [001-voice-transport-layer.md](001-voice-transport-layer.md) — transport-only invariant
