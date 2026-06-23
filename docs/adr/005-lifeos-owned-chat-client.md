# ADR-005: LifeOS-owned chat client (responsive /chat)

**Status:** Accepted
**Last Updated:** 2026-06-22
**Decision:** Accepted (cutover in whisper-relay #21)

## Context

whisper-relay shipped a standalone mobile UI (`static/`) alongside LifeOS `/chat`. Both were HTTP clients of the same orchestrator, but they diverged on persona selection, conversation UX, and feature depth. Consolidation planning split the work across LifeOS #358–#361 and whisper-relay #21–#22.

whisper-relay #22 implemented prep (port defaults, integration contract). LifeOS #361 shipped responsive `/chat` with voice; #21 removes `static/` and browser-facing listing proxies.

## Decision

### Client ownership

**LifeOS `/chat` is the single responsive client surface** for phone and desktop. There is **no `/mobile` route** and **no user-facing UI in whisper-relay**.

| Layer | Owner | Role |
|-------|-------|------|
| Chat UI (text + voice toggle, persona, backend, model) | LifeOS `web/chat/` | Browser client; same-origin with orchestrator |
| Orchestrator + conversation DB | LifeOS API | Unchanged |
| Voice transport (STT → text backend → TTS) | whisper-relay | API-only |

whisper-relay **retains the transport-only invariant** ([ADR-001](001-voice-transport-layer.md)): no agent tools, no orchestrator session logic, no persona resolution for browsers.

### Integration topology (primary path)

LifeOS **reverse-proxies** voice API paths to whisper-relay so the browser stays **same-origin**:

```
Phone browser → Tailscale HTTPS → LifeOS /chat
                                    ├─ Text:      POST /api/ask/stream (+ persona_id, model_override, modality=voice)
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

Default bind port is **`9788`**, reconciled across `config.py`, `.env.example`, README, and deploy scripts.

### API surface (post-cutover)

whisper-relay **keeps** voice turn endpoints:

- `POST /api/voice/turn`, `POST /api/voice/turn/stream`
- `GET /api/voice/audio/{turn_id}/{clip_id}`
- `POST /api/voice/turn/{turn_id}/cancel`
- `GET /health`, `GET /health/backends`

whisper-relay **drops** browser-facing listing proxies (`GET /api/voice/personas`, `/api/voice/conversations*`) — LifeOS owns persona and conversation listing for all input modes.

`GET /` returns **301** to `{LIFEOS_BASE_URL}/chat` for legacy bookmarks.

### Input dimensions (LifeOS client)

All manual; no autoselect:

1. **Backend** — LifeOS \| Agent ([ADR-004](004-dual-text-backends.md))
2. **Persona** — from `GET /api/personas`; default `primary` (LifeOS mode only)
3. **Model** — per-turn picker (`model_override` on ask/stream and voice turns)
4. **Input** — Voice \| Text (swaps composer vs voice dock)
5. **Conversation** — scoped by backend × persona in `sessionStorage`

### Tailscale

**Phone bookmark:** `https://<machine>.<tailnet>.ts.net/chat` (LifeOS on HTTPS :443). Do not expose whisper-relay UI on the tailnet — `whisper-relay-tailscale.service` is deprecated; use `lifeos-tailscale.service` in LifeOS instead.

## Consequences

### Positive

- One client codebase; no duplicate persona/thread logic in whisper-relay
- Same-origin voice calls via proxy simplify secure-context and deployment
- whisper-relay release cycle decoupled from chat UX

### Negative / migration

- Old whisper-relay root URL → 301 to LifeOS `/chat` (local `LIFEOS_BASE_URL`); update phone bookmarks to LifeOS HTTPS `/chat`

## Related Documents

- [001-voice-transport-layer.md](001-voice-transport-layer.md) — transport invariant preserved
- [002-upstream-integration-boundaries.md](002-upstream-integration-boundaries.md) — LifeOS HTTP client boundaries
- [004-dual-text-backends.md](004-dual-text-backends.md) — LifeOS \| Agent routing
- [nbramia/LifeOS#358](https://github.com/nbramia/LifeOS/issues/358) — chat module extraction
- [nbramia/LifeOS#361](https://github.com/nbramia/LifeOS/issues/361) — responsive /chat + Voice|Text
- [nbramia/whisper-relay#21](https://github.com/nbramia/whisper-relay/issues/21) — static cutover (this ADR finalized)
- [nbramia/whisper-relay#22](https://github.com/nbramia/whisper-relay/issues/22) — prep
