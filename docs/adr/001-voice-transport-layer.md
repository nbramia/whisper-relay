# ADR-001: whisper-relay as a voice transport layer

**Status:** Accepted
**Last Updated:** 2026-06-18
**Decision:** Accepted

## Context

LifeOS already provides a capable agent harness: orchestration, tool use, memory, planning, Claude Code / Codex handoffs, and multiple input surfaces (web chat, Telegram, MCP). [linux-whisper](https://github.com/nbramia/linux-whisper) already provides high-quality local speech-to-text with a full polish pipeline on the same Linux workstation.

The missing piece is a way to use both from a phone: hold a button, speak, hear the answer. The temptation is to build a "voice agent" that embeds STT, reasoning, and TTS in one service. That would duplicate LifeOS capabilities, fork behavior from chat/Telegram, and create a second place to maintain tool definitions and routing logic.

## Decision

**whisper-relay is a voice transport layer, not an agent.**

It performs exactly three transformations:

1. **Speech → text** — via linux-whisper (STT + polish, desktop parity).
2. **Text → LifeOS** — submit the transcript to LifeOS HTTP APIs exactly as if the user had typed it in web chat or sent it via Telegram. LifeOS runs unchanged.
3. **LifeOS text → speech** — synthesize the response (and tool-status updates) to audio and return it to the mobile browser.

whisper-relay contains **zero** agent tool definitions, orchestrator logic, or routing classifiers. It is a **client surface** of LifeOS — analogous to `web/index.html` or `api/services/telegram.py` — not a peer service that reimplements LifeOS internals.

### Deployment model

- **Standalone repo** (`whisper-relay`), not `LifeOS/services/voice-gateway`. LifeOS `api/services/` holds in-process Python modules; whisper-relay is a separately runnable service with a clean HTTP boundary.
- **Bind localhost** (`127.0.0.1:8888`), expose via **Tailscale Serve** to the tailnet.
- **Phase 1 transport:** one utterance per `POST /api/voice/turn` — HTTP multipart upload, no WebRTC, no streaming STT, no continuous listening.

## Rationale

### Why not embed an agent in the gateway?

LifeOS's orchestrator already handles tool selection, multi-turn context, escalation, and engine handoffs. A voice-specific agent would:

- Diverge from chat/Telegram behavior over time.
- Duplicate 18+ tool definitions and their maintenance burden.
- Violate the principle that voice is just another input modality.

The user's spoken question should produce the same LifeOS behavior as the same text typed in chat.

### Why not re-host LifeOS machinery?

Early planning incorrectly treated "don't duplicate agent logic" as "block LifeOS from doing its normal thing" — e.g. refusing to call `/api/chat/handoff` on `claude_intent`. That was wrong.

Telegram and web chat don't run the orchestrator locally either. They POST to `/api/ask/stream`, consume SSE, and call LifeOS APIs when handoffs are needed. whisper-relay follows the same pattern. Calling `POST /api/chat/handoff` is **client behavior**, not re-hosting — LifeOS still owns spawn logic, session stores, and worker dispatch.

### Why a separate repo?

- **Independent deploy cycle** — voice transport can ship without a LifeOS release.
- **Clear boundary** — HTTP-only integration; no `import lifeos` coupling.
- **Minimal blast radius** — Tailscale-exposed voice endpoint is isolated from LifeOS's main process.

### Why speak status updates?

Orchestrator turns can take tens of seconds when tools run. Chat UI shows "Searching your calendar…" inline. Voice has no visual channel during processing, so tool-status SSE events are synthesized to short TTS clips — parity with what the user would see in chat, adapted for audio.

## Alternatives considered

### Voice agent framework (Vapi, Retell, LiveKit, OpenAI Realtime)

**Rejected.** Adds cloud dependency, cost, and a second agent runtime. Conflicts with local-first LifeOS and the goal of using existing STT + orchestrator infrastructure.

### Embed voice gateway inside LifeOS

**Rejected.** Couples deploy and muddies the "client surface" model. LifeOS already has many surfaces (web, Telegram, MCP); a separate process with HTTP boundaries is cleaner.

### WebRTC / streaming STT for Phase 1

**Rejected for Phase 1.** Significantly more complexity. Hold-to-talk with HTTP upload is sufficient to validate the full loop. Streaming can be a later phase.

### Gateway-side policy blocking coding/agent tasks

**Rejected.** Would make voice a second-class LifeOS surface. Handoffs go through `/api/chat/handoff` like web chat.

## Consequences

### Positive

- Single source of truth for agent behavior (LifeOS).
- Single source of truth for STT quality (linux-whisper).
- Voice parity with chat/Telegram improves over time as LifeOS improves — for free.
- Small, auditable codebase focused on audio I/O and HTTP client logic.

### Negative

- **Latency stack:** upload + STT + orchestrator + TTS is inherently slower than streaming solutions. Acceptable for Phase 1 push-to-talk.
- **Async handoffs:** Claude Code / Codex tasks may run for minutes. Voice can confirm the handoff was started; completion notifications still flow through LifeOS's existing channels (Telegram, `/agents` UI) unless we add voice-specific notification later.
- **Three services to run:** LifeOS, linux-whisper models loaded, whisper-relay. Operational overhead is modest on a always-on workstation.

## Related Documents

- [ADR-003: Kokoro TTS with bm_george](003-kokoro-tts-bm-george.md)
- [Development principles](../development-principles.md)
- [AGENTS.md](../../AGENTS.md) — project constitution
- [GitHub epic #1](https://github.com/nbramia/whisper-relay/issues/1)
