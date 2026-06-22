# ADR directory

Architecture Decision Records for whisper-relay — **append-only** decision journal.

## Contents

| ADR | Title |
|-----|-------|
| [001](001-voice-transport-layer.md) | Voice transport layer (not an agent) |
| [002](002-upstream-integration-boundaries.md) | linux-whisper + LifeOS integration |
| [003](003-kokoro-tts-bm-george.md) | Kokoro TTS — `bm_george` voice |
| [004](004-dual-text-backends.md) | Dual text backends (LifeOS + Agent) |
| [005](005-lifeos-owned-chat-client.md) | LifeOS-owned `/chat` client (Accepted) |

## Key Principles

- **Never modify** an accepted ADR's decision text — supersede with a new numbered ADR
- Naming: `NNN-short-title.md`
- Required frontmatter: Status, Last Updated, Decision
- End every ADR with `## Related Documents`
- TTS backend selection is **ADR-003** (Kokoro `bm_george`)
- LifeOS vs OpenClaw Agent routing is **ADR-004** (voice-adapter HTTP client)
- LifeOS-owned client consolidation is **ADR-005** (reverse proxy, port `:9788`; Accepted — API-only after #21)

## Related Documents

- [../AGENTS.md](../AGENTS.md) — documentation standards
- [../development-principles.md](../development-principles.md)
