# Documentation — whisper-relay

## Where things live (single source of truth)

| Topic | Canonical doc | Everything else |
|-------|---------------|-----------------|
| Project intent & diagram | [README.md](../README.md) | — |
| Agent rules, invariants, boundaries | [AGENTS.md](../AGENTS.md) | [CLAUDE.md](../CLAUDE.md) adds escalation/mistakes only |
| Why transport layer, not agent | [adr/001](adr/001-voice-transport-layer.md) | README links here |
| linux-whisper + LifeOS integration | [adr/002](adr/002-upstream-integration-boundaries.md) | Issues #4, #5 cite this |
| Dual text backends (LifeOS + Agent) | [adr/004](adr/004-dual-text-backends.md) | UI toggle; voice-adapter in agents repo |
| LifeOS-owned client + reverse proxy | [adr/005](adr/005-lifeos-owned-chat-client.md) | Proposed; port `:9788`, `VOICE_GATEWAY_URL` |
| TTS (Kokoro, `bm_george`, env vars) | [adr/003](adr/003-kokoro-tts-bm-george.md) | Do not duplicate config elsewhere |
| Engineering process (generic) | [development-principles.md](development-principles.md) | AGENTS.md links; no project-specific duplication |
| Python / test standards | [specs/standards/](specs/standards/) | — |
| What to build | Repository issue tracker | Not duplicated in ADRs |

**Rule:** If a fact appears in two places, one must be a one-line pointer to the other.

## ADRs

| ADR | Title |
|-----|-------|
| [001](adr/001-voice-transport-layer.md) | Voice transport layer |
| [002](adr/002-upstream-integration-boundaries.md) | Upstream integration |
| [003](adr/003-kokoro-tts-bm-george.md) | Kokoro TTS |
| [004](adr/004-dual-text-backends.md) | Dual text backends (LifeOS + Agent) |
| [005](adr/005-lifeos-owned-chat-client.md) | LifeOS-owned `/chat` client (Proposed) |

Rules: [adr/AGENTS.md](adr/AGENTS.md)

## Upstream repos

Phase 1 requires **no code changes** in **linux-whisper** or **LifeOS** for the default LifeOS path — whisper-relay consumes public APIs/libraries only. **Agent mode** adds a second HTTP client to the OpenClaw **voice-adapter** in the [agents](https://github.com/nbramia/agents) repo (see [ADR-004](adr/004-dual-text-backends.md)). See [ADR-002 § Upstream scope](adr/002-upstream-integration-boundaries.md#upstream-repos-no-phase-1-changes).

## Related repos

- **linux-whisper** — STT + polish (library import)
- **LifeOS** — orchestrator (HTTP client, default backend)
- **agents** — OpenClaw voice-adapter for Agent mode (`AGENT_BACKEND_URL`, default `:8100`)
