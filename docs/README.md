# Documentation — whisper-relay

## Where things live (single source of truth)

| Topic | Canonical doc | Everything else |
|-------|---------------|-----------------|
| Project intent & diagram | [README.md](../README.md) | — |
| Agent rules, invariants, boundaries | [AGENTS.md](../AGENTS.md) | [CLAUDE.md](../CLAUDE.md) adds escalation/mistakes only |
| Why transport layer, not agent | [adr/001](adr/001-voice-transport-layer.md) | README links here |
| linux-whisper + LifeOS integration | [adr/002](adr/002-upstream-integration-boundaries.md) | Issues #4, #5 cite this |
| TTS (Kokoro, `bm_george`, env vars) | [adr/003](adr/003-kokoro-tts-bm-george.md) | Do not duplicate config elsewhere |
| Engineering process (generic) | [development-principles.md](development-principles.md) | AGENTS.md links; no project-specific duplication |
| Python / test standards | [specs/standards/](specs/standards/) | — |
| What to build | [GitHub issues](https://github.com/nbramia/whisper-relay/issues) | Not duplicated in ADRs |

**Rule:** If a fact appears in two places, one must be a one-line pointer to the other.

## ADRs

| ADR | Title |
|-----|-------|
| [001](adr/001-voice-transport-layer.md) | Voice transport layer |
| [002](adr/002-upstream-integration-boundaries.md) | Upstream integration |
| [003](adr/003-kokoro-tts-bm-george.md) | Kokoro TTS |

Rules: [adr/AGENTS.md](adr/AGENTS.md)

## Upstream repos

Phase 1 requires **no code changes** in [linux-whisper](https://github.com/nbramia/linux-whisper) or [LifeOS](https://github.com/nbramia/LifeOS) — whisper-relay consumes public APIs/libraries only. See [ADR-002 § Upstream scope](adr/002-upstream-integration-boundaries.md#upstream-repos-no-phase-1-changes).

## Related repos

- [linux-whisper](https://github.com/nbramia/linux-whisper) — STT + polish (library import)
- [LifeOS](https://github.com/nbramia/LifeOS) — orchestrator (HTTP client)
