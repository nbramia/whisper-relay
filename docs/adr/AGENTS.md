# ADR directory

Architecture Decision Records for whisper-relay — **append-only** decision journal.

## Contents

| ADR | Title |
|-----|-------|
| [001](001-voice-transport-layer.md) | Voice transport layer (not an agent) |
| [002](002-upstream-integration-boundaries.md) | linux-whisper + LifeOS integration |

## Key Principles

- **Never modify** an accepted ADR's decision text — supersede with a new numbered ADR
- Naming: `NNN-short-title.md`
- Required frontmatter: Status, Last Updated, Decision
- End every ADR with `## Related Documents`
- TTS backend selection will be **ADR-003** when decided

## Related Documents

- [../AGENTS.md](../AGENTS.md) — documentation standards
- [../development-principles.md](../development-principles.md)
