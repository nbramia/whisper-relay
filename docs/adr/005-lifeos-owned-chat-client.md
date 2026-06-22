# ADR-005: LifeOS-owned chat client (responsive /chat)

**Status:** Proposed
**Last Updated:** 2026-06-21
**Decision:** Proposed (finalize Accepted in whisper-relay #21 after LifeOS #361 ships)

## Context

whisper-relay shipped a standalone mobile UI (`static/`) alongside LifeOS `/chat`. Both are HTTP clients of the same orchestrator, but they diverged on persona selection, conversation UX, and feature depth. Consolidation planning split the work across LifeOS #358–#361 and whisper-relay #21–#22.

This ADR records the **target architecture** before cutover. whisper-relay #22 implements the prep (port defaults, integration contract); #21 removes `static/` once LifeOS responsive `/chat` with voice is live.

## Decision

### Client ownership

**LifeOS `/chat` becomes the single responsive client surface** for phone and desktop. There is **no `/mobile` route** and no long-term user-facing UI in whisper-relay.

| Layer | Owner | Role |
|-------|-------|------|
| Chat UI (text + voice toggle, persona, backend) | LifeOS `web/chat/` | Browser client; same-origin with orchestrator |
| Orchestrator + conversation DB | LifeOS API | Unchanged |
| Voice transport (STT → text backend → TTS) | whisper-relay | API-only after cutover (#21) |

whisper-relay **retains the transport-only invariant** ([ADR-001](001-voice-transport-layer.md)): no agent tools, no orchestrator session logic, no persona resolution.

### Integration topology (primary path)

LifeOS **reverse-proxies** voice API paths to whisper-relay so the browser stays **same-origin**:

```
Phone browser → Tailscale HTTPS → LifeOS /chat
                                    ├─ Text:      POST /api/ask/stream (+ persona_id)
                                    ├─ Agent-text: LifeOS server → voice-adapter (token server-side)
                                    └─ Voice:      POST /api/voice/turn/stream (proxied)
                                                       ↓
                                              whisper-relay :9788 (localhost)
```

**Why reverse proxy over CORS**

| Approach | Verdict |
|----------|---------|
| LifeOS reverse-proxies `/api/voice/*` → `VOICE_GATEWAY_URL` | **Primary** — one HTTPS origin, one bookmark (`/chat`), no cross-origin mic/CORS complexity |
| Browser calls whisper-relay directly with CORS | **Fallback only** — document if proxy is unavailable; not the default integration |

LifeOS reads whisper-relay at **`VOICE_GATEWAY_URL=http://127.0.0.1:9788`** (server-side env). whisper-relay binds **`127.0.0.1:9788`** by default (`VOICE_GATEWAY_PORT=9788`).

### Port default

Default bind port is **`9788`**, reconciled across `config.py`, `.env.example`, README, and deploy scripts. Earlier docs referenced `:8888`; new deployments should use `:9788`. `TAILNET_HTTP_PORT` (Tailscale Serve front port) remains independent.

### API surface after cutover (#21)

whisper-relay **keeps** voice turn endpoints:

- `POST /api/voice/turn`, `POST /api/voice/turn/stream`
- `GET /api/voice/audio/{turn_id}/{clip_id}`
- `GET /health`, `GET /health/backends`

whisper-relay **drops** browser-facing listing proxies (`GET /api/voice/personas`, `/api/voice/conversations*`) — LifeOS owns persona and conversation listing for all input modes.

### Input dimensions (LifeOS client)

All manual; no autoselect:

1. **Backend** — LifeOS \| Agent ([ADR-004](004-dual-text-backends.md))
2. **Persona** — from `GET /api/personas`; default `primary` (LifeOS mode only)
3. **Input** — Voice \| Text (swaps composer vs hold-to-talk dock only)
4. **Conversation** — scoped by backend × persona in `sessionStorage`

## Consequences

### Positive

- One client codebase; no duplicate persona/thread logic in whisper-relay `static/`
- Same-origin voice calls via proxy simplify secure-context and deployment
- whisper-relay release cycle decoupled from chat UX

### Negative / migration

- Phone bookmark moves from whisper-relay root → LifeOS `/chat` (#21 redirect during migration)
- Until #361 ships, `static/` remains the interim mobile UI

## Related Documents

- [001-voice-transport-layer.md](001-voice-transport-layer.md) — transport invariant preserved
- [002-upstream-integration-boundaries.md](002-upstream-integration-boundaries.md) — LifeOS HTTP client boundaries
- [004-dual-text-backends.md](004-dual-text-backends.md) — LifeOS \| Agent routing
- [nbramia/LifeOS#358](https://github.com/nbramia/LifeOS/issues/358) — chat module extraction
- [nbramia/LifeOS#361](https://github.com/nbramia/LifeOS/issues/361) — responsive /chat + Voice|Text
- [nbramia/whisper-relay#21](https://github.com/nbramia/whisper-relay/issues/21) — static cutover (finalize this ADR)
- [nbramia/whisper-relay#22](https://github.com/nbramia/whisper-relay/issues/22) — prep (this ADR draft)
