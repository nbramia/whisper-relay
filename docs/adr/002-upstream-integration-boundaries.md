# ADR-002: Upstream integration boundaries (linux-whisper + LifeOS)

**Status:** Accepted
**Last Updated:** 2026-06-18
**Decision:** Accepted

## Context

whisper-relay sits between a phone browser and two existing systems:

1. **linux-whisper** — local STT on the Linux workstation. The desktop app captures mic audio, transcribes via whisper.cpp (GPU), runs a four-stage polish pipeline, and injects text at the cursor.
2. **LifeOS** — personal agent harness. Web chat and Telegram submit text to `POST /api/ask/stream`; LifeOS runs the orchestrator, tools, and engine handoffs.

whisper-relay must integrate with both without forking their behavior. Several integration choices were debated during planning (polish on/off, handoff blocking, HTTP vs library import). This ADR records the accepted boundaries.

## Decision

### linux-whisper: STT + full polish, desktop parity

**Input to whisper-relay:** normalized 16 kHz mono PCM (from ffmpeg; see below).

**STT path:** import `linux_whisper` as a Python library — `create_engine(config)` → `STTEngine` protocol (`start_stream` → `feed_audio` → `finalize`). Keep a **warm singleton engine** in the whisper-relay process (GPU model load is ~10–15s cold).

**Polish path:** run the full `PolishPipeline` with the **same `~/.config/linux-whisper/config.yaml`** the desktop app uses. Do not disable polish or apply gateway-specific overrides.

| Stage | Purpose |
|-------|---------|
| 4a Disfluency | Remove fillers, repetitions |
| 4b Punctuation | Capitalization, punctuation |
| 4d Formatting | Spoken numbers/dates → written form |
| 4c LLM (conditional) | Resolve self-corrections |

**Rationale:** The transcript whisper-relay sends to LifeOS must be the same text the desktop app would produce for the same utterance. Polish is tuned for this workstation's STT output, not for raw whisper tokens. LifeOS already handles natural language; the question is what text *you* intended to send — and that's what linux-whisper's pipeline produces.

**Acceptable divergence:** `app_context` for context-aware LLM tone (focused-window detection) is `None` for phone audio — there is no focused X11/Wayland window. All other polish stages run normally.

**Not used from linux-whisper:** hotkey daemon, audio capture, VAD, text injection, system tray, snippets. whisper-relay has its own audio source (phone upload).

### Audio normalization: ffmpeg server-side

**Primary client:** Chrome mobile (`MediaRecorder` → `audio/webm;codecs=opus`).

Server-side ffmpeg converts uploaded audio to 16 kHz mono WAV/PCM before feeding the STT engine:

```bash
ffmpeg -y -i input -ar 16000 -ac 1 -f wav pipe:1
```

**Rationale:** Browser audio formats vary; server-side normalization keeps the STT adapter simple and matches linux-whisper's expected input regardless of client. Chrome is the Phase 1 target; other browsers are not guaranteed.

### LifeOS: HTTP client parity with web chat

**No LifeOS Python imports.** whisper-relay is an HTTP client only.

#### Submitting user text

```http
POST {LIFEOS_BASE_URL}/api/ask/stream
Content-Type: application/json

{"question": "<polished transcript>", "conversation_id": "..."}
```

Same endpoint and body shape as `api/services/telegram.py::chat_via_api` and the web chat UI.

#### Consuming SSE

Mirror `web/index.html` event handling:

| SSE event | whisper-relay action |
|-----------|---------------------|
| `content` | Accumulate for final response TTS |
| `status` | **Synthesize and queue short TTS clip immediately** (e.g. "Searching your calendar…") |
| `self_correction` | Clear accumulated content |
| `conversation_id` | Persist for multi-turn |
| `claude_intent` | Call `/api/chat/handoff` (below) |
| `error` | Speak error message |
| `done` | Finalize turn |

#### Engine handoffs

When SSE yields `claude_intent`, call the same endpoint as web chat:

```http
POST {LIFEOS_BASE_URL}/api/chat/handoff
Content-Type: application/json

{"engine": "claude_code"|"codex", "task": "...", "conversation_id": "..."}
```

Speak the confirmation message returned by LifeOS (or the equivalent handoff text). Do not block, substitute a fallback, or spawn workers locally.

**Reference implementations:**
- Web: `LifeOS/web/index.html` (~line 3936)
- Tests: `LifeOS/tests/test_chat_api.py` (`test_handoff_*`)
- Telegram: calls spawn helpers directly in-process (different client, same LifeOS outcome); whisper-relay uses the HTTP handoff endpoint for parity with web.

**Timeout:** 300 seconds (match Telegram client).

### TTS output

See **[ADR-003](003-kokoro-tts-bm-george.md)** for backend choice, voice, model paths, env vars, and implementation contract. This ADR covers only the adapter seam: `TTSAdapter.synthesize(text, turn_id, out_path, clip_id)` with markdown stripped; multiple clips per turn; `NullTTSAdapter` for CI.

## Rationale summary

| Choice | Why |
|--------|-----|
| Library import for linux-whisper | Reuses warm GPU engine and polish pipeline; no HTTP API exists on linux-whisper today |
| Polish ON | Desktop parity; same intended text to LifeOS |
| HTTP-only for LifeOS | Clean deploy boundary; whisper-relay is a client surface, not a LifeOS module |
| `/api/chat/handoff` on intent | LifeOS owns spawns; gateway mirrors web chat — not re-hosting |
| Status TTS | Audio parity with chat UI status messages during long tool rounds |
| ffmpeg server-side | Reliable format normalization from Chrome webm/opus |
| Port 8888 | Default; override with `VOICE_GATEWAY_PORT` in `.env` if needed |

## Alternatives considered

### STT only, polish OFF

**Rejected.** Would send different text to LifeOS than the desktop app would for the same speech. Polish latency (~tens–hundreds of ms) is acceptable for push-to-talk.

### Import LifeOS `chat_via_api` directly

**Rejected.** Couples repos at install time. HTTP keeps whisper-relay independently deployable. The SSE parsing logic is ~50 lines and stable.

### Subprocess / CLI invocation of linux-whisper

**Rejected.** No transcribe-only CLI exists today; would cold-start the GPU model per request.

### Gateway blocks `claude_intent` with spoken fallback

**Rejected.** Makes voice a crippled LifeOS surface. User expects voice to trigger the same workflows as chat.

### Piper / espeak as primary TTS

**Rejected** — [ADR-003](003-kokoro-tts-bm-george.md).

## Upstream repos: no Phase 1 changes

Phase 1 is implementable entirely in **whisper-relay**. No PRs required in sibling repos.

| Upstream | How whisper-relay uses it | Code change needed? |
|----------|---------------------------|---------------------|
| **linux-whisper** | Python library: `Config.load()`, `create_engine()`, `PolishPipeline` — same as `app.py` | **No** — public API sufficient |
| **LifeOS** | HTTP: `POST /api/ask/stream`, `POST /api/chat/handoff` — same as web chat | **No** — endpoints exist |

**Optional later (not blocking):** linux-whisper headless `transcribe` CLI for debugging; LifeOS doc mention of voice client surface. Track as whisper-relay issues only if needed.

## Consequences

### Adapter modules (planned)

```
src/voice_gateway/adapters/
  stt.py      → linux-whisper (STT + PolishPipeline)
  lifeos.py   → HTTP client (/api/ask/stream, /api/chat/handoff)
  tts.py      → Kokoro ([ADR-003](003-kokoro-tts-bm-george.md))
```

### Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `VOICE_GATEWAY_PORT` | `8888` | Bind port |
| `LIFEOS_BASE_URL` | `http://127.0.0.1:8000` | LifeOS HTTP client target |
| `LINUX_WHISPER_CONFIG` | `~/.config/linux-whisper/config.yaml` | Shared with desktop app |
| `FFMPEG_BIN` | `ffmpeg` | Audio normalization |

TTS env vars: [ADR-003](003-kokoro-tts-bm-george.md).

### Operational dependencies

1. LifeOS running and reachable at `LIFEOS_BASE_URL`.
2. linux-whisper installed with models; same config as desktop dictation.
3. ffmpeg on PATH.
4. Kokoro model files + espeak-ng ([ADR-003](003-kokoro-tts-bm-george.md)).
5. Tailscale Serve exposing `127.0.0.1:8888` to the tailnet.

## Related Documents

- [ADR-001: Voice transport layer](001-voice-transport-layer.md)
- [ADR-003: Kokoro TTS with bm_george](003-kokoro-tts-bm-george.md)
- [Code conventions](../specs/standards/code-conventions.md)
- [Testing standards](../specs/standards/testing-standards.md)
- LifeOS API reference — `/api/ask/stream` (upstream `docs/specs/product/api-reference.md`)
- linux-whisper README (upstream repo)
- GitHub issues #3–#7 (issue tracker)
